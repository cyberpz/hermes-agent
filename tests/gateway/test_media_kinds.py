import importlib

import pytest

from gateway.platforms.base import BasePlatformAdapter, MediaKind, classify_media_kind

I, V, A, D = MediaKind.IMAGE, MediaKind.VIDEO, MediaKind.VOICE, MediaKind.DOCUMENT
FULL = frozenset({I, V, A, D})

# The single source of truth for what each adapter natively delivers. A kind
# listed here MUST be backed by a real send_* override; the descriptor exists
# so dispatch sites can skip-and-warn rather than leak a path as chat text.
PINNED_MEDIA_KINDS = {
    "gateway.platforms.telegram:TelegramAdapter": FULL,
    "gateway.platforms.slack:SlackAdapter": FULL,
    "gateway.platforms.signal:SignalAdapter": FULL,
    "gateway.platforms.matrix:MatrixAdapter": FULL,
    "gateway.platforms.whatsapp:WhatsAppAdapter": FULL,
    "gateway.platforms.wecom:WeComAdapter": FULL,
    "gateway.platforms.bluebubbles:BlueBubblesAdapter": FULL,
    "gateway.platforms.feishu:FeishuAdapter": FULL,
    "gateway.platforms.qqbot.adapter:QQAdapter": FULL,
    "gateway.platforms.weixin:WeixinAdapter": FULL,
    "gateway.platforms.email:EmailAdapter": frozenset({I, D}),
    "gateway.platforms.yuanbao:YuanbaoAdapter": frozenset({I, D}),
    "gateway.platforms.dingtalk:DingTalkAdapter": frozenset(),
    "gateway.platforms.sms:SmsAdapter": frozenset(),
    "gateway.platforms.homeassistant:HomeAssistantAdapter": frozenset(),
    "gateway.platforms.webhook:WebhookAdapter": frozenset(),
    "gateway.platforms.msgraph_webhook:MSGraphWebhookAdapter": frozenset(),
    "plugins.platforms.discord.adapter:DiscordAdapter": FULL,
    "plugins.platforms.google_chat.adapter:GoogleChatAdapter": FULL,
    "plugins.platforms.mattermost.adapter:MattermostAdapter": FULL,
    "plugins.platforms.line.adapter:LineAdapter": frozenset({I, V, A}),
    "plugins.platforms.teams.adapter:TeamsAdapter": frozenset({I}),
    "plugins.platforms.simplex.adapter:SimplexAdapter": frozenset(),
    "plugins.platforms.irc.adapter:IRCAdapter": frozenset(),
    "plugins.platforms.ntfy.adapter:NtfyAdapter": frozenset(),
}


@pytest.mark.parametrize("ref,expected", PINNED_MEDIA_KINDS.items())
def test_media_kinds_pinned(ref, expected):
    mod, cls = ref.split(":")
    adapter_cls = getattr(importlib.import_module(mod), cls)
    assert adapter_cls.MEDIA_KINDS == expected


# The per-file method ``_dispatch_media_one`` (tools/send_message_tool.py)
# actually calls for each kind. This is the path with NO batch fallback, so
# the declared kind MUST override the exact method here — otherwise the base
# stub runs and leaks the local path as chat text. (send_multiple_images is an
# optional batch optimization; base.send_multiple_images loops file:// back to
# send_image_file, so send_image_file is the true terminal IMAGE method.)
_DISPATCH_METHOD = {
    I: "send_image_file",
    V: "send_video",
    A: "send_voice",
    D: "send_document",
}


@pytest.mark.parametrize("ref,expected", PINNED_MEDIA_KINDS.items())
def test_declared_kinds_are_backed_by_real_overrides(ref, expected):
    """Every declared kind must override the method its dispatch site calls.

    Asserts the descriptor's documented invariant ("MUST be backed by a real
    send_* override") executably, so a future adapter that declares a kind it
    doesn't deliver fails loudly in CI instead of leaking a path as chat text.
    """
    mod, cls = ref.split(":")
    adapter_cls = getattr(importlib.import_module(mod), cls)
    for kind in expected:
        method = _DISPATCH_METHOD[kind]
        assert getattr(adapter_cls, method) is not getattr(BasePlatformAdapter, method), (
            f"{cls} declares {kind.name} but inherits base {method} "
            f"(the base stub leaks the local path as chat text)"
        )


def test_platform_entry_has_no_media_kinds_field():
    # The descriptor lives on the adapter class only. Mirroring it onto
    # PlatformEntry would couple the ungated out-of-process standalone path
    # to a capability it cannot honor.
    from gateway.platform_registry import PlatformEntry

    assert "media_kinds" not in PlatformEntry.__dataclass_fields__


def test_media_kind_has_four_members():
    assert {k.name for k in MediaKind} == {"IMAGE", "VIDEO", "VOICE", "DOCUMENT"}


def test_base_default_is_fail_closed_empty():
    assert BasePlatformAdapter.MEDIA_KINDS == frozenset()


def test_classify_image_video_document():
    assert classify_media_kind("/x/a.png", platform="qqbot") is MediaKind.IMAGE
    assert classify_media_kind("/x/a.mp4", platform="qqbot") is MediaKind.VIDEO
    assert classify_media_kind("/x/a.pdf", platform="qqbot") is MediaKind.DOCUMENT


def test_classify_audio_routes_to_voice_on_non_telegram():
    assert classify_media_kind("/x/a.mp3", platform="slack") is MediaKind.VOICE
    assert classify_media_kind("/x/a.ogg", is_voice=True, platform="slack") is MediaKind.VOICE


def test_classify_force_document_overrides_image():
    assert classify_media_kind("/x/a.png", platform="qqbot", force_document=True) is MediaKind.DOCUMENT
