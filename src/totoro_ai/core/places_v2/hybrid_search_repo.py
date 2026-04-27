"""HybridSearchRepo — vector + FTS retrieval with RRF fusion.

One SQL round-trip:

  1. `filtered` CTE applies HybridSearchFilters to places_v2 once
     (category, tags, city/neighborhood/country, geo via earth_box,
     created_at range).
  2. `vec` CTE: kNN over place_embeddings_v2.vector (cosine, HNSW
     index), restricted to filtered ids. Top candidate_limit by rank.
  3. `txt` CTE: full-text on places_v2.search_vector via
     `websearch_to_tsquery('simple_unaccent', :query_text)` with
     ts_rank_cd respecting the per-field weights (A/B/C). Top
     candidate_limit by rank.
  4. `fused`: FULL OUTER JOIN on place_id, RRF score
     `1/(k + v_rank) + 1/(k + t_rank)` (NULL ranks contribute 0).
  5. Final SELECT joins back to places_v2 to materialize PlaceCore
     and order by rrf_score DESC limited to `limit`.

Does not embed — the caller passes the query vector. Service layer
owns the embedder.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    HybridSearchFilters,
    HybridSearchHit,
    LocationContext,
    PlaceCategory,
    PlaceCore,
    PlaceNameAlias,
    PlaceTag,
)

logger = logging.getLogger(__name__)


class HybridSearchRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query: str,
        query_vector: list[float],
        filters: HybridSearchFilters | None = None,
        limit: int = 20,
        rrf_k: int = 60,
        candidate_multiplier: int = 4,
    ) -> list[HybridSearchHit]:
        filters = filters or HybridSearchFilters()
        where_sql, where_params = _build_filter_clause(filters)
        candidate_limit = limit * candidate_multiplier

        # pgvector accepts the textual literal "[v1,v2,...]" and casts
        # implicitly because the LHS column is typed as vector.
        qvec_lit = "[" + ",".join(repr(float(v)) for v in query_vector) + "]"

        sql = text(
            f"""
            WITH filtered AS (
                SELECT id FROM places_v2
                WHERE {where_sql}
            ),
            vec AS (
                SELECT
                    pe.place_id,
                    ROW_NUMBER() OVER (
                        ORDER BY pe.vector <=> :query_vector
                    ) AS rank
                FROM place_embeddings_v2 pe
                JOIN filtered f ON f.id = pe.place_id
                ORDER BY pe.vector <=> :query_vector
                LIMIT :candidate_limit
            ),
            txt AS (
                SELECT
                    p.id AS place_id,
                    ROW_NUMBER() OVER (
                        ORDER BY ts_rank_cd(p.search_vector, q.tsq) DESC
                    ) AS rank
                FROM places_v2 p
                JOIN filtered f ON f.id = p.id
                CROSS JOIN (
                    SELECT websearch_to_tsquery(
                        'simple_unaccent', :query_text
                    ) AS tsq
                ) q
                WHERE p.search_vector @@ q.tsq
                LIMIT :candidate_limit
            ),
            fused AS (
                SELECT
                    COALESCE(vec.place_id, txt.place_id) AS place_id,
                    COALESCE(1.0 / (:rrf_k + vec.rank), 0)
                        + COALESCE(1.0 / (:rrf_k + txt.rank), 0) AS rrf_score,
                    vec.rank AS vector_rank,
                    txt.rank AS text_rank
                FROM vec
                FULL OUTER JOIN txt ON vec.place_id = txt.place_id
            )
            SELECT
                p.id, p.provider_id, p.place_name, p.place_name_aliases,
                p.category, p.tags, p.location, p.created_at, p.refreshed_at,
                fused.rrf_score, fused.vector_rank, fused.text_rank
            FROM fused
            JOIN places_v2 p ON p.id = fused.place_id
            ORDER BY fused.rrf_score DESC
            LIMIT :limit
            """
        )

        exec_params: dict[str, Any] = {
            **where_params,
            "query_text": query,
            "query_vector": qvec_lit,
            "rrf_k": rrf_k,
            "candidate_limit": candidate_limit,
            "limit": limit,
        }

        try:
            result = await self._session.execute(sql, exec_params)
        except Exception as exc:
            logger.error(
                "hybrid_search.failed",
                extra={"error": str(exc), "query": query},
            )
            raise

        return [_row_to_hit(row) for row in result.mappings()]


# ---------------------------------------------------------------------------
# Filter clause builder
# ---------------------------------------------------------------------------


def _build_filter_clause(
    filters: HybridSearchFilters,
) -> tuple[str, dict[str, Any]]:
    """Render HybridSearchFilters as a WHERE fragment + bound params.

    Every value is bound by name; nothing user-supplied is interpolated
    into SQL text.
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if filters.category is not None:
        conditions.append("category = :f_category")
        params["f_category"] = filters.category.value

    if filters.tags:
        for i, tag in enumerate(filters.tags):
            key = f"f_tag_{i}"
            conditions.append(f"tags @> :{key}::jsonb")
            params[key] = json.dumps([{"value": tag}])

    if filters.city:
        conditions.append("location->>'city' ILIKE :f_city")
        params["f_city"] = f"%{filters.city}%"

    if filters.neighborhood:
        conditions.append("location->>'neighborhood' ILIKE :f_neighborhood")
        params["f_neighborhood"] = f"%{filters.neighborhood}%"

    if filters.country:
        conditions.append("location->>'country' = :f_country")
        params["f_country"] = filters.country

    if (
        filters.lat is not None
        and filters.lng is not None
        and filters.radius_m is not None
    ):
        conditions.append(
            "location IS NOT NULL"
            " AND location->>'lat' IS NOT NULL"
            " AND location->>'lng' IS NOT NULL"
            " AND earth_box("
            "    ll_to_earth(:f_lat, :f_lng), :f_radius_m"
            " ) @> ll_to_earth("
            "    (location->>'lat')::float8,"
            "    (location->>'lng')::float8"
            " )"
        )
        params["f_lat"] = filters.lat
        params["f_lng"] = filters.lng
        params["f_radius_m"] = float(filters.radius_m)

    if filters.created_after is not None:
        conditions.append("created_at >= :f_created_after")
        params["f_created_after"] = filters.created_after

    if filters.created_before is not None:
        conditions.append("created_at <= :f_created_before")
        params["f_created_before"] = filters.created_before

    where = " AND ".join(conditions) if conditions else "TRUE"
    return where, params


# ---------------------------------------------------------------------------
# Row → HybridSearchHit
# ---------------------------------------------------------------------------


def _row_to_hit(row: Any) -> HybridSearchHit:
    tags = [PlaceTag.model_validate(t) for t in (row.get("tags") or [])]
    aliases = [
        PlaceNameAlias.model_validate(a)
        for a in (row.get("place_name_aliases") or [])
    ]
    loc_raw = row.get("location")
    location = LocationContext.model_validate(loc_raw) if loc_raw else None
    place = PlaceCore(
        id=row.get("id"),
        provider_id=row.get("provider_id"),
        place_name=row["place_name"],
        place_name_aliases=aliases,
        category=PlaceCategory(row["category"]) if row.get("category") else None,
        tags=tags,
        location=location,
        created_at=_to_datetime(row.get("created_at")),
        refreshed_at=_to_datetime(row.get("refreshed_at")),
    )
    return HybridSearchHit(
        place=place,
        rrf_score=float(row["rrf_score"]),
        vector_rank=int(row["vector_rank"]) if row.get("vector_rank") else None,
        text_rank=int(row["text_rank"]) if row.get("text_rank") else None,
    )


def _to_datetime(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None
