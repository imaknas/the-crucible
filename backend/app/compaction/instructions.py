"""What the summarizer is asked to write.

The instruction is one of the things compaction experiments vary (length,
emphasis, another tool's prompt), so the host asks a SummaryInstruction for
the prompt instead of hard-coding it. Each instruction receives the
transcript to fold in (which may start with the previous summary) and
returns the full prompt.
"""

from typing import Protocol


class SummaryInstruction(Protocol):
    name: str

    def prompt(self, transcript: str) -> str: ...


class DetailedBrief:
    """The Crucible's original instruction: a detailed technical brief, with
    no length limit (in practice the summary grows with the conversation)."""

    name = "brief"

    def prompt(self, transcript: str) -> str:
        return (
            "Summarize the following conversation history into a concise, detailed technical brief. "
            "IMPORTANT: Preserve the attribution of which speaker (User or specific model name) made each key argument or claim. "
            f"Maintain all key arguments and theses identified so far.\n\n{transcript}"
        )


class LengthTarget:
    """The original instruction plus a length limit, and nothing else, so a
    comparison with DetailedBrief isolates the effect of length."""

    def __init__(self, tokens: int, base: SummaryInstruction = DetailedBrief()):
        self.tokens = tokens
        self.base = base
        self.name = f"{base.name}-{tokens}"

    def prompt(self, transcript: str) -> str:
        words = int(self.tokens * 0.75)
        instruction, _, text = self.base.prompt(transcript).partition("\n\n")
        return f"{instruction} Keep the brief to at most about {words} words.\n\n{text}"
