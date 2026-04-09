"""ExtractionPersistenceService — shared write-path for extraction results."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from totoro_ai.core.config import get_config
from totoro_ai.core.events.events import PlaceSaved
from totoro_ai.core.extraction.types import ExtractionResult
from totoro_ai.db.models import Place
from totoro_ai.db.repositories import EmbeddingRepository, PlaceRepository
from totoro_ai.providers.embeddings import EmbedderProtocol

if TYPE_CHECKING:
    from totoro_ai.core.events.dispatcher import EventDispatcherProtocol

logger = logging.getLogger(__name__)


@dataclass
class PlaceSaveOutcome:
    """Per-result outcome from save_and_emit.

    status values:
    - "saved": written to DB; place_id is the new UUID
    - "duplicate": already in DB; place_id is the existing record's ID
    - "below_threshold": confidence < save_threshold; place_id is None
    """

    result: ExtractionResult
    place_id: str | None
    status: str


class ExtractionPersistenceService:
    """Shared write-path for extraction results (inline and background paths).

    Ordering invariant: DB writes → PlaceSaved dispatch → bulk embeddings.
    """

    def __init__(
        self,
        place_repo: PlaceRepository,
        embedding_repo: EmbeddingRepository,
        embedder: EmbedderProtocol,
        event_dispatcher: "EventDispatcherProtocol",
    ) -> None:
        self._place_repo = place_repo
        self._embedding_repo = embedding_repo
        self._embedder = embedder
        self._event_dispatcher = event_dispatcher

    async def save_and_emit(
        self, results: list[ExtractionResult], user_id: str
    ) -> list[PlaceSaveOutcome]:
        """Save extraction results to DB and emit PlaceSaved event.

        Enforces save_threshold from config — places below threshold are
        included in the returned outcomes with status "below_threshold" but
        are never written to the database.

        Returns:
            One PlaceSaveOutcome per input result, with status "saved",
            "duplicate", or "below_threshold".
        """
        save_threshold = get_config().extraction.confidence.save_threshold
        outcomes: list[PlaceSaveOutcome] = []
        saved_ids: list[str] = []
        saved_results: list[ExtractionResult] = []

        for result in results:
            # Threshold check — skip DB write but still surface in response
            if round(result.confidence, 2) < save_threshold:
                outcomes.append(
                    PlaceSaveOutcome(
                        result=result, place_id=None, status="below_threshold"
                    )
                )
                continue

            # Dedup check — only when external_id is known
            if result.external_id is not None:
                existing = await self._place_repo.get_by_provider(
                    result.external_provider or "unknown", result.external_id
                )
                if existing:
                    outcomes.append(
                        PlaceSaveOutcome(
                            result=result, place_id=existing.id, status="duplicate"
                        )
                    )
                    continue

            place_id = str(uuid4())
            place = Place(
                id=place_id,
                user_id=user_id,
                place_name=result.place_name,
                address=result.address or "",
                cuisine=result.cuisine,
                price_range=None,
                lat=result.lat,
                lng=result.lng,
                source_url=None,
                external_provider=result.external_provider or "unknown",
                external_id=result.external_id,
                confidence=result.confidence,
                source=result.resolved_by.value,
            )
            await self._place_repo.save(place)
            saved_ids.append(place_id)
            saved_results.append(result)
            outcomes.append(
                PlaceSaveOutcome(result=result, place_id=place_id, status="saved")
            )

        if not saved_ids:
            return outcomes

        # Dispatch PlaceSaved AFTER all DB writes (ordering invariant)
        event = PlaceSaved(
            user_id=user_id,
            place_ids=saved_ids,
            place_metadata={},
        )
        await self._event_dispatcher.dispatch(event)

        # Embed all saved places in one batch (non-fatal on failure)
        try:
            descriptions = [self._build_description(r) for r in saved_results]
            vectors = await self._embedder.embed(descriptions, input_type="document")
            model_name = get_config().models["embedder"].model
            records = [
                (pid, vec, model_name)
                for pid, vec in zip(saved_ids, vectors, strict=True)
            ]
            await self._embedding_repo.bulk_upsert_embeddings(records)
        except Exception as e:
            logger.warning(
                "Failed to generate/store embeddings (non-fatal): %s. "
                "Places saved, taste signal captured.",
                e,
                exc_info=True,
            )

        return outcomes

    def _build_description(self, result: ExtractionResult) -> str:
        """Build embedding input text from extraction result fields."""
        parts = [result.place_name]
        if result.cuisine:
            parts.append(result.cuisine)
        if result.address:
            parts.append(result.address)
        return get_config().embeddings.description_separator.join(parts)
