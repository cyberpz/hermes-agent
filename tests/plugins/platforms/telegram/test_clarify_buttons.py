"""Opt-in labelled clarify buttons on Telegram (#148236).

A clarify prompt normally shows one numeric button per choice with the full option text in the body,
which is right for prose answers and useless for a menu: a section navigator whose buttons read
"1", "2", "3" tells the user nothing, and the forced "Other" row is noise when the choices are the
whole answer space.

Pinned here: ``callback_data`` always carries the choice *index* (never the label), the flag is
default-off and byte-identical to today when absent, and a label Telegram would clip falls back to
the numbered keyboard rather than showing a truncated option.
"""
from __future__ import annotations

import pytest
from telegram import InlineKeyboardButton

from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult
from plugins.platforms.telegram.adapter import TelegramAdapter
from plugins.platforms.telegram.telegram_clarify_buttons import (
    MAX_BUTTON_LABEL, MAX_LABELLED_CHOICES, clarify_rows)

OTHER = "✏️ Other (type answer)"


def _labels(rows) -> list[list[str]]:
    return [[button.text for button in row] for row in rows]


def _data(rows) -> list[list[str]]:
    return [[button.callback_data for button in row] for row in rows]


def test_default_keyboard_is_unchanged():
    """No flag: numeric labels plus the Other row, exactly as before the feature existed."""
    rows = clarify_rows(["Volga", "How I work"], "cid", other_label=OTHER)

    assert _labels(rows) == [["1"], ["2"], [OTHER]]
    assert _data(rows) == [["cl:cid:0"], ["cl:cid:1"], ["cl:cid:other"]]


def test_labelled_buttons_use_the_choice_text_but_send_the_index():
    rows = clarify_rows(["📖 Volga", "🏠 How I work"], "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows) == [["📖 Volga"], ["🏠 How I work"], [OTHER]]
    assert _data(rows) == [["cl:cid:0"], ["cl:cid:1"], ["cl:cid:other"]], "the tap must resolve by index"


def test_other_row_can_be_dropped():
    rows = clarify_rows(["Yes", "No"], "cid", other_label=OTHER, label_buttons=True, other_row=False)

    assert _labels(rows) == [["Yes"], ["No"]]


def test_other_row_is_independent_of_labelling():
    rows = clarify_rows(["Yes"], "cid", other_label=OTHER, other_row=False)

    assert _labels(rows) == [["1"]]


def test_a_label_telegram_would_clip_falls_back_to_numbers():
    """A truncated label silently changes what the option says — worse than a number."""
    long_choice = "x" * (MAX_BUTTON_LABEL + 1)
    rows = clarify_rows(["short", long_choice], "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows) == [["1"], ["2"], [OTHER]]


def test_a_label_at_the_limit_is_accepted():
    rows = clarify_rows(["x" * MAX_BUTTON_LABEL], "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows) == [["x" * MAX_BUTTON_LABEL], [OTHER]]


@pytest.mark.parametrize("bad", ["", "   "])
def test_an_empty_label_falls_back_to_numbers(bad):
    rows = clarify_rows([bad, "ok"], "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows) == [["1"], ["2"], [OTHER]]


def test_too_many_choices_fall_back_to_numbers():
    choices = [f"card {i}" for i in range(MAX_LABELLED_CHOICES + 1)]
    rows = clarify_rows(choices, "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows)[0] == ["1"]


def test_no_choices_yields_only_the_other_row():
    rows = clarify_rows([], "cid", other_label=OTHER, label_buttons=True)

    assert _labels(rows) == [[OTHER]]


def test_buttons_are_real_inline_buttons():
    rows = clarify_rows(["a"], "cid", other_label=OTHER, label_buttons=True)

    assert all(isinstance(button, InlineKeyboardButton) for row in rows for button in row)


def _adapter(extra: dict) -> TelegramAdapter:
    return TelegramAdapter(PlatformConfig(enabled=True, token="t", extra=extra))


async def _capture_keyboard(adapter: TelegramAdapter, monkeypatch) -> list[list[str]]:
    """Run send_clarify's build() against a stubbed transport and return the rendered labels."""
    captured = {}

    async def _send_prompt(name, chat_id, metadata, build, **kwargs):
        _text, keyboard, _after = build()
        captured["labels"] = _labels(keyboard.inline_keyboard)
        return SendResult(success=True, message_id="1")

    monkeypatch.setattr(adapter, "_send_prompt", _send_prompt)
    await adapter.send_clarify("42", "Which section?", ["📖 Volga", "🏠 How I work"], "cid", "sess")
    return captured["labels"]


@pytest.mark.asyncio
async def test_adapter_keeps_numbers_without_the_flag(monkeypatch):
    labels = await _capture_keyboard(_adapter({}), monkeypatch)

    assert labels == [["1"], ["2"], ["✏️ Other (type answer)"]]


@pytest.mark.asyncio
async def test_adapter_renders_labels_when_opted_in(monkeypatch):
    labels = await _capture_keyboard(_adapter({"clarify_label_buttons": True, "clarify_other_row": False}),
                                     monkeypatch)

    assert labels == [["📖 Volga"], ["🏠 How I work"]]
