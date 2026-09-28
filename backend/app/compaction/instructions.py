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


class StateAndIndex:
    """What to carry forward, chosen by what cannot be recovered otherwise:
    who stated what (authority), the latest value of everything still in
    play (state), and an index of what was discussed, so details left out can
    be found again in the full history rather than rewritten here."""

    name = "state"
    instruction = (
        "Condense the conversation history below into a record the conversation can continue from.\n"
        "1. Current state: every decision, agreed value, constraint and open item, each with who stated it "
        "(User or the model's name). When a value was changed, give only the latest one and note that it replaced an earlier one.\n"
        "2. Index: one line per topic or subject that came up, naming it plainly so it can be looked up later.\n"
        "Leave out discussion that led nowhere. Be concise."
    )

    def prompt(self, transcript: str) -> str:
        return f"{self.instruction}\n\n{transcript}"


class IndexOnly:
    """A pure pointer: which topics exist, nothing about them. Useful only
    with recall, which fetches the details when a question needs them."""

    name = "index"
    instruction = (
        "List every topic, component or subject that came up in the conversation history below, "
        "one per line, by the exact name used in the conversation. No values, details or decisions."
    )

    def prompt(self, transcript: str) -> str:
        return f"{self.instruction}\n\n{transcript}"


class AllSubjects:
    """Another instruction plus a warning that priorities may change, asking
    for the specifics of every subject rather than only the current goal.
    Knows nothing about the conversation: it tests whether a generic hedge,
    written before anyone knows the next goal, prevents off-goal loss."""

    note = (
        " Priorities may change later in this conversation: keep the specific values (numbers, names, "
        "identifiers, dates, decisions, exclusions) for every subject that came up, not only the current goal."
    )

    def __init__(self, base: SummaryInstruction = DetailedBrief()):
        self.base = base
        self.name = f"{base.name}-allsubjects"

    @property
    def instruction(self) -> str:
        return self.base.instruction + self.note

    def prompt(self, transcript: str) -> str:
        return self.base.prompt(transcript).replace(self.base.instruction, self.instruction, 1)


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
