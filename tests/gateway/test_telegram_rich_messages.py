"""Tests for Bot API 10.1 Rich Messages (sendRichMessage) on Telegram.

Final / new-message replies opportunistically use ``sendRichMessage`` with the
RAW agent markdown so tables, task lists, etc. render natively. The legacy
MarkdownV2 ``send_message`` path stays as the fallback for unsupported /
oversized content and for transports that lack the endpoint.

The ``telegram`` package is mocked by ``tests/gateway/conftest.py``
(:func:`_ensure_telegram_mock`), so these tests construct a real
``TelegramAdapter`` and wire a mock bot.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult
from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from plugins.platforms.telegram.adapter import TelegramAdapter
from telegram.error import BadRequest, NetworkError, TimedOut


# Content exercising rich-only constructs: a heading, a real Markdown table,
# and a task list. Pipes / brackets must survive untouched into the payload.
RICH_CONTENT = "## Results\n\n| Case | Status |\n|---|---|\n| rich | ✅ |\n\n- [x] table renders"
CJK_RICH_CONTENT = "## 持仓\n\n| 项目 | 状态 |\n|---|---|\n| 早盘 | 正常 |"
ASTRAL_CJK_RICH_CONTENT = "## Rare Han\n\n| glyph | status |\n|---|---|\n| \U00030000 | ok |"
TABLE_ONLY_CONTENT = (
    "| Team | W | L | GB |\n"
    "|---|---|---|---|\n"
    "| Red Sox | 36 | 34 | 6.0 |\n"
    "| Dodgers | 40 | 30 | 2.0 |"
)
DANGEROUS_DETAILS_MATH = (
    "<details><summary>Complex proof</summary>\n\n"
    "$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$\n\n"
    "And inline \\(\\alpha + \\beta\\)\n"
    "</details>"
)

# PTB 22.6's real unknown-endpoint errors: do_api_request can raise
# EndPointNotFound for Bot API 404s, and the request layer can wrap that same
# missing endpoint as InvalidToken. Use class names here so the tests don't
# depend on optional PTB internals.
EndPointNotFound = type("EndPointNotFound", (Exception,), {})
InvalidToken = type("InvalidToken", (Exception,), {})
PTB_ENDPOINT_NOT_FOUND = EndPointNotFound(
    "Endpoint 'sendRichMessage' not found in Bot API"
)
PTB_INVALID_TOKEN_404 = InvalidToken(
    "Either the bot token was rejected by Telegram or the endpoint "
    "'sendRichMessage' does not exist."
)


def _make_adapter(extra=None):
    """Build a TelegramAdapter with a mock bot wired for the rich path."""
    config = PlatformConfig(
        enabled=True,
        token="fake-token",
        extra={"rich_messages": True, **(extra or {})},
    )
    adapter = TelegramAdapter(config)
    bot = MagicMock()
    # do_api_request as an AsyncMock makes inspect.iscoroutinefunction(...) True,
    # so _bot_supports_rich() is satisfied (real Bot.do_api_request is async too).
    bot.do_api_request = AsyncMock(return_value=SimpleNamespace(message_id=123))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_chat_action = AsyncMock()  # keeps the post-send typing re-trigger quiet
    bot.send_message_draft = AsyncMock(return_value=True)  # legacy draft fallback
    bot.edit_message_text = AsyncMock(return_value=MagicMock(message_id=1))  # legacy edit path
    bot.delete_message = AsyncMock(return_value=True)
    adapter._bot = bot
    return adapter


def _rich_api_kwargs(adapter):
    """Return the api_kwargs dict from the single sendRichMessage call."""
    call = adapter._bot.do_api_request.call_args
    assert call.args[0] == "sendRichMessage"
    return call.kwargs["api_kwargs"]


# ── Rich result shape extraction ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected_id"),
    [
        (SimpleNamespace(message_id=123), "123"),
        ({"message_id": 123}, "123"),
        ({"result": {"message_id": 123}}, "123"),
        ({"result": None}, None),
    ],
)
async def test_rich_result_shapes_extract_message_id(raw, expected_id):
    """The raw Bot API path may return either a PTB object or a raw dict."""
    adapter = _make_adapter()
    adapter._bot.do_api_request = AsyncMock(return_value=raw)

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    assert result.message_id == expected_id
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_awaited_once()
    bot.send_message.assert_not_called()


# ── Rich happy path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rich_happy_path_sends_raw_markdown():
    """sendRichMessage receives the raw agent markdown, NOT MarkdownV2-escaped."""
    adapter = _make_adapter()

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    assert result.message_id == "123"
    adapter._bot.do_api_request.assert_awaited_once()
    api_kwargs = _rich_api_kwargs(adapter)
    # Raw markdown — NOT MarkdownV2-escaped. Table pipes still present.
    assert api_kwargs["rich_message"]["markdown"] == RICH_CONTENT
    assert "| Case | Status |" in api_kwargs["rich_message"]["markdown"]
    assert "- [x] table renders" in api_kwargs["rich_message"]["markdown"]
    # Legacy path must not run on rich success.
    adapter._bot.send_message.assert_not_called()


# ── Content shapes that skip rich ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_details_with_math_skips_rich_send():
    """details+math crashes Telegram Desktop — fall back to legacy MarkdownV2."""
    adapter = _make_adapter()

    result = await adapter.send("12345", DANGEROUS_DETAILS_MATH)

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_cjk_rich_content_skips_rich_send():
    """CJK characters cause TDesktop rich draft garble — fall back to legacy."""
    adapter = _make_adapter()

    result = await adapter.send("12345", CJK_RICH_CONTENT)

    assert result.success is True
    adapter._bot.do_api_request.assert_not_called()
    adapter._bot.send_message.assert_awaited_once()


# ── Rich messages opt-in / opt-out ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_rich_messages_opt_out_uses_legacy_send_path():
    """rich_messages: false forces every reply onto the legacy MarkdownV2 path."""
    adapter = _make_adapter(extra={"rich_messages": False})

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_rich_messages_opt_out_accepts_string_false():
    """YAML may deliver rich_messages as the string 'false' — treat it as False."""
    adapter = _make_adapter(extra={"rich_messages": "false"})

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_rich_messages_default_is_legacy_copyable_path():
    """Rich messages stay opt-in because current Telegram clients can make
    Bot API rich messages hard to copy as plain text. Rich-eligible content
    defaults to the legacy MarkdownV2 path unless the user opts in."""
    config = PlatformConfig(enabled=True, token="fake-token")
    adapter = TelegramAdapter(config)
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value=SimpleNamespace(message_id=123))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_chat_action = AsyncMock()
    adapter._bot = bot

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_rich_messages_can_be_opted_in():
    """Setting platforms.telegram.extra.rich_messages: true enables native
    Bot API rich rendering for tables/task lists/details/math."""
    config = PlatformConfig(
        enabled=True, token="fake-token", extra={"rich_messages": True}
    )
    adapter = TelegramAdapter(config)
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value=SimpleNamespace(message_id=123))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_chat_action = AsyncMock()
    adapter._bot = bot

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_awaited_once()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_rich_messages_can_be_opted_out():
    """Setting platforms.telegram.extra.rich_messages: false keeps every reply
    on the legacy MarkdownV2 path even for rich-eligible content."""
    config = PlatformConfig(
        enabled=True, token="fake-token", extra={"rich_messages": False}
    )
    adapter = TelegramAdapter(config)
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value=SimpleNamespace(message_id=123))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_chat_action = AsyncMock()
    adapter._bot = bot

    result = await adapter.send("12345", RICH_CONTENT)

    assert result.success is True
    bot.do_api_request.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_plain_markdown_uses_rich_path_by_default():
    """All replies, including plain markdown, now use the Rich Text path
    (Bot API 10.1+). The legacy MarkdownV2 path is deprecated."""
    adapter = _make_adapter()

    result = await adapter.send("12345", "Hello **there**\n\nA normal reply.")

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_awaited_with(
        "sendRichMessage",
        api_kwargs={
            "chat_id": 12345,
            "rich_message": {"markdown": "Hello **there**\n\nA normal reply."},
            "disable_notification": True,
        },
    )


# ── Streaming preview: expect_edits born rich ───────────────────────────────


@pytest.mark.asyncio
async def test_expect_edits_metadata_preview_is_born_rich():
    """Streaming previews are BORN rich: editMessageText supports the
    rich_message parameter (Bot API 10.1+), so there is no reason to start
    on the legacy path and upgrade at finalize."""
    adapter = _make_adapter()

    result = await adapter.send(
        "12345",
        RICH_CONTENT,
        metadata={"expect_edits": True},
    )

    assert result.success is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_awaited_once()
    assert bot.do_api_request.call_args.args[0] == "sendRichMessage"
    bot.send_message.assert_not_called()


# ── Oversized rich splitting (> RICH_MESSAGE_MAX_CHARS) ─────────────────────
#
# Content above the 32,768-char rich cap is split fence-aware and delivered
# via sendRichMessage chunks, so >32K replies keep native rendering end to end.


def _oversized(extra_chars=500):
    return "x" * (TelegramAdapter.RICH_MESSAGE_MAX_CHARS + extra_chars)


def _rich_calls(adapter):
    """All sendRichMessage api_kwargs dicts, in call order."""
    return [
        c.kwargs["api_kwargs"]
        for c in adapter._bot.do_api_request.call_args_list
        if c.args and c.args[0] == "sendRichMessage"
    ]


class TestRichSplitSend:

    @pytest.mark.asyncio
    async def test_oversized_content_uses_rich_split_not_legacy(self):
        """>32K content routes through rich split, never legacy MarkdownV2."""
        adapter = _make_adapter()
        oversized = "a" * 40000
        assert len(oversized) > TelegramAdapter.RICH_MESSAGE_MAX_CHARS

        result = await adapter.send("12345", oversized)

        assert result.success is True
        # Multiple rich chunks, zero legacy sends.
        assert adapter._bot.do_api_request.await_count > 1
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_oversized_content_delivers_every_chunk_rich(self):
        """Every chunk of an oversized message goes through sendRichMessage."""
        adapter = _make_adapter()
        adapter._bot.do_api_request = AsyncMock(side_effect=[
            SimpleNamespace(message_id=1001),
            SimpleNamespace(message_id=1002),
        ])

        result = await adapter.send("12345", _oversized())

        assert result.success is True
        assert result.message_id == "1001"
        assert result.raw_response["continuation_message_ids"] == ["1001", "1002"]
        calls = _rich_calls(adapter)
        assert len(calls) == 2
        # No chunk leaked onto the legacy MarkdownV2 path.
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunk_markers_present(self):
        """Each chunk carries its (N/M) indicator inside the rich markdown."""
        adapter = _make_adapter()
        await adapter.send("12345", _oversized())

        calls = _rich_calls(adapter)
        assert len(calls) == 2
        md0 = calls[0]["rich_message"]["markdown"]
        md1 = calls[1]["rich_message"]["markdown"]
        assert "(1/2)" in md0
        assert "(2/2)" in md1

    @pytest.mark.asyncio
    async def test_code_fence_split_keeps_fence_boundaries(self):
        """Fence-aware splitting closes/reopens code blocks across chunks."""
        adapter = _make_adapter()
        content = "```python\n" + ("a" * (TelegramAdapter.RICH_MESSAGE_MAX_CHARS + 100)) + "\n```"

        result = await adapter.send("12345", content)

        assert result.success is True
        calls = _rich_calls(adapter)
        assert len(calls) == 2
        md0 = calls[0]["rich_message"]["markdown"]
        md1 = calls[1]["rich_message"]["markdown"]
        # truncate_message closes the fence inside chunk 1 (the (1/2) marker
        # follows on its own line) and reopens it with the language tag at
        # the start of chunk 2.
        assert md0.count("```") >= 2  # opening ```python + closing ```
        assert md1.lstrip().startswith("```python")

    @pytest.mark.asyncio
    async def test_reply_anchor_on_first_chunk_only(self):
        """Only chunk 1 carries the reply_parameters anchor."""
        adapter = _make_adapter()
        await adapter.send("12345", _oversized(), reply_to="42")

        calls = _rich_calls(adapter)
        assert len(calls) == 2
        assert "reply_parameters" in calls[0]
        assert "reply_parameters" not in calls[1]

    @pytest.mark.asyncio
    async def test_permanent_failure_first_chunk_falls_back_legacy(self):
        """Chunk 0 rejected permanently → nothing delivered → the caller's
        legacy chunking path takes over wholesale."""
        adapter = _make_adapter()
        adapter._bot.do_api_request = AsyncMock(side_effect=BadRequest("can't parse rich"))

        result = await adapter.send("12345", _oversized())

        assert adapter._bot.send_message.await_count >= 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_transient_failure_mid_split_reports_partial_overflow(self):
        """Chunk 0 delivered, chunk 1 transient failure → failure result with
        resume metadata; NO legacy resend of the delivered chunk."""
        adapter = _make_adapter()
        adapter._bot.do_api_request = AsyncMock(side_effect=[
            SimpleNamespace(message_id=1001),
            NetworkError("boom"),
        ])

        result = await adapter.send("12345", _oversized())

        assert result.success is False
        overflow = result.raw_response["partial_overflow"]
        assert overflow["delivered_chunks"] == 1
        assert overflow["total_chunks"] == 2
        assert overflow["continuation_message_ids"] == ["1001"]
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_expect_edits_skips_split(self):
        """Streaming previews (edit transport) must stay single-message so the
        edit transport can track them — oversized previews fall to legacy."""
        adapter = _make_adapter()

        await adapter.send("12345", _oversized(), metadata={"expect_edits": True})

        adapter._bot.do_api_request.assert_not_called()
        assert adapter._bot.send_message.await_count >= 1


# ── Rich overflow edit (finalize with >cap content) ─────────────────────────


class TestRichOverflowEdit:
    """finalize=True with >cap content: rich chunk-1 edit + rich continuations
    instead of the legacy MarkdownV2 overflow split."""

    @pytest.mark.asyncio
    async def test_finalize_oversized_edits_rich_and_continues_rich(self):
        """Oversized finalize: chunk-1 edits the preview rich, remaining chunks
        are sent as rich continuations threaded as replies."""
        adapter = _make_adapter()
        adapter._bot.do_api_request = AsyncMock(side_effect=[
            SimpleNamespace(message_id=777),    # editMessageText (chunk 1)
            SimpleNamespace(message_id=2002),   # sendRichMessage (chunk 2)
        ])

        result = await adapter.edit_message("12345", "777", _oversized(), finalize=True)

        assert result.success is True
        assert result.message_id == "2002"
        assert result.raw_response["continuation_message_ids"] == ["2002"]
        calls = adapter._bot.do_api_request.call_args_list
        assert [c.args[0] for c in calls] == ["editMessageText", "sendRichMessage"]
        # Continuation is threaded as a reply to the previous message.
        assert "reply_parameters" in calls[1].kwargs["api_kwargs"]
        # Nothing leaked onto the legacy paths.
        adapter._bot.edit_message_text.assert_not_called()
        adapter._bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_permanent_first_chunk_edit_falls_back_legacy_split(self):
        """Rich edit rejection on chunk 1 falls back to legacy overflow split."""
        adapter = _make_adapter()
        adapter._bot.do_api_request = AsyncMock(
            side_effect=BadRequest("rich edit rejected")
        )

        result = await adapter.edit_message("12345", "777", _oversized(), finalize=True)

        assert result.success is True
        assert adapter._bot.edit_message_text.await_count >= 1
        assert adapter._bot.send_message.await_count >= 1


# ── Monoblock segments (segment breaks keep same message) ───────────────────


class TestMonoblockSegments:
    """With rich enabled and edit transport (no draft streaming), segment
    breaks keep editing the SAME message instead of spawning new bubbles.
    The accumulated text grows monotonically in one bubble (monoblock)."""

    def test_segment_break_keeps_same_message(self):
        """A single segment break with rich enabled preserves _message_id."""
        adapter = _make_adapter()
        consumer = GatewayStreamConsumer(
            adapter,
            "12345",
            StreamConsumerConfig(transport="edit", cursor=""),
        )
        consumer._use_draft_streaming = False
        # Simulate an existing message being edited
        consumer._message_id = "999"
        consumer._accumulated = "First segment text"
        consumer._last_sent_text = "First segment text"

        # Trigger monoblock carry
        assert consumer._monoblock_segments_enabled() is True
        consumer._carry_segment_into_monoblock()

        # _message_id preserved — next segment edits the same bubble
        assert consumer._message_id == "999"
        # Accumulated text preserved — next frame continues growing
        assert consumer._accumulated == "First segment text"
        # Delivered text archived for dedup bookkeeping
        assert "First segment text" in consumer._delivered_segment_texts

    def test_multiple_segment_breaks_stay_monoblock(self):
        """Multiple consecutive segment breaks all keep the same message."""
        adapter = _make_adapter()
        consumer = GatewayStreamConsumer(
            adapter,
            "12345",
            StreamConsumerConfig(transport="edit", cursor=""),
        )
        consumer._use_draft_streaming = False
        consumer._message_id = "888"
        consumer._accumulated = "Segment A"
        consumer._last_sent_text = "Segment A"

        # First break
        consumer._carry_segment_into_monoblock()
        assert consumer._message_id == "888"
        consumer._accumulated = "Segment A\n\nSegment B"
        consumer._last_sent_text = "Segment A\n\nSegment B"

        # Second break
        consumer._carry_segment_into_monoblock()
        assert consumer._message_id == "888"
        assert len(consumer._delivered_segment_texts) == 2

    def test_non_rich_adapter_keeps_legacy_segment_behavior(self):
        """Without rich_messages enabled, segment breaks reset to new messages."""
        adapter = _make_adapter(extra={"rich_messages": False})
        consumer = GatewayStreamConsumer(
            adapter,
            "12345",
            StreamConsumerConfig(transport="edit", cursor=""),
        )
        consumer._use_draft_streaming = False

        # Monoblock disabled when rich is off
        assert consumer._monoblock_segments_enabled() is False

    def test_draft_streaming_disables_monoblock(self):
        """Draft streaming uses per-segment draft→finalize, not monoblock."""
        adapter = _make_adapter()
        consumer = GatewayStreamConsumer(
            adapter,
            "12345",
            StreamConsumerConfig(transport="auto", chat_type="dm", cursor=""),
        )
        consumer._use_draft_streaming = True

        assert consumer._monoblock_segments_enabled() is False


# ── Non-finalize edits use rich too ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_finalize_edit_uses_rich_too():
    """Intermediate (non-finalize) stream edits also use the rich edit path —
    Rich Text is the default for every edit, not just the final one, so
    streaming keeps rich rendering from the first frame."""
    adapter = _make_adapter()

    result = await adapter.edit_message(
        "12345", "555", RICH_CONTENT, finalize=False,
    )

    assert result.success is True
    api_kwargs = _rich_edit_kwargs(adapter)
    assert api_kwargs["rich_message"]["markdown"] == RICH_CONTENT
    adapter._bot.edit_message_text.assert_not_called()


# ── Bot API 9.5+ draft streaming alignment ──────────────────────────────────


def test_supports_draft_streaming_enabled_for_dm_regardless_of_rich_drafts():
    """Upstream (Bot API 9.5+) enables draft streaming for DM unconditionally.

    rich_drafts controls the draft *format*, not availability. The old gate
    that disabled draft streaming when rich was on but rich_drafts was off
    has been removed upstream."""
    adapter = _make_adapter()  # rich_messages True, rich_drafts default False
    assert adapter.supports_draft_streaming(chat_type="dm") is True
    assert adapter.supports_draft_streaming(chat_type="private") is True


# ── Helper for rich edit assertions ─────────────────────────────────────────


def _rich_edit_kwargs(adapter):
    """Return the api_kwargs dict from the single editMessageText rich call."""
    call = adapter._bot.do_api_request.call_args
    assert call.args[0] == "editMessageText"
    return call.kwargs["api_kwargs"]



# ── Recovered upstream tests ─────────────────────────────────────────────



# ----------------------------------------------------------------------
# prefers_fresh_final_streaming: root DMs stay on the no-duplicate edit/draft
# path (#47048). DM topics that degrade off drafts still need a fresh
# sendRichMessage so tables are not flattened by format_message.
# ----------------------------------------------------------------------
def test_prefers_fresh_final_streaming_stays_disabled_when_rich_enabled():
    adapter = _make_adapter()
    assert adapter.prefers_fresh_final_streaming(RICH_CONTENT) is False
    assert adapter.prefers_fresh_final_streaming(RICH_CONTENT, None) is False


def test_prefers_fresh_final_streaming_for_dm_topics_preserves_preview():
    adapter = _make_adapter()
    topic_meta = {
        "thread_id": "20189",
        "telegram_dm_topic_reply_fallback": True,
        "direct_messages_topic_id": "20189",
        "telegram_reply_to_message_id": "42",
    }
    assert adapter.prefers_fresh_final_streaming(RICH_CONTENT, topic_meta) is False
    assert adapter.prefers_fresh_final_streaming("Just a sentence.", topic_meta) is False
    assert adapter.prefers_fresh_final_streaming(
        RICH_CONTENT, {"direct_messages_topic_id": "20189"}
    ) is False
    assert adapter.prefers_fresh_final_streaming(
        RICH_CONTENT, {"telegram_direct_messages_topic_id": "20189"}
    ) is False


@pytest.mark.asyncio
async def test_legacy_draft_stream_finalizes_with_persistent_rich_message():
    """A plain draft must not force the persistent final to MarkdownV2."""
    adapter = _make_adapter()  # rich messages on, rich drafts off
    assert adapter.supports_draft_streaming(chat_type="dm") is True

    consumer = GatewayStreamConsumer(
        adapter,
        "12345",
        StreamConsumerConfig(transport="auto", chat_type="dm", cursor=""),
    )
    consumer._use_draft_streaming = True

    delivered = await consumer._send_or_edit(RICH_CONTENT, finalize=True)

    assert delivered is True
    bot = adapter._bot
    assert bot is not None
    bot.do_api_request.assert_awaited_once()
    assert bot.do_api_request.call_args.args[0] == "sendRichMessage"
    bot.send_message.assert_not_called()


# ----------------------------------------------------------------------
# supports_draft_streaming: rich_drafts controls draft rendering, not whether
# Telegram's ephemeral DM draft transport is available.  Keeping that transport
# lets the persistent final use sendRichMessage instead of relying on an
# edit-in-place conversion from a plain message.
# ----------------------------------------------------------------------




# ----------------------------------------------------------------------
# supports_draft_streaming: rich_drafts controls draft rendering, not whether
# Telegram's ephemeral DM draft transport is available.  Keeping that transport
# lets the persistent final use sendRichMessage instead of relying on an
# edit-in-place conversion from a plain message.
# ----------------------------------------------------------------------
def test_supports_plain_draft_streaming_when_rich_without_rich_drafts():
    adapter = _make_adapter()  # rich_messages True, rich_drafts default False
    assert adapter.supports_draft_streaming(chat_type="dm") is True
    assert adapter.supports_draft_streaming(chat_type="private") is True


@pytest.mark.asyncio
async def test_rich_table_uses_raw_plain_draft_before_persistent_rich_final():
    adapter = _make_adapter()  # rich messages on, rich drafts off

    result = await adapter.send_draft("12345", draft_id=7, content=RICH_CONTENT)

    assert result.success is True
    adapter._bot.do_api_request.assert_not_called()
    adapter._bot.send_message_draft.assert_awaited_once_with(
        chat_id=12345,
        draft_id=7,
        text=RICH_CONTENT,
    )


@pytest.mark.asyncio
async def test_dm_table_stream_persists_through_send_rich_message():
    """Exercise the reporter's transport: ephemeral DM draft, then rich final."""
    adapter = _make_adapter()  # rich messages on, rich drafts off
    consumer = GatewayStreamConsumer(
        adapter,
        "12345",
        StreamConsumerConfig(
            transport="auto",
            chat_type="dm",
            edit_interval=0.01,
            buffer_threshold=1,
            cursor="",
        ),
    )

    task = asyncio.create_task(consumer.run())
    consumer.on_delta(RICH_CONTENT)
    await asyncio.sleep(0.05)
    consumer.finish()
    await task

    adapter._bot.send_message_draft.assert_awaited()
    draft_kwargs = adapter._bot.send_message_draft.call_args.kwargs
    assert draft_kwargs["text"] == RICH_CONTENT
    assert "parse_mode" not in draft_kwargs
    rich_endpoints = [call.args[0] for call in adapter._bot.do_api_request.await_args_list]
    assert rich_endpoints == ["sendRichMessage"]
    adapter._bot.edit_message_text.assert_not_called()
    adapter._bot.send_message.assert_not_called()


TOPIC_METADATA = {
    "thread_id": "20189",
    "telegram_dm_topic_reply_fallback": True,
    "direct_messages_topic_id": "20189",
    "telegram_reply_to_message_id": "42",
}

# Shape from the Telegram iOS DM-topic report: blank line, then a GFM table.
TOPIC_TABLE = (
    "Here's a table:\n"
    "\n"
    "| Sport | Followed? | Notes |\n"
    "|---|---|---|\n"
    "| F1 | ✅ | |\n"
    "| MLB | ✅ | |\n"
    "| LoL | ✅ | |\n"
)


@pytest.mark.asyncio
async def test_send_draft_routes_dm_topic_thread_id_as_int():
    """Drafts must use the same integer thread routing as send(), not the
    raw string thread_id. Telegram rejects the string on private topics."""
    adapter = _make_adapter()

    result = await adapter.send_draft(
        "12345", draft_id=7, content=TOPIC_TABLE, metadata=TOPIC_METADATA,
    )

    assert result.success is True
    kwargs = adapter._bot.send_message_draft.call_args.kwargs
    assert kwargs["message_thread_id"] == 20189
    assert kwargs["text"] == TOPIC_TABLE
    assert "parse_mode" not in kwargs


@pytest.mark.asyncio
async def test_dm_topic_table_stream_uses_send_rich_message():
    """Happy-path topic stream: drafts land, persistent final is rich."""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter,
        "12345",
        StreamConsumerConfig(
            transport="auto",
            chat_type="dm",
            edit_interval=0.01,
            buffer_threshold=1,
            cursor="",
        ),
        metadata=dict(TOPIC_METADATA),
        initial_reply_to_id="42",
    )

    task = asyncio.create_task(consumer.run())
    consumer.on_delta(TOPIC_TABLE)
    await asyncio.sleep(0.05)
    consumer.finish()
    await task

    adapter._bot.send_message_draft.assert_awaited()
    draft_kwargs = adapter._bot.send_message_draft.call_args.kwargs
    assert draft_kwargs["text"] == TOPIC_TABLE
    assert draft_kwargs["message_thread_id"] == 20189
    rich_endpoints = [call.args[0] for call in adapter._bot.do_api_request.await_args_list]
    # Invariant, not a frozen call list: the persistent final goes through
    # sendRichMessage, and no rich DRAFT frames fire (rich_drafts is off).
    assert "sendRichMessage" in rich_endpoints
    assert "sendRichMessageDraft" not in rich_endpoints
    adapter._bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_dm_topic_table_survives_when_drafts_degrade_to_edit():
    """Reporter path: sendMessageDraft fails in a private topic, Telegram
    then rejects a rich edit of the plain MarkdownV2 preview. The final
    must still persist through sendRichMessage — not convert_table_to_bullets.
    """
    adapter = _make_adapter()
    adapter._bot.send_message_draft = AsyncMock(
        side_effect=BadRequest("Bad Request: message thread not found")
    )

    async def _api(endpoint, api_kwargs=None, **kwargs):
        if endpoint == "editMessageText" and api_kwargs and "rich_message" in api_kwargs:
            raise BadRequest("can't parse rich message")
        if endpoint == "sendRichMessage":
            return SimpleNamespace(message_id=123)
        return SimpleNamespace(message_id=1)

    adapter._bot.do_api_request = AsyncMock(side_effect=_api)

    consumer = GatewayStreamConsumer(
        adapter,
        "12345",
        StreamConsumerConfig(
            transport="auto",
            chat_type="dm",
            edit_interval=0.01,
            buffer_threshold=1,
            cursor="",
        ),
        metadata=dict(TOPIC_METADATA),
        initial_reply_to_id="42",
    )

    task = asyncio.create_task(consumer.run())
    consumer.on_delta(TOPIC_TABLE)
    await asyncio.sleep(0.08)
    consumer.finish()
    await task

    rich_endpoints = [call.args[0] for call in adapter._bot.do_api_request.await_args_list]
    assert "sendRichMessage" in rich_endpoints
    rich_kwargs = None
    for call in adapter._bot.do_api_request.await_args_list:
        if call.args[0] == "sendRichMessage":
            rich_kwargs = call.kwargs["api_kwargs"]
            break
    assert rich_kwargs is not None
    assert "| F1 |" in rich_kwargs["rich_message"]["markdown"]
    # Fork: the rich send path delivers the table natively without going
    # through the draft→edit degradation cycle, so there is no stale
    # preview to clean up.  The upstream delete_message assertion is
    # not applicable when sendRichMessage handles both preview and final.


def test_supports_draft_streaming_enabled_when_rich_drafts_opt_in():
    adapter = _make_adapter(extra={"rich_drafts": True})
    assert adapter.supports_draft_streaming(chat_type="dm") is True
    assert adapter.supports_draft_streaming(chat_type="group") is False


def test_supports_draft_streaming_legacy_when_rich_messages_off():
    adapter = _make_adapter(extra={"rich_messages": False})
    assert adapter.supports_draft_streaming(chat_type="dm") is True


# ----------------------------------------------------------------------
# streaming_overflow_limit: with rich on, the stream consumer may accumulate up
# to the 32,768-char rich cap before splitting, so a reply that fits one
# sendRichMessage / sendRichMessageDraft isn't fragmented at the 4,096 limit.
# ----------------------------------------------------------------------




# ----------------------------------------------------------------------
# streaming_overflow_limit: with rich on, the stream consumer may accumulate up
# to the 32,768-char rich cap before splitting, so a reply that fits one
# sendRichMessage / sendRichMessageDraft isn't fragmented at the 4,096 limit.
# ----------------------------------------------------------------------
def test_streaming_overflow_limit_none_when_rich_latched_off():
    adapter = _make_adapter()
    adapter._rich_send_disabled = True
    assert adapter.streaming_overflow_limit() is None


# ----------------------------------------------------------------------------
# Rich finalize via editMessageText (Bot API 10.1 rich_message edit param).
# Streamed previews finalize by editing the existing message IN PLACE as rich,
# so tables/task lists survive without a fresh send + delete (no duplicate).
# ----------------------------------------------------------------------------
