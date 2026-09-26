"""Detail-retention scenarios: does a specific fact survive compaction?

A scenario is a long, deterministic conversation with facts planted at chosen
turns, buried mid-message (summaries tend to keep openings), surrounded by
plausible filler. After the conversation, each fact is probed with a
question whose answer can be checked by string match.

Facts are fictional so a model can't answer from prior knowledge, and they
cover the kinds of detail summaries tend to drop: numbers, names, identifiers,
dates, exact wording, and negations ("we agreed NOT to ...").
"""

import random
import re
from dataclasses import dataclass, field
from typing import Optional, Sequence


@dataclass(frozen=True)
class PlantedFact:
    key: str
    kind: str
    statement: str
    question: str
    answers: tuple[str, ...]


DEFAULT_FACTS: tuple[PlantedFact, ...] = (
    PlantedFact("budget", "number", "The procurement cap for the pilot is 47,300 euros.",
                "What is the procurement cap for the pilot, in euros?", ("47,300", "47300", "47 300")),
    PlantedFact("reviewer", "name", "The on-call reviewer for the data pipeline is Ilse Marchetti.",
                "Who is the on-call reviewer for the data pipeline?", ("marchetti",)),
    PlantedFact("key_label", "identifier", "Every export must be encrypted with the key labelled ORCHID-7.",
                "Which key label must exports be encrypted with?", ("orchid-7", "orchid 7", "orchid7")),
    PlantedFact("no_kafka", "negation", "We agreed not to use Kafka for the event bus.",
                "Which technology did we agree not to use for the event bus?", ("kafka",)),
    PlantedFact("freeze", "date", "The migration freeze starts on 14 March.",
                "On what date does the migration freeze start?", ("14 march", "march 14", "14th of march", "march 14th")),
    PlantedFact("port", "identifier", "The staging database listens on port 6543.",
                "Which port does the staging database listen on?", ("6543",)),
    PlantedFact("quote", "quote", "The client's exact words were 'latency first, features second'.",
                "What were the client's exact words about priorities?", ("latency first, features second", "latency first features second")),
    PlantedFact("vendor", "choice", "Of the three vendors we picked Northwind over Contoso and Fabrikam.",
                "Which vendor did we pick?", ("northwind",)),
)


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str
    fact_key: Optional[str] = None


@dataclass
class Scenario:
    turns: list[Turn]
    facts: list[PlantedFact]
    # fact key -> index into `turns` where it was planted
    positions: dict[str, int] = field(default_factory=dict)

    def probe_prompt(self, fact: PlantedFact) -> str:
        return f"Quick check on something from earlier in this conversation: {fact.question} Answer with just the value."


# ─── Filler ──────────────────────────────────────────────────────

_TOPICS = [
    "the rollout plan", "the logging setup", "the onboarding docs", "the test coverage",
    "the incident runbook", "the search feature", "the billing module", "the mobile client",
    "the caching layer", "the permissions model", "the analytics dashboard", "the release cadence",
]
_OPENERS = [
    "Let's go back to {t}.", "One more thing about {t}.", "I've been thinking about {t}.",
    "Can we revisit {t}?", "Quick update on {t}.", "Following up on {t}.",
]
_USER_BODY = [
    "The team feels the current approach is too slow to iterate on.",
    "Nobody owns it right now, which is part of the problem.",
    "We tried a simpler version last quarter and it mostly worked.",
    "I'd like a recommendation we can act on this week.",
    "There's some disagreement about how much to invest here.",
    "The main risk is that it grows without anyone noticing.",
    "Leadership wants a short written rationale before we commit.",
    "We should keep whatever we do easy to undo.",
]
_ASSISTANT_BODY = [
    "A reasonable first step is to write down what 'done' looks like so the scope stays bounded.",
    "I'd separate the decision from the implementation and time-box the investigation to a few days.",
    "It helps to measure the current state before changing it, otherwise improvements are hard to show.",
    "Assigning a single owner usually does more than any tooling change.",
    "Start with the smallest change that produces a visible result, then expand if it holds up.",
    "Document the trade-offs briefly; the rationale matters more than the format.",
    "If the risk is silent growth, a simple weekly metric with an alert threshold is often enough.",
    "Prefer reversible choices here, since the requirements are still moving.",
    "A short pilot with one team will surface most of the problems before a wider rollout.",
    "Keep the interface stable and iterate behind it; that limits the blast radius of mistakes.",
]


def _user_turn(rng: random.Random, fact: Optional[PlantedFact]) -> Turn:
    topic = rng.choice(_TOPICS)
    parts = [rng.choice(_OPENERS).format(t=topic), rng.choice(_USER_BODY)]
    if fact:
        parts.append(fact.statement)  # mid-message, never the opener
    parts.append(rng.choice(_USER_BODY))
    return Turn("user", " ".join(parts), fact.key if fact else None)


def _assistant_turn(rng: random.Random, sentences: int) -> Turn:
    return Turn("assistant", " ".join(rng.sample(_ASSISTANT_BODY, k=min(sentences, len(_ASSISTANT_BODY)))))


def build_scenario(
    facts: Sequence[PlantedFact] = DEFAULT_FACTS,
    *,
    exchanges: int = 40,
    fact_exchanges: Optional[Sequence[int]] = None,
    assistant_sentences: int = 6,
    seed: int = 0,
) -> Scenario:
    """A conversation of `exchanges` user/assistant pairs with `facts` planted.

    By default facts are spread evenly over the first 80% of the conversation,
    so later facts sit inside the verbatim tail a summary usually preserves
    and earlier ones don't.
    """
    rng = random.Random(seed)
    facts = list(facts)
    if fact_exchanges is None:
        span = max(1, int(exchanges * 0.8))
        fact_exchanges = [round(i * span / max(1, len(facts))) for i in range(len(facts))]
    if len(fact_exchanges) != len(facts):
        raise ValueError("fact_exchanges must have one entry per fact")
    planted = {ex: fact for ex, fact in zip(fact_exchanges, facts)}
    if len(planted) != len(facts):
        raise ValueError("two facts planted in the same exchange")

    turns: list[Turn] = []
    positions: dict[str, int] = {}
    for ex in range(exchanges):
        fact = planted.get(ex)
        if fact:
            positions[fact.key] = len(turns)
        turns.append(_user_turn(rng, fact))
        turns.append(_assistant_turn(rng, assistant_sentences))
    return Scenario(turns=turns, facts=facts, positions=positions)


# ─── Scoring ─────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[\"'`*_]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_correct(answer: str, fact: PlantedFact) -> bool:
    """Whether `answer` contains one of the fact's accepted answers."""
    got = _normalize(answer)
    return any(_normalize(a) in got for a in fact.answers)
