"""Third-party fixes applied once at startup.

langchain_anthropic 1.3.2 crashes with "'dict' object has no attribute
'model_dump'" while streaming web-search beta events: message_delta carries a
plain dict `container`. Wrap it so the original parser can call model_dump().
Remove this once the pinned version is fixed upstream.
"""

_applied = False


def apply_langchain_patches() -> None:
    global _applied
    if _applied:
        return
    _applied = True
    try:
        import langchain_anthropic.chat_models

        _original_make_chunk = (
            langchain_anthropic.chat_models._make_message_chunk_from_anthropic_event
        )

        def _safe_make_chunk(event, *args, **kwargs):
            if getattr(event, "type", None) == "message_delta":
                delta = getattr(event, "delta", None)
                if delta and getattr(delta, "container", None) is not None:
                    if isinstance(delta.container, dict):

                        class MockContainer:
                            def __init__(self, d):
                                self.d = d

                            def model_dump(self, mode=None, **kw):
                                return self.d

                        delta.container = MockContainer(delta.container)
            return _original_make_chunk(event, *args, **kwargs)

        langchain_anthropic.chat_models._make_message_chunk_from_anthropic_event = (
            _safe_make_chunk
        )
    except Exception:
        pass
