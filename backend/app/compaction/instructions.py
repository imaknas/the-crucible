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
    # The instruction text itself, without the transcript.
    instruction: str

    def prompt(self, transcript: str) -> str: ...


class DetailedBrief:
    """The Crucible's original instruction: a detailed technical brief, with
    no length limit (in practice the summary grows with the conversation)."""

    name = "brief"
    instruction = (
        "Summarize the following conversation history into a concise, detailed technical brief. "
        "IMPORTANT: Preserve the attribution of which speaker (User or specific model name) made each key argument or claim. "
        "Maintain all key arguments and theses identified so far."
    )

    def prompt(self, transcript: str) -> str:
        return f"{self.instruction}\n\n{transcript}"


class HandoffBrief:
    """Codex CLI's compaction prompt: a handoff for the model that resumes the
    work, placed after the history as Codex does. Text from openai/codex,
    codex-rs/prompts/templates/compact/prompt.md (Apache-2.0)."""

    name = "handoff"
    instruction = (
        "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM "
        "that will resume the task.\n\n"
        "Include:\n"
        "- Current progress and key decisions made\n"
        "- Important context, constraints, or user preferences\n"
        "- What remains to be done (clear next steps)\n"
        "- Any critical data, examples, or references needed to continue\n\n"
        "Be concise, structured, and focused on helping the next LLM seamlessly continue the work."
    )

    def prompt(self, transcript: str) -> str:
        return f"{transcript}\n\n{self.instruction}"


class LengthTarget:
    """The original instruction plus a length limit, and nothing else, so a
    comparison with DetailedBrief isolates the effect of length."""

    def __init__(self, tokens: int, base: SummaryInstruction = DetailedBrief()):
        self.tokens = tokens
        self.base = base
        self.name = f"{base.name}-{tokens}"

    @property
    def instruction(self) -> str:
        return f"{self.base.instruction} Keep the summary to at most about {int(self.tokens * 0.75)} words."

    def prompt(self, transcript: str) -> str:
        return self.base.prompt(transcript).replace(self.base.instruction, self.instruction, 1)
