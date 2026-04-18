"""Unit tests for ChatService.run() dispatch paths."""

from unittest.mock import AsyncMock, MagicMock, patch

from totoro_ai.api.schemas.chat import ChatRequest
from totoro_ai.api.schemas.consult import (
    ConsultResponse,
    ConsultResult,
    Location,
    ReasoningStep,
)
from totoro_ai.api.schemas.extract_place import (
    ExtractPlaceItem,
    ExtractPlaceResponse,
)
from totoro_ai.api.schemas.recall import RecallResponse, RecallResult
from totoro_ai.core.chat.router import IntentClassification
from totoro_ai.core.chat.service import ChatService
from totoro_ai.core.intent.intent_parser import (
    ParsedIntent,
    ParsedIntentPlace,
    ParsedIntentSearch,
)
from totoro_ai.core.places import (
    LocationContext,
    PlaceAttributes,
    PlaceObject,
    PlaceType,
)


def _make_service(
    extraction: AsyncMock | None = None,
    consult: AsyncMock | None = None,
    recall: AsyncMock | None = None,
    assistant: AsyncMock | None = None,
    intent_parser: AsyncMock | None = None,
    event_dispatcher: AsyncMock | None = None,
    memory_service: AsyncMock | None = None,
) -> ChatService:
    """Helper to build a ChatService with all deps mocked.

    The intent_parser mock defaults to returning an empty ParsedIntent
    (place_type=None, enriched_query=None) so non-recall tests don't have
    to set up the parse() return value explicitly.
    """
    if event_dispatcher is None:
        event_dispatcher = AsyncMock()
        event_dispatcher.dispatch = AsyncMock()
    if intent_parser is None:
        intent_parser = AsyncMock()
        intent_parser.parse = AsyncMock(return_value=ParsedIntent())
    return ChatService(
        extraction_service=extraction or AsyncMock(),
        consult_service=consult or AsyncMock(),
        recall_service=recall or AsyncMock(),
        assistant_service=assistant or AsyncMock(),
        intent_parser=intent_parser,
        event_dispatcher=event_dispatcher,
        memory_service=memory_service or AsyncMock(),
    )


def _consult_response() -> ConsultResponse:
    return ConsultResponse(
        results=[
            ConsultResult(
                place=PlaceObject(
                    place_id="nara-1",
                    place_name="Nara Eatery",
                    place_type=PlaceType.food_and_drink,
                    subcategory="restaurant",
                    attributes=PlaceAttributes(cuisine="japanese"),
                    provider_id="google:ChIJnara",
                    lat=13.7563,
                    lng=100.5018,
                    address="123 Test St",
                    geo_fresh=True,
                    enriched=True,
                ),
                confidence=0.87,
                source="saved",
            ),
        ],
        reasoning_steps=[ReasoningStep(step="1", summary="Recalled from memory")],
    )


def _extract_response() -> ExtractPlaceResponse:
    return ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(
                place=PlaceObject(
                    place_id="place-1",
                    place_name="Ichiran Ramen",
                    place_type=PlaceType.food_and_drink,
                    subcategory="restaurant",
                    attributes=PlaceAttributes(cuisine="ramen"),
                    provider_id="google:ChIJxxx",
                ),
                confidence=0.9,
                status="saved",
            )
        ],
        source_url=None,
    )


def _recall_response() -> RecallResponse:
    return RecallResponse(
        results=[
            RecallResult(
                place=PlaceObject(
                    place_id="place-1",
                    place_name="Ichiran Ramen",
                    place_type=PlaceType.food_and_drink,
                    subcategory="restaurant",
                    attributes=PlaceAttributes(cuisine="ramen"),
                ),
                match_reason="semantic + keyword",
                relevance_score=0.9,
            )
        ],
        total_count=1,
        empty_state=False,
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_consult_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'consult' intent to ConsultService and pipes
    the full ConsultResponse through as `data`. Each result carries a
    full enriched PlaceObject and a source tag (ADR-058: no score)."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.return_value = _consult_response()

    service = _make_service(consult=consult_mock)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby")

    result = await service.run(request)

    assert result.type == "consult"
    assert result.data is not None
    assert "Nara Eatery" in result.message
    consult_mock.consult.assert_called_once_with("user_1", "cheap dinner nearby", None)

    # New response shape: list of ConsultResult with full PlaceObject.
    results_payload = result.data["results"]
    assert isinstance(results_payload, list)
    assert len(results_payload) >= 1
    first = results_payload[0]
    assert first["place"]["place_name"] == "Nara Eatery"
    assert first["place"]["enriched"] is True
    assert first["source"] in ("saved", "discovered")


def _place(place_id: str, name: str) -> PlaceObject:
    return PlaceObject(
        place_id=place_id,
        place_name=name,
        place_type=PlaceType.food_and_drink,
        subcategory="restaurant",
        attributes=PlaceAttributes(cuisine="ramen"),
        provider_id=f"google:ChIJ{place_id}",
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_extract_place_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'extract-place' intent to ExtractionService."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = _extract_response()

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://www.tiktok.com/video/123")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.data is not None
    extraction_mock.run.assert_called_once_with(
        "https://www.tiktok.com/video/123", "user_1"
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_extract_place_message_picks_first_saved_not_first_result(
    mock_classify: MagicMock,
) -> None:
    """Message names the saved place even when it isn't results[0]."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(place=None, confidence=0.60, status="failed"),
            ExtractPlaceItem(place=None, confidence=0.60, status="failed"),
            ExtractPlaceItem(
                place=_place("p1", "ChaTraMue"), confidence=0.75, status="saved"
            ),
            ExtractPlaceItem(place=None, confidence=0.65, status="failed"),
        ],
        source_url=None,
    )

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://tiktok.com/video/1")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.message == "Saved: ChaTraMue"


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_extract_place_message_all_duplicates(
    mock_classify: MagicMock,
) -> None:
    """When every result is a duplicate, the message does not lie about saving."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(
                place=_place("p1", "Ichiran Ramen"),
                confidence=0.92,
                status="duplicate",
            ),
            ExtractPlaceItem(
                place=_place("p2", "Nara Eatery"),
                confidence=0.88,
                status="duplicate",
            ),
        ],
        source_url=None,
    )

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://tiktok.com/video/2")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.message == "Already in your saves."


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_extract_place_message_all_failed(mock_classify: MagicMock) -> None:
    """When nothing cleared the confidence bar, the message says so."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(place=None, confidence=0.20, status="failed"),
            ExtractPlaceItem(place=None, confidence=0.25, status="failed"),
        ],
        source_url=None,
    )

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://tiktok.com/video/3")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.message == "Couldn't extract a place from that."


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_extract_place_message_only_needs_review(
    mock_classify: MagicMock,
) -> None:
    """Pure tentative save: the message surfaces the uncertainty (ADR-057)."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(
                place=_place("p1", "Thipsamai"),
                confidence=0.60,
                status="needs_review",
            ),
        ],
        source_url=None,
    )

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://tiktok.com/video/4")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.message == "Low confidence — please confirm: Thipsamai"


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_extract_place_message_mixed_saved_and_needs_review(
    mock_classify: MagicMock,
) -> None:
    """Mixed confident + tentative: the message lists both bands separately."""
    mock_classify.return_value = IntentClassification(
        intent="extract-place", confidence=0.98, clarification_needed=False
    )
    extraction_mock = AsyncMock()
    extraction_mock.run.return_value = ExtractPlaceResponse(
        results=[
            ExtractPlaceItem(
                place=_place("p1", "ChaTraMue"), confidence=0.75, status="saved"
            ),
            ExtractPlaceItem(
                place=_place("p2", "Thipsamai"),
                confidence=0.60,
                status="needs_review",
            ),
            ExtractPlaceItem(place=None, confidence=0.22, status="failed"),
        ],
        source_url=None,
    )

    service = _make_service(extraction=extraction_mock)
    request = ChatRequest(user_id="user_1", message="https://tiktok.com/video/5")

    result = await service.run(request)

    assert result.type == "extract-place"
    assert result.message == (
        "Saved: ChaTraMue Low confidence — please confirm: Thipsamai"
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_recall_meta_query_dispatches_filter_mode(
    mock_classify: MagicMock,
) -> None:
    """Meta-query "pull my restaurants" → IntentParser extracts
    place_type + subcategory, returns enriched_query=None. ChatService
    builds RecallFilters from parsed.place and passes query=None, so the
    recall service dispatches to filter-mode (ADR-057 follow-up)."""
    mock_classify.return_value = IntentClassification(
        intent="recall", confidence=0.90, clarification_needed=False
    )
    parser_mock = AsyncMock()
    parser_mock.parse = AsyncMock(
        return_value=ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
            ),
            search=ParsedIntentSearch(enriched_query=None),
        )
    )
    recall_mock = AsyncMock()
    recall_mock.run.return_value = _recall_response()

    service = _make_service(recall=recall_mock, intent_parser=parser_mock)
    request = ChatRequest(
        user_id="user_1", message="Can you pull all restaurants I saved?"
    )

    result = await service.run(request)

    assert result.type == "recall"
    parser_mock.parse.assert_awaited_once_with("Can you pull all restaurants I saved?")
    recall_mock.run.assert_awaited_once()
    call = recall_mock.run.await_args
    assert call.kwargs["query"] is None  # filter mode
    assert call.kwargs["user_id"] == "user_1"
    filters = call.kwargs["filters"]
    assert filters.place_type == "food_and_drink"
    assert filters.subcategory == "restaurant"


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_recall_place_description_keeps_enriched_query(
    mock_classify: MagicMock,
) -> None:
    """A place-description query ("cozy ramen near my office") produces
    a populated enriched_query — recall routes to hybrid mode with that
    string as the vector/FTS input."""
    mock_classify.return_value = IntentClassification(
        intent="recall", confidence=0.90, clarification_needed=False
    )
    parser_mock = AsyncMock()
    parser_mock.parse = AsyncMock(
        return_value=ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
                attributes=PlaceAttributes(cuisine="japanese", ambiance="cozy"),
            ),
            search=ParsedIntentSearch(
                enriched_query="cozy japanese ramen restaurant nearby",
            ),
        )
    )
    recall_mock = AsyncMock()
    recall_mock.run.return_value = _recall_response()

    service = _make_service(recall=recall_mock, intent_parser=parser_mock)
    request = ChatRequest(
        user_id="user_1", message="that cozy ramen place near my office"
    )

    await service.run(request)

    call = recall_mock.run.await_args
    assert call.kwargs["query"] == "cozy japanese ramen restaurant nearby"
    filters = call.kwargs["filters"]
    assert filters.cuisine == "japanese"
    assert filters.ambiance == "cozy"
    assert filters.subcategory == "restaurant"


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_recall_projects_location_context_onto_filters(
    mock_classify: MagicMock,
) -> None:
    """LocationContext on parsed.place maps directly onto RecallFilters'
    neighborhood/city/country fields."""
    mock_classify.return_value = IntentClassification(
        intent="recall", confidence=0.90, clarification_needed=False
    )
    parser_mock = AsyncMock()
    parser_mock.parse = AsyncMock(
        return_value=ParsedIntent(
            place=ParsedIntentPlace(
                place_type=PlaceType.food_and_drink,
                subcategory="restaurant",
                attributes=PlaceAttributes(
                    location_context=LocationContext(city="Bangkok", country="Thailand")
                ),
            ),
            search=ParsedIntentSearch(enriched_query=None),
        )
    )
    recall_mock = AsyncMock()
    recall_mock.run.return_value = _recall_response()

    service = _make_service(recall=recall_mock, intent_parser=parser_mock)
    request = ChatRequest(
        user_id="user_1", message="Show me everything I saved in Bangkok"
    )

    await service.run(request)

    filters = recall_mock.run.await_args.kwargs["filters"]
    assert filters.city == "Bangkok"
    assert filters.country == "Thailand"
    assert filters.neighborhood is None


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_assistant_intent(mock_classify: MagicMock) -> None:
    """ChatService routes 'assistant' intent to ChatAssistantService."""
    mock_classify.return_value = IntentClassification(
        intent="assistant", confidence=0.92, clarification_needed=False
    )
    assistant_mock = AsyncMock()
    assistant_mock.run.return_value = "Tipping is not expected in Japan."

    service = _make_service(assistant=assistant_mock)
    request = ChatRequest(user_id="user_1", message="is tipping expected in Japan?")

    result = await service.run(request)

    assert result.type == "assistant"
    assert result.message == "Tipping is not expected in Japan."
    assert result.data is None
    assistant_mock.run.assert_called_once_with(
        "is tipping expected in Japan?", "user_1"
    )


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_error_on_downstream_exception(mock_classify: MagicMock) -> None:
    """ChatService returns type='error' when downstream service raises."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.side_effect = RuntimeError("DB timeout")

    service = _make_service(consult=consult_mock)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby")

    result = await service.run(request)

    assert result.type == "error"
    assert "DB timeout" in (result.data or {}).get("detail", "")


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_error_on_classify_exception(mock_classify: MagicMock) -> None:
    """ChatService returns type='error' when classify_intent raises."""
    mock_classify.side_effect = RuntimeError("LLM timeout")

    service = _make_service()
    request = ChatRequest(user_id="user_1", message="something")

    result = await service.run(request)

    assert result.type == "error"


# Phase 4 / US2 — clarification (T014)


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_clarification_response_no_downstream_call(
    mock_classify: MagicMock,
) -> None:
    """ChatService returns clarification without calling any downstream service."""
    mock_classify.return_value = IntentClassification(
        intent="recall",
        confidence=0.48,
        clarification_needed=True,
        clarification_question=(
            "Are you looking for a saved place called Fuji or a recommendation?"
        ),
    )
    consult_mock = AsyncMock()
    recall_mock = AsyncMock()
    extraction_mock = AsyncMock()
    assistant_mock = AsyncMock()

    service = _make_service(
        extraction=extraction_mock,
        consult=consult_mock,
        recall=recall_mock,
        assistant=assistant_mock,
    )
    request = ChatRequest(user_id="user_1", message="fuji")

    result = await service.run(request)

    assert result.type == "clarification"
    assert result.data is None
    assert "Fuji" in result.message or "fuji" in result.message.lower()

    consult_mock.consult.assert_not_called()
    recall_mock.run.assert_not_called()
    extraction_mock.run.assert_not_called()
    assistant_mock.run.assert_not_called()


@patch("totoro_ai.core.chat.service.classify_intent")
async def test_run_consult_passes_location(mock_classify: MagicMock) -> None:
    """ChatService passes location to ConsultService.consult() call."""
    mock_classify.return_value = IntentClassification(
        intent="consult", confidence=0.95, clarification_needed=False
    )
    consult_mock = AsyncMock()
    consult_mock.consult.return_value = _consult_response()

    service = _make_service(consult=consult_mock)
    loc = Location(lat=13.7563, lng=100.5018)
    request = ChatRequest(user_id="user_1", message="cheap dinner nearby", location=loc)

    await service.run(request)

    consult_mock.consult.assert_called_once_with("user_1", "cheap dinner nearby", loc)
