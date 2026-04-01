"""Level 6 — GPT-4o-mini vision on video frames (stub, background phase).

Scene detection + bottom-third crop for text overlay extraction.
"""

import logging

from totoro_ai.core.extraction.models import ExtractionContext

logger = logging.getLogger(__name__)


class VisionFramesEnricher:
    """Extract place names from video frames via GPT-4o-mini vision.

    Background phase enricher.
    Stub implementation — video frame extraction not yet available.
    """

    async def enrich(self, context: ExtractionContext) -> None:
        if not context.url:
            return

        # TODO: Implement video frame extraction + GPT-4o-mini vision
        # Get CDN URL, stream to ffmpeg, scene detection, crop bottom third
        # Send 3-5 frames to GPT-4o-mini vision
        # Hard timeout: 10 seconds
        # Append CandidatePlace(source=VISION_FRAMES)
        logger.debug("VisionFramesEnricher: stub, skipping")
