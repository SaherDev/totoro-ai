"""Tests for LLMNEREnricher."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from totoro_ai.core.extraction.enrichers.llm_ner import (
    LLMNEREnricher,
    _NERPlace,
    _NERResponse,
)
from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
)
from totoro_ai.providers.llm import InstructorClient


def _mock_instructor(places: list[dict]) -> InstructorClient:  # type: ignore[type-arg]
    """Build a mock InstructorClient returning the given places."""
    client = MagicMock(spec=InstructorClient)
    response = _NERResponse(places=[_NERPlace(**p) for p in places])
    client.extract = AsyncMock(return_value=response)
    return client


@pytest.fixture
def enricher_two_places() -> LLMNEREnricher:
    client = _mock_instructor(
        [
            {
                "name": "Fuji Ramen",
                "city": "Bangkok",
                "cuisine": "ramen",
                "price_range": "mid",
                "place_type": "restaurant",
            },
            {
                "name": "Som Tam Nua",
                "city": "Bangkok",
                "cuisine": "thai",
                "price_range": "low",
                "place_type": "restaurant",
            },
        ]
    )
    return LLMNEREnricher(instructor_client=client)


class TestLLMNEREnricher:
    async def test_populates_candidates_from_llm_response(
        self, enricher_two_places: LLMNEREnricher
    ) -> None:
        ctx = ExtractionContext(
            url=None, user_id="u1", caption="Ate at Fuji Ramen and Som Tam Nua"
        )
        await enricher_two_places.enrich(ctx)
        assert len(ctx.candidates) == 2
        names = {c.name for c in ctx.candidates}
        assert "Fuji Ramen" in names
        assert "Som Tam Nua" in names

    async def test_no_skip_guard_appends_to_existing_candidates(
        self, enricher_two_places: LLMNEREnricher
    ) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        ctx.candidates.append(
            CandidatePlace(
                name="Existing",
                city=None,
                cuisine=None,
                source=ExtractionLevel.EMOJI_REGEX,
            )
        )
        await enricher_two_places.enrich(ctx)
        assert len(ctx.candidates) == 3  # 1 existing + 2 from LLM

    async def test_case1_skips_when_no_text(self) -> None:
        """Case 1: no caption and no supplementary_text → enricher skips."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1")
        await enricher.enrich(ctx)
        client.extract.assert_not_called()
        assert ctx.candidates == []

    async def test_case1_skips_when_empty_supplementary_text(self) -> None:
        """Case 1: empty string supplementary_text is treated as no text."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", supplementary_text="")
        await enricher.enrich(ctx)
        client.extract.assert_not_called()

    async def test_case2_uses_supplementary_text_when_no_caption(self) -> None:
        """Case 2: supplementary_text only → LLM called, candidates populated."""
        client = _mock_instructor(
            [
                {
                    "name": "Fuji Ramen",
                    "city": None,
                    "cuisine": None,
                    "price_range": None,
                    "place_type": None,
                }
            ]
        )
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(
            url=None, user_id="u1", supplementary_text="Fuji Ramen is great"
        )
        await enricher.enrich(ctx)
        client.extract.assert_called_once()
        assert len(ctx.candidates) == 1

    async def test_case2_supplementary_text_platform_defaults_to_unknown(self) -> None:
        """Case 2: no platform set → user message contains 'platform: unknown'."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(
            url=None, user_id="u1", supplementary_text="Nobu Tokyo"
        )
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "platform: unknown" in user_msg["content"]

    async def test_case3_full_metadata_passed_to_llm(self) -> None:
        """Case 3: all 5 metadata fields appear in the user message."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(
            url="https://tiktok.com/v/123",
            user_id="u1",
            caption="Dinner at Le Bernardin",
            platform="tiktok",
            title="Best restaurant in NYC",
            hashtags=["nyc", "finedining"],
            location_tag="New York",
        )
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        content = user_msg["content"]
        assert "platform: tiktok" in content
        assert "title: Best restaurant in NYC" in content
        assert "caption: Dinner at Le Bernardin" in content
        assert "nyc" in content
        assert "location_tag: New York" in content

    async def test_structured_fields_on_candidate(self) -> None:
        """price_range and place_type from LLM response are set on candidates."""
        client = _mock_instructor(
            [
                {
                    "name": "Le Bernardin",
                    "city": "New York",
                    "cuisine": "french",
                    "price_range": "high",
                    "place_type": "restaurant",
                }
            ]
        )
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="Le Bernardin dinner")
        await enricher.enrich(ctx)
        assert len(ctx.candidates) == 1
        candidate = ctx.candidates[0]
        assert candidate.price_range == "high"
        assert candidate.place_type == "restaurant"

    async def test_adr_044_system_prompt_defensive_instruction(self) -> None:
        """System prompt must contain defensive instruction (ADR-044)."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        content_lower = system_msg["content"].lower()
        assert "ignore" in content_lower
        assert "metadata" in content_lower

    async def test_adr_044_metadata_xml_tags_in_user_message(self) -> None:
        """Caption must be wrapped in <metadata> tags in user message (ADR-044)."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "<metadata>" in user_msg["content"]
        assert "</metadata>" in user_msg["content"]

    async def test_source_set_to_llm_ner(
        self, enricher_two_places: LLMNEREnricher
    ) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        await enricher_two_places.enrich(ctx)
        assert all(c.source == ExtractionLevel.LLM_NER for c in ctx.candidates)

    async def test_empty_places_list_no_candidates(self) -> None:
        """LLM returns empty places list → candidates unchanged."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        assert ctx.candidates == []

    async def test_returns_none(self, enricher_two_places: LLMNEREnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        result = await enricher_two_places.enrich(ctx)
        assert result is None
