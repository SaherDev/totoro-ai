"""Extraction service orchestrating the extraction pipeline."""

import logging
from uuid import uuid4

from totoro_ai.api.errors import ExtractionFailedNoMatchError
from totoro_ai.api.schemas.extract_place import ExtractPlaceResponse
from totoro_ai.core.config import ExtractionConfig, get_config
from totoro_ai.core.extraction.confidence import compute_confidence
from totoro_ai.core.extraction.dispatcher import (
    ExtractionDispatcher,
    UnsupportedInputError,
)
from totoro_ai.core.extraction.places_client import PlacesClient
from totoro_ai.db.models import Place
from totoro_ai.db.repositories import EmbeddingRepository, PlaceRepository
from totoro_ai.providers.embeddings import EmbedderProtocol

logger = logging.getLogger(__name__)


class ExtractionService:
    """Orchestrate place extraction pipeline (ADR-008, ADR-034)."""

    @staticmethod
    def _build_description(place: Place) -> str:
        """Build embedding input text from place fields.

        Combines place_name, cuisine (if present), and address into a single
        description string for embedding, separated by the configured separator.

        Args:
            place: Place entity with name, cuisine, address

        Returns:
            Description string with configured separator
        """
        parts = [place.place_name]
        if place.cuisine:
            parts.append(place.cuisine)
        parts.append(place.address)
        separator = get_config().embeddings.description_separator
        return separator.join(parts)

    def __init__(
        self,
        dispatcher: ExtractionDispatcher,
        places_client: PlacesClient,
        place_repo: PlaceRepository,
        extraction_config: ExtractionConfig,
        embedder: EmbedderProtocol,
        embedding_repo: EmbeddingRepository,
    ) -> None:
        """Initialize service with dependencies.

        Args:
            dispatcher: ExtractionDispatcher for input routing
            places_client: PlacesClient for place validation
            place_repo: PlaceRepository for place persistence (handles transactions)
            extraction_config: Confidence weights and decision thresholds
            embedder: EmbedderProtocol for generating embeddings (ADR-038)
            embedding_repo: EmbeddingRepository for persisting embeddings
        """
        self._dispatcher = dispatcher
        self._places_client = places_client
        self._place_repo = place_repo
        self._extraction_config = extraction_config
        self._embedder = embedder
        self._embedding_repo = embedding_repo

    async def run(self, raw_input: str, user_id: str) -> ExtractPlaceResponse:
        """Extract and save (or confirm) a place from raw input.

        Pipeline:
        1. Validate raw_input not empty
        2. Dispatch to appropriate extractor
        3. Validate place against Google Places
        4. Compute confidence
        5. Check thresholds:
           - ≤ require_confirmation → error
           - require_confirmation < score < store_silently → requires_confirmation=True
           - ≥ store_silently → check dedup, save, return with place_id
        6. Dedup by (external_provider, external_id) if match found
        7. Write Place to database

        Args:
            raw_input: TikTok URL or plain text
            user_id: User identifier (validated by NestJS)

        Returns:
            ExtractPlaceResponse with place data and status

        Raises:
            ValueError: If raw_input is empty (→ 400)
            UnsupportedInputError: If no extractor matches (→ 422)
            ExtractionFailedNoMatchError: If confidence ≤ require_confirmation (→ 422)
        """
        # Step 1: Validate input
        if not raw_input or not raw_input.strip():
            raise ValueError("raw_input cannot be empty")

        # Step 2: Dispatch to extractor
        try:
            result = await self._dispatcher.dispatch(raw_input)
        except UnsupportedInputError:
            raise

        if result is None:
            raise ExtractionFailedNoMatchError("Extraction returned no result")

        extraction = result.extraction

        # Step 3: Validate against Google Places
        places_match = await self._places_client.validate_place(
            name=extraction.place_name,
            location=extraction.address,
        )

        # Step 4: Compute confidence
        confidence = compute_confidence(
            source=result.source,
            match_quality=places_match.match_quality,
            weights=self._extraction_config.confidence_weights,
            corroborated=False,
        )

        # Step 5: Apply thresholds
        thresholds = self._extraction_config.thresholds

        if confidence <= thresholds.require_confirmation:
            raise ExtractionFailedNoMatchError(
                f"Confidence too low: {confidence:.2f} ≤ {thresholds.require_confirmation}"  # noqa: E501
            )

        if confidence < thresholds.store_silently:
            return ExtractPlaceResponse(
                place_id=None,
                place=extraction,
                confidence=confidence,
                requires_confirmation=True,
                source_url=result.source_url,
            )

        # Step 6: Confidence ≥ store_silently — check deduplication
        if places_match.external_id:
            existing = await self._place_repo.get_by_provider(
                places_match.external_provider, places_match.external_id
            )

            if existing:
                return ExtractPlaceResponse(
                    place_id=existing.id,
                    place=extraction,
                    confidence=confidence,
                    requires_confirmation=False,
                    source_url=result.source_url,
                )

        # Step 7: Write new Place to database
        place_id = str(uuid4())
        place = Place(
            id=place_id,
            user_id=user_id,
            place_name=places_match.validated_name or extraction.place_name,
            address=extraction.address,
            cuisine=extraction.cuisine,
            price_range=extraction.price_range,
            lat=places_match.lat,
            lng=places_match.lng,
            source_url=result.source_url,
            external_provider=places_match.external_provider,
            external_id=places_match.external_id,
            confidence=confidence,
            source=result.source.value,
        )

        await self._place_repo.save(place)

        # Step 8: Generate and save embedding (ADR-040, ADR-025)
        try:
            description = self._build_description(place)
            vectors = await self._embedder.embed([description], input_type="document")
            model_name = get_config().models["embedder"].model
            await self._embedding_repo.upsert_embedding(
                place_id=place_id, vector=vectors[0], model_name=model_name
            )
        except Exception as e:
            logger.error(
                "Failed to generate embedding for place %s: %s", place_id, e
            )
            raise

        return ExtractPlaceResponse(
            place_id=place_id,
            place=extraction,
            confidence=confidence,
            requires_confirmation=False,
            source_url=result.source_url,
        )
