"""Three-phase extraction pipeline service (ADR-008, ADR-034).

Phase 1: Enrichment — run all enrichers, populate context, dedup candidates
Phase 2: Validation — validate candidates via Google Places in parallel
Phase 3: Background — dispatch heavy enrichers if nothing validated
"""

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from totoro_ai.api.schemas.extract_place import (
    ExtractedPlaceSchema,
    ExtractPlaceResponse,
    ProvisionalResponse,
)
from totoro_ai.core.config import ExtractionConfig, get_config
from totoro_ai.core.events.events import ExtractionPending, PlaceSaved
from totoro_ai.core.extraction.dedup import dedup_candidates
from totoro_ai.core.extraction.input_parser import parse_input
from totoro_ai.core.extraction.models import ExtractionContext, ExtractionLevel
from totoro_ai.core.extraction.protocols import Enricher
from totoro_ai.core.extraction.result import ExtractionResult
from totoro_ai.core.extraction.validator import GooglePlacesValidator
from totoro_ai.db.models import Place
from totoro_ai.db.repositories import EmbeddingRepository, PlaceRepository
from totoro_ai.providers.embeddings import EmbedderProtocol

if TYPE_CHECKING:
    from totoro_ai.core.events.dispatcher import EventDispatcherProtocol

logger = logging.getLogger(__name__)


class ExtractionService:
    """Orchestrate the three-phase extraction pipeline."""

    def __init__(
        self,
        enricher_chain: list[Enricher],
        validator: GooglePlacesValidator,
        place_repo: PlaceRepository,
        extraction_config: ExtractionConfig,
        embedder: EmbedderProtocol,
        embedding_repo: EmbeddingRepository,
        event_dispatcher: "EventDispatcherProtocol",
        background_pending_levels: list[ExtractionLevel] | None = None,
    ) -> None:
        self._enricher_chain = enricher_chain
        self._validator = validator
        self._place_repo = place_repo
        self._extraction_config = extraction_config
        self._embedder = embedder
        self._embedding_repo = embedding_repo
        self._event_dispatcher = event_dispatcher
        self._background_pending_levels = background_pending_levels or [
            ExtractionLevel.SUBTITLE_CHECK,
            ExtractionLevel.WHISPER_AUDIO,
            ExtractionLevel.VISION_FRAMES,
        ]

    async def run(
        self, raw_input: str, user_id: str
    ) -> ExtractPlaceResponse | ProvisionalResponse:
        """Execute the three-phase extraction pipeline.

        Args:
            raw_input: TikTok URL, plain text, or mixed input
            user_id: User identifier (validated by NestJS)

        Returns:
            ExtractPlaceResponse with validated places, or
            ProvisionalResponse when background processing is dispatched

        Raises:
            ValueError: If raw_input is empty
        """
        if not raw_input or not raw_input.strip():
            raise ValueError("raw_input cannot be empty")

        parsed = parse_input(raw_input)

        context = ExtractionContext(
            url=parsed.url,
            user_id=user_id,
            supplementary_text=parsed.supplementary_text,
        )

        # Phase 1: Enrichment — run all enrichers, then dedup
        for enricher in self._enricher_chain:
            await enricher.enrich(context)
        dedup_candidates(context)

        # Phase 2: Validation — validate candidates via Google Places
        if context.candidates:
            results = await self._validator.validate(
                context.candidates, source_url=context.url
            )
            if results:
                response = await self._save_results(results, user_id, context.url)
                return response

        # Phase 3: Background — dispatch heavy enrichers if nothing validated
        pending = self._background_pending_levels if context.url else []

        if pending:
            await self._event_dispatcher.dispatch(
                ExtractionPending(
                    user_id=user_id,
                    url=context.url,
                    supplementary_text=context.supplementary_text,
                    pending_levels=[level.value for level in pending],
                )
            )

        return ProvisionalResponse(
            pending_levels=pending,
        )

    async def _save_results(
        self,
        results: list[ExtractionResult],
        user_id: str,
        source_url: str | None,
    ) -> ExtractPlaceResponse:
        """Save validated results to database and dispatch events.

        Uses batch save (single dedup query + single commit) instead of
        N sequential saves.
        """
        thresholds = self._extraction_config.thresholds

        # Split results into saveable vs confirmation-required
        saveable: list[tuple[ExtractionResult, Place]] = []
        place_schemas: list[ExtractedPlaceSchema] = []

        for result in results:
            requires_confirmation = (
                result.confidence < thresholds.store_silently
            )
            above_threshold = (
                result.confidence > thresholds.require_confirmation
            )

            if not requires_confirmation and above_threshold:
                place_id = str(uuid4())
                place = Place(
                    id=place_id,
                    user_id=user_id,
                    place_name=result.place_name,
                    address=result.address or "",
                    cuisine=result.cuisine,
                    source_url=source_url,
                    external_provider=result.external_provider or "google",
                    external_id=result.external_id,
                    confidence=result.confidence,
                    source=result.resolved_by.value,
                )
                saveable.append((result, place))
            else:
                place_schemas.append(
                    self._to_schema(result, None, requires_confirmation)
                )

        # Batch save — one dedup query + one commit
        saved_place_ids: list[str] = []
        saved_metadata: list[dict[str, object]] = []

        if saveable:
            places_to_save = [place for _, place in saveable]
            saved_places = await self._place_repo.save_many(places_to_save)

            for (result, _), saved_place in zip(saveable, saved_places, strict=False):
                place_schemas.append(
                    self._to_schema(result, saved_place.id, False)
                )
                saved_place_ids.append(saved_place.id)
                saved_metadata.append({
                    "cuisine": result.cuisine,
                    "source": result.resolved_by.value,
                })

        # Batch embeddings (non-fatal per ADR-040)
        if saved_place_ids:
            await self._generate_embeddings(
                [place for _, place in saveable]
            )

        # Dispatch batch PlaceSaved event
        if saved_place_ids:
            await self._event_dispatcher.dispatch(
                PlaceSaved(
                    user_id=user_id,
                    place_ids=saved_place_ids,
                    place_metadata=saved_metadata,
                )
            )

        return ExtractPlaceResponse(
            places=place_schemas,
            source_url=source_url,
        )

    @staticmethod
    def _to_schema(
        result: ExtractionResult,
        place_id: str | None,
        requires_confirmation: bool,
    ) -> ExtractedPlaceSchema:
        return ExtractedPlaceSchema(
            place_id=place_id,
            place_name=result.place_name,
            address=result.address,
            city=result.city,
            cuisine=result.cuisine,
            confidence=result.confidence,
            resolved_by=result.resolved_by,
            corroborated=result.corroborated,
            external_provider=result.external_provider,
            external_id=result.external_id,
            requires_confirmation=requires_confirmation,
        )

    async def _generate_embeddings(self, places: list[Place]) -> None:
        """Generate embeddings for saved places. Non-fatal."""
        try:
            descriptions = [self._build_description(p) for p in places]
            vectors = await self._embedder.embed(
                descriptions, input_type="document"
            )
            model_name = get_config().models["embedder"].model
            for place, vector in zip(places, vectors, strict=False):
                await self._embedding_repo.upsert_embedding(
                    place_id=place.id,
                    vector=vector,
                    model_name=model_name,
                )
        except Exception as e:
            logger.warning(
                "Failed to generate embeddings (non-fatal): %s",
                e,
                exc_info=True,
            )

    @staticmethod
    def _build_description(place: Place) -> str:
        """Build embedding input text from place fields."""
        parts = [place.place_name]
        if place.cuisine:
            parts.append(place.cuisine)
        if place.address:
            parts.append(place.address)
        separator = get_config().embeddings.description_separator
        return separator.join(parts)
