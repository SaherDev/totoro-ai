"""HybridSearchRepo — vector + FTS retrieval with RRF fusion.

One SQL round-trip composed via the SQLAlchemy expression API:

  1. `filtered` CTE applies HybridSearchFilters to places_v2 once
     (category, tags, city/neighborhood/country, geo via earth_box,
     created_at range).
  2. `vec` CTE: kNN over place_embeddings_v2.vector (cosine, HNSW
     index), restricted to filtered ids. Top candidate_limit by rank.
  3. `txt` CTE: full-text on places_v2.search_vector via
     `websearch_to_tsquery('simple_unaccent', :q)` with ts_rank_cd
     respecting the per-field weights (A/B/C). Top candidate_limit
     by rank.
  4. `fused`: FULL OUTER JOIN on place_id, RRF score
     `1/(k + v_rank) + 1/(k + t_rank)` (NULL ranks contribute 0).
  5. Final SELECT joins back to places_v2 to materialize PlaceCore
     and orders by rrf_score DESC limited to `limit`.

Does not embed — the caller passes the query vector. Service layer
owns the embedder.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    Column,
    ColumnElement,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    and_,
    cast,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings_repo import EMBEDDING_DIMENSIONS
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


# ---------------------------------------------------------------------------
# Local Table references — typed columns for native query building.
# Matches the per-repo pattern used by places_repo / user_places_repo /
# embeddings_repo. The search_vector column is added here because this
# repo is the one that queries it.
# ---------------------------------------------------------------------------

_metadata = MetaData()

_PlacesV2Table = Table(
    "places_v2",
    _metadata,
    Column("id", String),
    Column("provider_id", String),
    Column("place_name", String),
    Column("place_name_aliases", JSONB),
    Column("category", String),
    Column("tags", JSONB),
    Column("location", JSONB),
    Column("created_at", DateTime(timezone=True)),
    Column("refreshed_at", DateTime(timezone=True)),
    Column("search_vector", TSVECTOR),
)
_p = _PlacesV2Table.c

_PlaceEmbeddingsTable = Table(
    "place_embeddings_v2",
    _metadata,
    Column("id", String),
    Column("place_id", String),
    Column("vector", Vector(EMBEDDING_DIMENSIONS)),
    Column("model_name", String),
    Column("text_hash", String),
    Column("created_at", DateTime(timezone=True)),
)
_e = _PlaceEmbeddingsTable.c


_TS_CONFIG = "simple_unaccent"  # custom config from the FTS migration


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
        candidate_limit = limit * candidate_multiplier

        # ---- filtered CTE ------------------------------------------------
        filtered = (
            select(_p.id)
            .where(and_(*_filter_conditions(filters)))
            .cte("filtered")
        )

        # ---- vec CTE -----------------------------------------------------
        # pgvector's cosine_distance binds the list as a vector parameter.
        cosine_dist = _e.vector.cosine_distance(query_vector)
        vec = (
            select(
                _e.place_id.label("place_id"),
                func.row_number().over(order_by=cosine_dist).label("rank"),
            )
            .select_from(
                _PlaceEmbeddingsTable.join(
                    filtered, filtered.c.id == _e.place_id
                )
            )
            .order_by(cosine_dist)
            .limit(candidate_limit)
            .cte("vec")
        )

        # ---- txt CTE -----------------------------------------------------
        # PG implicitly casts the first arg to regconfig at runtime, so
        # passing the config name as a plain string param is fine.
        tsq = func.websearch_to_tsquery(_TS_CONFIG, query)
        text_rank = func.ts_rank_cd(_p.search_vector, tsq)
        txt = (
            select(
                _p.id.label("place_id"),
                func.row_number().over(order_by=text_rank.desc()).label("rank"),
            )
            .select_from(
                _PlacesV2Table.join(filtered, filtered.c.id == _p.id)
            )
            .where(_p.search_vector.op("@@")(tsq))
            .order_by(text_rank.desc())
            .limit(candidate_limit)
            .cte("txt")
        )

        # ---- fused CTE (FULL OUTER JOIN + RRF) ---------------------------
        rrf_score = (
            func.coalesce(1.0 / (rrf_k + vec.c.rank), 0)
            + func.coalesce(1.0 / (rrf_k + txt.c.rank), 0)
        ).label("rrf_score")
        fused = (
            select(
                func.coalesce(vec.c.place_id, txt.c.place_id).label("place_id"),
                rrf_score,
                vec.c.rank.label("vector_rank"),
                txt.c.rank.label("text_rank"),
            )
            .select_from(
                vec.outerjoin(txt, vec.c.place_id == txt.c.place_id, full=True)
            )
            .cte("fused")
        )

        # ---- final SELECT — materialize PlaceCore + scores ---------------
        stmt = (
            select(
                _p.id,
                _p.provider_id,
                _p.place_name,
                _p.place_name_aliases,
                _p.category,
                _p.tags,
                _p.location,
                _p.created_at,
                _p.refreshed_at,
                fused.c.rrf_score,
                fused.c.vector_rank,
                fused.c.text_rank,
            )
            .select_from(fused.join(_PlacesV2Table, _p.id == fused.c.place_id))
            .order_by(fused.c.rrf_score.desc())
            .limit(limit)
        )

        try:
            result = await self._session.execute(stmt)
        except Exception as exc:
            logger.error(
                "hybrid_search.failed",
                extra={"error": str(exc), "query": query},
            )
            raise

        return [_row_to_hit(row._mapping) for row in result]


# ---------------------------------------------------------------------------
# Filter conditions — built from typed columns, not text fragments
# ---------------------------------------------------------------------------


def _filter_conditions(
    filters: HybridSearchFilters,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []

    if filters.category is not None:
        conditions.append(_p.category == filters.category.value)

    if filters.tags:
        # AND semantics: every requested tag value must be present.
        # Mirrors places_repo.find() — pre-stringify the JSONB literal
        # because cast() expects a primitive bind value.
        for tag_val in filters.tags:
            conditions.append(
                _p.tags.op("@>")(
                    cast(json.dumps([{"value": tag_val}]), JSONB)
                )
            )

    if filters.city:
        conditions.append(_p.location["city"].astext.ilike(f"%{filters.city}%"))

    if filters.neighborhood:
        conditions.append(
            _p.location["neighborhood"].astext.ilike(f"%{filters.neighborhood}%")
        )

    if filters.country:
        conditions.append(_p.location["country"].astext == filters.country)

    if (
        filters.lat is not None
        and filters.lng is not None
        and filters.radius_m is not None
    ):
        geo_lat = cast(_p.location["lat"].astext, Float())
        geo_lng = cast(_p.location["lng"].astext, Float())
        query_box = func.earth_box(
            func.ll_to_earth(filters.lat, filters.lng), float(filters.radius_m)
        )
        conditions.extend(
            [
                _p.location.isnot(None),
                _p.location["lat"].astext.isnot(None),
                _p.location["lng"].astext.isnot(None),
                query_box.op("@>")(func.ll_to_earth(geo_lat, geo_lng)),
            ]
        )

    if filters.created_after is not None:
        conditions.append(_p.created_at >= filters.created_after)

    if filters.created_before is not None:
        conditions.append(_p.created_at <= filters.created_before)

    return conditions


# ---------------------------------------------------------------------------
# Row → HybridSearchHit
# ---------------------------------------------------------------------------


def _row_to_hit(row: Mapping[str, Any]) -> HybridSearchHit:
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
    v_rank = row.get("vector_rank")
    t_rank = row.get("text_rank")
    return HybridSearchHit(
        place=place,
        rrf_score=float(row["rrf_score"]),
        vector_rank=int(v_rank) if v_rank is not None else None,
        text_rank=int(t_rank) if t_rank is not None else None,
    )


def _to_datetime(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None
