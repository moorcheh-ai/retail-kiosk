from __future__ import annotations

import pytest

from retail_kiosk.intent import (
    ClassificationMethod,
    IntentKind,
    IntentConfig,
    canned_response,
    classify_intent,
    normalize_text,
)


@pytest.fixture
def cfg() -> IntentConfig:
    return IntentConfig(store_name="The Brew Corner")


class TestNormalizeText:
    def test_expands_contractions(self) -> None:
        assert "what is" in normalize_text("What's the price?")

    def test_strips_punctuation(self) -> None:
        assert normalize_text("  Hello!!!  ") == "hello"


class TestGreetings:
    def test_plain_hello(self, cfg: IntentConfig) -> None:
        result = classify_intent("Hello", cfg)
        assert result.kind == IntentKind.GREETING
        assert result.method == ClassificationMethod.RULE

    def test_good_morning(self, cfg: IntentConfig) -> None:
        result = classify_intent("Good morning", cfg)
        assert result.kind == IntentKind.GREETING

    def test_greeting_with_question_is_question(self, cfg: IntentConfig) -> None:
        result = classify_intent("Hi, do you have oat milk?", cfg)
        assert result.kind == IntentKind.QUESTION
        assert result.method == ClassificationMethod.QUESTION_OVERRIDE

    def test_hey_how_are_you_is_chitchat(self, cfg: IntentConfig) -> None:
        result = classify_intent("hey, how are you", cfg)
        assert result.kind == IntentKind.CHITCHAT
        assert result.method == ClassificationMethod.RULE

    def test_hi_how_are_you_is_chitchat(self, cfg: IntentConfig) -> None:
        assert classify_intent("Hi how are you?", cfg).kind == IntentKind.CHITCHAT


class TestSocialIntents:
    def test_thanks(self, cfg: IntentConfig) -> None:
        assert classify_intent("Thank you!", cfg).kind == IntentKind.THANKS

    def test_farewell(self, cfg: IntentConfig) -> None:
        assert classify_intent("Goodbye", cfg).kind == IntentKind.FAREWELL

    def test_help(self, cfg: IntentConfig) -> None:
        assert classify_intent("What can you help with?", cfg).kind == IntentKind.HELP

    def test_chitchat(self, cfg: IntentConfig) -> None:
        assert classify_intent("How are you?", cfg).kind == IntentKind.CHITCHAT

    def test_acknowledgment(self, cfg: IntentConfig) -> None:
        assert classify_intent("Okay, got it", cfg).kind == IntentKind.ACKNOWLEDGMENT


class TestQuestions:
    def test_price_question(self, cfg: IntentConfig) -> None:
        result = classify_intent("How much is a latte?", cfg)
        assert result.kind == IntentKind.QUESTION

    def test_hours_question(self, cfg: IntentConfig) -> None:
        result = classify_intent("What are your hours?", cfg)
        assert result.kind == IntentKind.QUESTION

    def test_long_catalog_question(self, cfg: IntentConfig) -> None:
        text = (
            "I am looking for a decaf cappuccino with oat milk and maybe a croissant "
            "if you have any gluten free options near the bakery section"
        )
        result = classify_intent(text, cfg)
        assert result.kind == IntentKind.QUESTION

    def test_do_you_have(self, cfg: IntentConfig) -> None:
        result = classify_intent("Do you have almond milk?", cfg)
        assert result.kind == IntentKind.QUESTION


class TestCannedResponses:
    def test_greeting_includes_store_name(self, cfg: IntentConfig) -> None:
        reply = canned_response(IntentKind.GREETING, cfg)
        assert "The Brew Corner" in reply

    def test_all_social_kinds_have_templates(self, cfg: IntentConfig) -> None:
        for kind in (
            IntentKind.GREETING,
            IntentKind.THANKS,
            IntentKind.FAREWELL,
            IntentKind.HELP,
            IntentKind.CHITCHAT,
            IntentKind.ACKNOWLEDGMENT,
        ):
            assert canned_response(kind, cfg)


class TestIntentConfigFromVoice:
    def test_empty_custom_uses_default_template(self) -> None:
        from retail_kiosk.intent import intent_config_from_voice_settings
        from retail_kiosk.models import KioskVoiceSettings

        voice = KioskVoiceSettings(store_name="Demo Shop", greeting_reply="")
        config = intent_config_from_voice_settings(voice)
        reply = canned_response(IntentKind.GREETING, config)
        assert "Demo Shop" in reply
