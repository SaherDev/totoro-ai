"""Tests for new cascade types in types.py."""

from totoro_ai.core.extraction.types import (
    CandidatePlace,
    ExtractionContext,
    ExtractionLevel,
    ExtractionPending,
    ExtractionResult,
    ProvisionalResponse,
)


class TestExtractionLevel:
    def test_enum_values(self) -> None:
        assert ExtractionLevel.EMOJI_REGEX.value == "emoji_regex"
        assert ExtractionLevel.LLM_NER.value == "llm_ner"
        assert ExtractionLevel.SUBTITLE_CHECK.value == "subtitle_check"
        assert ExtractionLevel.WHISPER_AUDIO.value == "whisper_audio"
        assert ExtractionLevel.VISION_FRAMES.value == "vision_frames"

    def test_enum_has_five_members(self) -> None:
        assert len(ExtractionLevel) == 5


class TestCandidatePlace:
    def test_instantiation(self) -> None:
        c = CandidatePlace(
            name="Fuji Ramen",
            city="Bangkok",
            cuisine="ramen",
            source=ExtractionLevel.EMOJI_REGEX,
        )
        assert c.name == "Fuji Ramen"
        assert c.city == "Bangkok"
        assert c.cuisine == "ramen"
        assert c.source == ExtractionLevel.EMOJI_REGEX
        assert c.corroborated is False

    def test_corroborated_default_false(self) -> None:
        c = CandidatePlace(
            name="X", city=None, cuisine=None, source=ExtractionLevel.LLM_NER
        )
        assert c.corroborated is False

    def test_corroborated_can_be_set(self) -> None:
        c = CandidatePlace(
            name="X",
            city=None,
            cuisine=None,
            source=ExtractionLevel.LLM_NER,
            corroborated=True,
        )
        assert c.corroborated is True


class TestExtractionContext:
    def test_instantiation_url(self) -> None:
        ctx = ExtractionContext(url="https://tiktok.com/v/123", user_id="u1")
        assert ctx.url == "https://tiktok.com/v/123"
        assert ctx.user_id == "u1"
        assert ctx.supplementary_text == ""
        assert ctx.caption is None
        assert ctx.transcript is None
        assert ctx.candidates == []
        assert ctx.pending_levels == []

    def test_instantiation_plain_text(self) -> None:
        ctx = ExtractionContext(
            url=None, user_id="u2", supplementary_text="ramen in Tokyo"
        )
        assert ctx.url is None
        assert ctx.supplementary_text == "ramen in Tokyo"

    def test_candidates_are_independent_instances(self) -> None:
        ctx1 = ExtractionContext(url=None, user_id="u1")
        ctx2 = ExtractionContext(url=None, user_id="u2")
        ctx1.candidates.append(
            CandidatePlace(
                name="A", city=None, cuisine=None, source=ExtractionLevel.LLM_NER
            )
        )
        assert ctx2.candidates == []


class TestExtractionResult:
    def test_instantiation(self) -> None:
        r = ExtractionResult(
            place_name="Fuji Ramen",
            address="123 Sukhumvit, Bangkok",
            city="Bangkok",
            cuisine="ramen",
            confidence=0.95,
            resolved_by=ExtractionLevel.EMOJI_REGEX,
            corroborated=False,
            external_provider="google",
            external_id="ChIJ123",
        )
        assert r.confidence == 0.95
        assert r.resolved_by == ExtractionLevel.EMOJI_REGEX


class TestProvisionalResponse:
    def test_instantiation(self) -> None:
        p = ProvisionalResponse(
            extraction_status="processing",
            confidence=0.0,
            message="Still working on it.",
        )
        assert p.extraction_status == "processing"
        assert p.pending_levels == []


class TestExtractionPending:
    def test_instantiation(self) -> None:
        ctx = ExtractionContext(url="https://tiktok.com/v/1", user_id="u1")
        event = ExtractionPending(
            user_id="u1",
            url="https://tiktok.com/v/1",
            pending_levels=[
                ExtractionLevel.WHISPER_AUDIO,
                ExtractionLevel.VISION_FRAMES,
            ],
            context=ctx,
        )
        assert event.user_id == "u1"
        assert len(event.pending_levels) == 2
