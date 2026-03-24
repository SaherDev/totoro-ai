"""Extraction service orchestrating the extraction pipeline."""

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from totoro_ai.api.errors import ExtractionFailedNoMatchError
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceResponse,
)
from totoro_ai.core.config import load_yaml_config
from totoro_ai.core.extraction.confidence import compute_confidence
from totoro_ai.core.extraction.dispatcher import (
    ExtractionDispatcher,
    UnsupportedInputError,
)
from totoro_ai.core.extraction.places_client import PlacesClient
from totoro_ai.db.models import Place


class ExtractionService:
    """Orchestrate place extraction pipeline (ADR-008, ADR-034)."""

    def __init__(
        self,
        dispatcher: ExtractionDispatcher,
        places_client: PlacesClient,
        db_session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Initialize service with dependencies.

        Args:
            dispatcher: ExtractionDispatcher for input routing
            places_client: PlacesClient for place validation
            db_session_factory: Factory function returning AsyncSession
        """
        self._dispatcher = dispatcher
        self._places_client = places_client
        self._db_session_factory = db_session_factory

    async def run(
        self, raw_input: str, user_id: str
    ) -> ExtractPlaceResponse:
        """Extract and save (or confirm) a place from raw input.

        Pipeline:
        1. Validate raw_input not empty
        2. Dispatch to appropriate extractor
        3. Validate place against Google Places
        4. Compute confidence
        5. Check thresholds:
           - ≤0.30 → error
           - 0.30-0.70 → return with requires_confirmation=True
           - ≥0.70 → check dedup, save, return with place_id
        6. Dedup by google_place_id if match found
        7. Write Place to database

        Args:
            raw_input: TikTok URL or plain text
            user_id: User identifier (validated by NestJS)

        Returns:
            ExtractPlaceResponse with place data and status

        Raises:
            ValueError: If raw_input is empty (→ 400)
            UnsupportedInputError: If no extractor matches (→ 422)
            ExtractionFailedNoMatchError: If confidence ≤0.30 (→ 422)
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
            corroborated=False,
        )

        # Step 5: Apply thresholds
        _thresholds = load_yaml_config("app.yaml").get("extraction", {}).get("thresholds", {})
        threshold_store = _thresholds.get("store_silently", 0.70)
        threshold_require_confirm = _thresholds.get("require_confirmation", 0.30)

        if confidence <= threshold_require_confirm:
            raise ExtractionFailedNoMatchError(
                f"Confidence too low: {confidence:.2f} ≤ {threshold_require_confirm}"
            )

        # Below store threshold but above confirm threshold
        if confidence < threshold_store:
            return ExtractPlaceResponse(
                place_id=None,
                place=extraction,
                confidence=confidence,
                requires_confirmation=True,
                source_url=result.source_url,
            )

        # Step 6: Confidence ≥ threshold_store — check deduplication
        db_session = self._db_session_factory()

        if places_match.google_place_id:
            # Query for existing place with same google_place_id
            from sqlalchemy import select

            existing = await db_session.scalar(
                select(Place).filter_by(google_place_id=places_match.google_place_id)
            )

            if existing:
                # Return existing place without writing
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
            google_place_id=places_match.google_place_id,
            confidence=confidence,
            source=result.source.value,
        )

        db_session.add(place)
        await db_session.commit()

        return ExtractPlaceResponse(
            place_id=place_id,
            place=extraction,
            confidence=confidence,
            requires_confirmation=False,
            source_url=result.source_url,
        )
