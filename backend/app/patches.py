"""Third-party fixes applied once at startup.

langchain_anthropic 1.3.2 crashes with "'dict' object has no attribute
'model_dump'" while streaming web-search beta events: message_delta carries a
plain dict `container`. Wrap it so the original parser can call model_dump().
Remove this once the pinned version is fixed upstream.

The patch replaces a private module function, so it must fail loudly when
upstream renames it rather than silently stop applying:
tests/test_upstream_hooks.py checks that the symbol exists and that the
streaming path still calls it, and a missing symbol raises here.
"""

PATCHED_ATTR = "_crucible_patched"
ANTHROPIC_HOOK = "_make_message_chunk_from_anthropic_event"

_applied = False


class _ContainerDump:
    """Gives a plain-dict `container` the model_dump() the parser expects."""

    def __init__(self, data: dict):
        self.data = data

    def model_dump(self, mode=None, **kw):
        return self.data


def wrap_dict_container(event) -> None:
    """Make a message_delta event's dict `container` parseable, in place."""
    if getattr(event, "type", None) != "message_delta":
        return
    delta = getattr(event, "delta", None)
    if delta is not None and isinstance(getattr(delta, "container", None), dict):
        delta.container = _ContainerDump(delta.container)


def apply_langchain_patches() -> None:
    global _applied
    if _applied:
        return
    try:
        import langchain_anthropic.chat_models as anthropic_chat
    except ImportError:  # provider not installed: nothing to patch
        _applied = True
        return

    original = getattr(anthropic_chat, ANTHROPIC_HOOK, None)
    if original is None:
        raise RuntimeError(
            f"langchain_anthropic.chat_models.{ANTHROPIC_HOOK} no longer exists; "
            "the web-search streaming fix in app/patches.py cannot apply. "
            "Check whether the upstream bug is fixed and update or remove the patch."
        )
    if getattr(original, PATCHED_ATTR, False):
        _applied = True
        return

    def _safe_make_chunk(event, *args, **kwargs):
        wrap_dict_container(event)
        return original(event, *args, **kwargs)

    setattr(_safe_make_chunk, PATCHED_ATTR, True)
    _safe_make_chunk.__wrapped__ = original
    setattr(anthropic_chat, ANTHROPIC_HOOK, _safe_make_chunk)
    _applied = True
