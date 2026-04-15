"""Tests for LLMNEREnricher.

Post ADR-054 the LLM emits a `_NERPlace` that mirrors `PlaceCreate`
field-for-field (minus user_id/provider/external_id). The enricher
stamps on `user_id` from context and wraps the result in a
`CandidatePlace` with extraction metadata.
"""

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
from totoro_ai.core.places import (
    LocationContext,
    PlaceAttributes,
    PlaceCreate,
    PlaceType,
)
from totoro_ai.providers.llm import InstructorClient


def _ner_place(
    place_name: str,
    place_type: PlaceType = PlaceType.food_and_drink,
    subcategory: str | None = "restaurant",
    cuisine: str | None = None,
    price_hint: str | None = None,
    city: str | None = None,
    signals: list[str] | None = None,
) -> _NERPlace:
    attributes = PlaceAttributes(
        cuisine=cuisine,
        price_hint=price_hint,
        location_context=LocationContext(city=city) if city else None,
    )
    return _NERPlace(
        place_name=place_name,
        place_type=place_type,
        subcategory=subcategory,
        attributes=attributes,
        signals=signals or [],
    )


def _mock_instructor(places: list[_NERPlace]) -> InstructorClient:  # type: ignore[type-arg]
    client = MagicMock(spec=InstructorClient)
    response = _NERResponse(places=places)
    client.extract = AsyncMock(return_value=response)
    return client


@pytest.fixture
def enricher_two_places() -> LLMNEREnricher:
    client = _mock_instructor(
        [
            _ner_place(
                "Fuji Ramen",
                cuisine="japanese",
                price_hint="moderate",
                city="Bangkok",
            ),
            _ner_place(
                "Som Tam Nua",
                cuisine="thai",
                price_hint="cheap",
                city="Bangkok",
            ),
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
        names = {c.place.place_name for c in ctx.candidates}
        assert "Fuji Ramen" in names
        assert "Som Tam Nua" in names

    async def test_candidates_carry_user_id_from_context(
        self, enricher_two_places: LLMNEREnricher
    ) -> None:
        ctx = ExtractionContext(url=None, user_id="user-42", caption="text")
        await enricher_two_places.enrich(ctx)
        assert all(c.place.user_id == "user-42" for c in ctx.candidates)

    async def test_no_skip_guard_appends_to_existing_candidates(
        self, enricher_two_places: LLMNEREnricher
    ) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        ctx.candidates.append(
            CandidatePlace(
                place=PlaceCreate(
                    user_id="u1",
                    place_name="Existing",
                    place_type=PlaceType.food_and_drink,
                ),
                source=ExtractionLevel.EMOJI_REGEX,
            )
        )
        await enricher_two_places.enrich(ctx)
        assert len(ctx.candidates) == 3  # 1 existing + 2 from LLM

    async def test_case1_skips_when_no_text(self) -> None:
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1")
        await enricher.enrich(ctx)
        client.extract.assert_not_called()
        assert ctx.candidates == []

    async def test_case1_skips_when_empty_supplementary_text(self) -> None:
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", supplementary_text="")
        await enricher.enrich(ctx)
        client.extract.assert_not_called()

    async def test_case2_uses_supplementary_text_when_no_caption(self) -> None:
        client = _mock_instructor([_ner_place("Fuji Ramen")])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(
            url=None, user_id="u1", supplementary_text="Fuji Ramen is great"
        )
        await enricher.enrich(ctx)
        client.extract.assert_called_once()
        assert len(ctx.candidates) == 1

    async def test_case2_supplementary_text_platform_defaults_to_unknown(self) -> None:
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", supplementary_text="Nobu Tokyo")
        await enricher.enrich(ctx)
        call_args = client.extract.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "platform: unknown" in user_msg["content"]

    async def test_case3_full_metadata_passed_to_llm(self) -> None:
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

    async def test_attributes_propagate_to_candidate_place_create(self) -> None:
        """The NER's `attributes` block is forwarded to the wrapped
        PlaceCreate verbatim — no per-field mapping happens."""
        client = _mock_instructor(
            [
                _ner_place(
                    "Le Bernardin",
                    cuisine="french",
                    price_hint="expensive",
                    city="New York",
                    subcategory="restaurant",
                )
            ]
        )
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="Le Bernardin dinner")
        await enricher.enrich(ctx)
        assert len(ctx.candidates) == 1
        candidate = ctx.candidates[0]
        assert candidate.place.place_name == "Le Bernardin"
        assert candidate.place.place_type == PlaceType.food_and_drink
        assert candidate.place.subcategory == "restaurant"
        assert candidate.place.attributes.cuisine == "french"
        assert candidate.place.attributes.price_hint == "expensive"
        assert candidate.place.attributes.location_context is not None
        assert candidate.place.attributes.location_context.city == "New York"

    async def test_adr_044_system_prompt_defensive_instruction(self) -> None:
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

    async def test_signals_propagate_to_candidate(self) -> None:
        client = _mock_instructor(
            [_ner_place("Sushi Bar", signals=["emoji_marker", "caption"])]
        )
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        await enricher.enrich(ctx)
        assert ctx.candidates[0].signals == ["emoji_marker", "caption"]

    async def test_empty_places_list_no_candidates(self) -> None:
        client = _mock_instructor([])
        enricher = LLMNEREnricher(instructor_client=client)
        ctx = ExtractionContext(url=None, user_id="u1", caption="some text")
        await enricher.enrich(ctx)
        assert ctx.candidates == []

    async def test_returns_none(self, enricher_two_places: LLMNEREnricher) -> None:
        ctx = ExtractionContext(url=None, user_id="u1", caption="text")
        result = await enricher_two_places.enrich(ctx)
        assert result is None
