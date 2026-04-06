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


def _mock_instructor(places: list[dict[str, str | None]]) -> InstructorClient:
    """Build a mock InstructorClient returning the given places."""
    client = MagicMock(spec=InstructorClient)
    response = _NERResponse(places=[_NERPlace(**p) for p in places])
    client.extract = AsyncMock(return_value=response)
    return client


@pytest.fixture
def enricher_two_places() -> LLMNEREnricher:
    client = _mock_instructor([
        {"name": "Fuji Ramen", "city": "Bangkok", "cuisine": "ramen"},
        {"name": "Som Tam Nua", "city": "Bangkok", "cuisine": "thai"},
    ])
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
                name="Existing", city=None, cuisine=None, source=ExtractionLevel.EMOJI_REGEX
            )
        )
        await enricher_two_places.enrich(ctx)
        assert len(ctx.candidates) == 3  # 1 existing + 2 from LLM

    async def test_skips_when_no_text(self) -> None:
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1")
        await enricher.enrich(ctx)
        client.extract.assert_not_called()
        assert ctx.candidates == []

    async def test_uses_supplementary_text_when_no_caption(self) -> None:
        client = _mock_instructor([{"name": "Fuji Ramen", "city": None, "cuisine": None}])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(
            url=None, user_id="u1", supplementary_text="Fuji Ramen is great"
        )
        await enricher.enrich(ctx)
        client.extract.assert_called_once()
        assert len(ctx.candidates) == 1

    async def test_adr_044_system_prompt_defensive_instruction(self) -> None:
        """System prompt must contain a defensive instruction (ADR-044)."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        content_lower = system_msg["content"].lower()
        assert "instruction" in content_lower or "ignore" in content_lower

    async def test_adr_044_context_xml_tags_in_user_message(self) -> None:
        """Caption must be wrapped in <context> tags in user message (ADR-044)."""
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "<context>" in user_msg["content"]
        assert "</context>" in user_msg["content"]

    async def test_source_set_to_llm_ner(self, enricher_two_places: LLMNEREnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        await enricher_two_places.enrich(ctx)
        assert all(c.source == ExtractionLevel.LLM_NER for c in ctx.candidates)

    async def test_returns_none(self, enricher_two_places: LLMNEREnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        result = await enricher_two_places.enrich(ctx)
        assert result is None
