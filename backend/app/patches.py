"""Third-party fixes applied once at startup.

langchain_anthropic crashes with "'dict' object has no attribute
'model_dump'" while streaming web-search beta events: message_delta carries a
plain dict `container`, and the chunk parser calls `container.model_dump()`.
Found in 1.3.2 and still present in 1.7.6, where the parser moved from a
module function to a ChatAnthropic method. Wrap the dict so the parser can call
model_dump(). Remove this once upstream handles a dict container.

The patch replaces a private method, so it must fail loudly when upstream
renames it rather than silently stop applying: tests/test_upstream_hooks.py
checks that the method exists and that the streaming path still calls it,
and a missing method raises here.
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
        from langchain_anthropic.chat_models import ChatAnthropic
    except ImportError:  # provider not installed: nothing to patch
        _applied = True
        return

    original = getattr(ChatAnthropic, ANTHROPIC_HOOK, None)
    if original is None:
        raise RuntimeError(
            f"langchain_anthropic ChatAnthropic.{ANTHROPIC_HOOK} no longer exists; "
            "the web-search streaming fix in app/patches.py cannot apply. "
            "Check whether the upstream bug is fixed and update or remove the patch."
        )
    if getattr(original, PATCHED_ATTR, False):
        _applied = True
        return

    def _safe_make_chunk(self, event, *args, **kwargs):
        wrap_dict_container(event)
        return original(self, event, *args, **kwargs)

    setattr(_safe_make_chunk, PATCHED_ATTR, True)
    _safe_make_chunk.__wrapped__ = original
    setattr(ChatAnthropic, ANTHROPIC_HOOK, _safe_make_chunk)
    _applied = True
