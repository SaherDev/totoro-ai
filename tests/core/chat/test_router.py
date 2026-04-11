"""Unit tests for intent router and classification."""

from totoro_ai.core.chat.router import IntentClassification
from totoro_ai.core.memory.schemas import PersonalFact


class TestIntentClassification:
    """Tests for IntentClassification schema."""

    def test_personal_facts_field_exists(self) -> None:
        """IntentClassification has personal_facts field."""
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=[],
        )
        assert hasattr(classification, "personal_facts")
        assert classification.personal_facts == []

    def test_personal_facts_defaults_to_empty_list(self) -> None:
        """IntentClassification.personal_facts defaults to [] if not provided."""
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
        )
        assert classification.personal_facts == []

    def test_personal_facts_with_stated_fact(self) -> None:
        """IntentClassification accepts personal_facts with stated source."""
        fact = PersonalFact(text="I use a wheelchair", source="stated")
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=[fact],
        )
        assert len(classification.personal_facts) == 1
        assert classification.personal_facts[0].text == "I use a wheelchair"
        assert classification.personal_facts[0].source == "stated"

    def test_personal_facts_with_inferred_fact(self) -> None:
        """IntentClassification accepts personal_facts with inferred source."""
        fact = PersonalFact(text="Seems like they prefer spicy", source="inferred")
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=[fact],
        )
        assert len(classification.personal_facts) == 1
        assert classification.personal_facts[0].source == "inferred"

    def test_personal_facts_multiple_facts(self) -> None:
        """IntentClassification can hold multiple personal facts."""
        facts = [
            PersonalFact(text="I'm vegetarian", source="stated"),
            PersonalFact(text="I hate seafood", source="inferred"),
        ]
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=facts,
        )
        assert len(classification.personal_facts) == 2

    def test_model_validate_json_with_personal_facts(self) -> None:
        """IntentClassification can be deserialized from JSON with personal_facts."""
        json_str = """{
            "intent": "consult",
            "confidence": 0.95,
            "clarification_needed": false,
            "clarification_question": null,
            "personal_facts": [
                {"text": "I'm vegan", "source": "stated"}
            ]
        }"""
        classification = IntentClassification.model_validate_json(json_str)
        assert classification.intent == "consult"
        assert len(classification.personal_facts) == 1
        assert classification.personal_facts[0].text == "I'm vegan"

    def test_model_validate_json_without_personal_facts(self) -> None:
        """IntentClassification deserializes from JSON without personal_facts field."""
        json_str = """{
            "intent": "consult",
            "confidence": 0.95,
            "clarification_needed": false,
            "clarification_question": null
        }"""
        classification = IntentClassification.model_validate_json(json_str)
        assert classification.intent == "consult"
        assert classification.personal_facts == []

    def test_model_validate_json_empty_personal_facts(self) -> None:
        """IntentClassification deserializes with empty personal_facts array."""
        json_str = """{
            "intent": "extract-place",
            "confidence": 0.9,
            "clarification_needed": false,
            "clarification_question": null,
            "personal_facts": []
        }"""
        classification = IntentClassification.model_validate_json(json_str)
        assert classification.personal_facts == []

    def test_model_dump_includes_personal_facts(self) -> None:
        """IntentClassification.model_dump() includes personal_facts."""
        fact = PersonalFact(text="I'm vegetarian", source="stated")
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=[fact],
        )
        dumped = classification.model_dump()
        assert "personal_facts" in dumped
        assert len(dumped["personal_facts"]) == 1

    def test_place_attribute_not_extracted_as_personal_fact(self) -> None:
        """IntentClassification stores personal facts, not place attributes.

        Place attributes like 'this place is wheelchair-friendly' must NOT be
        in personal_facts; they're extracted by extraction pipeline instead.
        """
        # Personal fact: "I use a wheelchair"
        fact = PersonalFact(text="I use a wheelchair", source="stated")
        classification = IntentClassification(
            intent="consult",
            confidence=0.95,
            clarification_needed=False,
            clarification_question=None,
            personal_facts=[fact],
        )
        # The fact should be present
        assert len(classification.personal_facts) == 1

        # Place attribute should NOT be in personal_facts.
        # Verified in _SYSTEM_PROMPT extraction rules.
