"""fallback_node emission tests (feature 027 M3, FR-027)."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from totoro_ai.core.agent.graph import fallback_node
from totoro_ai.core.agent.reasoning import ReasoningStep
from totoro_ai.core.config import get_config


def _base_state(**overrides: object) -> dict:
    state = {
        "messages": [],
        "taste_profile_summary": "",
        "memory_summary": "",
        "user_id": "u1",
        "location": None,
        "last_recall_results": None,
        "reasoning_steps": [],
        "steps_taken": 0,
        "error_count": 0,
    }
    state.update(overrides)  # type: ignore[arg-type]
    return state


def test_fallback_node_composes_graceful_ai_message() -> None:
    cfg = get_config().agent
    update = fallback_node(_base_state(steps_taken=cfg.max_steps))
    assert "messages" in update
    msgs = update["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert "something went wrong" in msgs[0].content.lower()


def test_fallback_node_appends_exactly_one_user_visible_step_on_max_steps() -> None:
    cfg = get_config().agent
    update = fallback_node(_base_state(steps_taken=cfg.max_steps))
    steps = update["reasoning_steps"]
    assert len(steps) == 1
    step = steps[0]
    assert isinstance(step, ReasoningStep)
    assert step.step == "fallback"
    assert step.source == "fallback"
    assert step.tool_name is None
    assert step.visibility == "user"
    assert str(cfg.max_steps) in step.summary


def test_fallback_node_appends_user_visible_step_on_max_errors() -> None:
    cfg = get_config().agent
    update = fallback_node(_base_state(error_count=cfg.max_errors))
    steps = update["reasoning_steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step.step == "fallback"
    assert step.source == "fallback"
    assert step.visibility == "user"
    assert "errors" in step.summary.lower()


def test_fallback_node_preserves_existing_reasoning_steps() -> None:
    cfg = get_config().agent
    existing = [
        ReasoningStep(
            step="agent.tool_decision",
            summary="starting",
            source="agent",
            visibility="user",
        ),
    ]
    update = fallback_node(
        _base_state(steps_taken=cfg.max_steps, reasoning_steps=existing)
    )
    steps = update["reasoning_steps"]
    assert len(steps) == 2
    assert steps[0].step == "agent.tool_decision"
    assert steps[1].step == "fallback"


def test_fallback_node_no_debug_diagnostics_in_m3() -> None:
    """M3 defers max_steps_detail / max_errors_detail to M9."""
    cfg = get_config().agent
    update = fallback_node(_base_state(steps_taken=cfg.max_steps))
    steps = update["reasoning_steps"]
    step_names = {s.step for s in steps}
    assert "max_steps_detail" not in step_names
    assert "max_errors_detail" not in step_names
    # Only the user-visible 'fallback' step at this milestone.
    assert step_names == {"fallback"}
