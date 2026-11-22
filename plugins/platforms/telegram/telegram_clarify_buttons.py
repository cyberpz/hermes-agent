"""Clarify keyboards for Telegram, with opt-in labelled buttons (#148236).

A clarify prompt normally renders one numeric button per choice and keeps the full option text in
the message body, because a phone truncates long button labels. That is right for a question with
prose answers, and useless for a menu: a section navigator whose buttons read "1", "2", "3" tells
the user nothing, and the forced "✏️ Other (type answer)" row is noise when the choices are the
whole answer space.

``clarify_label_buttons: true`` renders each button with its own choice text instead. It stays
opt-in and default-off: with the flag absent the keyboard is byte-identical to today's, so nothing
downstream — tests, transcripts, other platforms — sees a different wire payload.
"""
from __future__ import annotations

from typing import Any, Sequence

#: Telegram renders 1-64 characters of button text; anything longer is silently clipped, and a
#: clipped label changes what the option says. Longer labels therefore keep the numbered keyboard.
MAX_BUTTON_LABEL = 64

#: One screen of buttons. Beyond this the labelled menu no longer fits the "pick a card" shape the
#: flag exists for, so the numbered keyboard (which paginates the choice list in the body) wins.
MAX_LABELLED_CHOICES = 8


def clarify_rows(
    choices: Sequence[Any], clarify_id: str, *, other_label: str, label_buttons: bool = False,
    other_row: bool = True,
) -> list[list[Any]]:
    """Keyboard rows for a clarify prompt.

    ``callback_data`` always carries the choice *index* (``cl:<id>:<idx>``), never the label, so
    the tap resolves exactly as before: only what the user reads changes. Each labelled choice gets
    its own row, as the numeric keyboard does — Telegram sizes a row to its widest button, so
    packing several labels on one row would shrink all of them.

    ``InlineKeyboardButton`` is imported here, not at module scope: python-telegram-bot is an
    on-demand install, and a top-level import would make this module (and with it the whole adapter)
    fail to load before the SDK is present.
    """
    from telegram import InlineKeyboardButton

    labels = [str(choice).strip() for choice in choices]
    if label_buttons and labels and len(labels) <= MAX_LABELLED_CHOICES and all(
            label and len(label) <= MAX_BUTTON_LABEL for label in labels):
        rows = [[InlineKeyboardButton(label, callback_data=f"cl:{clarify_id}:{index}")]
                for index, label in enumerate(labels)]
    else:
        rows = [[InlineKeyboardButton(str(index + 1), callback_data=f"cl:{clarify_id}:{index}")]
                for index in range(len(labels))]
    if other_row:
        rows.append([InlineKeyboardButton(other_label, callback_data=f"cl:{clarify_id}:other")])
    return rows
