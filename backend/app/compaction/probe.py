"""Detail-retention scenarios: does a specific fact survive compaction?

A scenario is a long, deterministic conversation with facts planted at chosen
turns, buried mid-message (summaries tend to keep openings), surrounded by
plausible filler. After the conversation, each fact is probed with a
question whose answer can be checked by string match.

Facts are fictional so a model can't answer from prior knowledge, and they
cover the kinds of detail summaries tend to drop: numbers, names, identifiers,
dates, exact wording, and negations ("we agreed NOT to ...").

Two designs:

- build_scenario(): generic filler around a few hand-written facts. The facts
  are the only specific content, so any competent summary keeps them (pilot 1
  hit a ceiling this way).
- build_dense_scenario(): every turn carries specifics of the same shape as
  the facts, facts come in variants (plain, a rejected proposal nearby, or a
  value that is later updated), and the answer that must *not* be given is
  recorded as `stale`.
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
    # Values that were true earlier or proposed and rejected: an answer that
    # contains one of them is wrong even if it also contains the right value.
    stale: tuple[str, ...] = ()
    # "plain", "distractor" (a rejected proposal is planted too) or "update"
    # (an older value is planted before `statement`).
    variant: str = "plain"
    # Statements planted at other turns: the superseded value (before
    # `statement`) or the rejected proposal (anywhere).
    extras: tuple[str, ...] = ()


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
    # fact key -> indexes into `turns` of its extra statements
    extra_positions: dict[str, list[int]] = field(default_factory=dict)

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


# ─── Dense scenarios ─────────────────────────────────────────────
#
# Facts and filler are built from the same kind of material: every turn states
# specifics about some subsystem, so a summary has to choose what to keep. Fact
# attributes (budget cap, reviewer, key label, port, freeze date, avoided
# technology, client quote, vendor) never appear in filler, and filler values
# come from disjoint pools, so a probe has exactly one right answer and the
# availability oracle can't be fooled by a filler value.

_SUBJECTS = [
    "ingest pipeline", "audit service", "billing export", "search indexer", "notification gateway",
    "report scheduler", "image resizer", "session store", "feature-flag service", "payment webhook",
    "geo lookup", "fraud scorer", "email relay", "metrics collector", "backup job", "sync worker",
    "partner API", "admin console", "rate limiter", "document store", "chat widget", "invoice renderer",
    "ledger service", "tax calculator", "shipping quote service", "inventory cache", "recommendation model",
    "support portal", "SSO bridge", "log shipper", "CDN purge job", "warehouse loader", "experiment runner",
    "translation service", "PDF exporter", "webhook dispatcher", "config service", "license checker",
    "push service", "status page",
]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_FACT_FIRST = ["Ilse", "Tomasz", "Priya", "Joaquin", "Maren", "Oluwaseun", "Keiko", "Anders",
               "Beatriz", "Dmitri", "Aoife", "Rafael", "Sunniva", "Kwame", "Liesel", "Matteo"]
_FACT_LAST = ["Marchetti", "Vasquez-Lind", "Okonkwo", "Halvorsen", "Draganova", "Achterberg",
              "Quintero", "Nakashima", "Villeneuve", "Oyelaran", "Brandstetter", "Castellano",
              "Lindqvist", "Szczepanik", "Moravec", "Iturbide", "Fairweather", "Takahara"]
_FILLER_NAMES = ["Nora Pike", "Ravi Sethi", "Lena Ostrova", "Ben Adeyemi", "Clara Wu", "Hugo Brandt",
                 "Mei Tanaka", "Omar Haddad", "Sara Lindgren", "Tariq Aziz", "Julia Fern", "Pavel Novak"]
_KEY_WORDS = ["ORCHID", "JUNIPER", "BASALT", "HERON", "COBALT", "SPRUCE", "MARLIN", "QUARTZ",
              "PELICAN", "SAFFRON", "GRANITE", "TUNDRA", "ZEPHYR", "LOTUS", "OBSIDIAN", "CONDOR"]
_AVOIDED_TECH = ["Kafka", "RabbitMQ", "MongoDB", "GraphQL", "Kubernetes", "Terraform", "Cassandra",
                 "Elasticsearch", "Redis Streams", "gRPC", "DynamoDB", "Airflow"]
_FILLER_TECH = ["Postgres", "SQLite", "nginx", "Celery", "Prometheus", "Grafana", "OpenTelemetry", "Vault"]
_PRIORITIES = ["latency", "features", "reliability", "cost", "polish", "security", "accuracy",
               "coverage", "speed", "simplicity"]
_VENDORS = ["Northwind", "Contoso", "Fabrikam", "Tailspin", "Litware", "Adatum", "Proseware",
            "Wingtip", "Woodgrove", "Lucerne", "Coho", "Margie"]


def _money(n: int) -> tuple[str, ...]:
    return (f"{n:,}", str(n), f"{n:,}".replace(",", " "))


def _date(day: int, month: str) -> tuple[str, ...]:
    m = month.lower()
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return (f"{day} {m}", f"{m} {day}", f"{day}{suffix} of {m}", f"{m} {day}{suffix}", f"{day}{suffix} {m}")


def _key(word: str, digit: int) -> tuple[str, ...]:
    return (f"{word}-{digit}".lower(), f"{word} {digit}".lower(), f"{word}{digit}".lower())


class _Values:
    """Draws fact values without repeats and remembers every accepted string."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def _take(self, make):
        for _ in range(200):
            value, strings = make()
            normalized = {_normalize(x) for x in strings}
            if not any(a in b or b in a for a in normalized for b in self.used):
                self.used |= normalized
                return value, strings
        raise RuntimeError("value pool exhausted")

    def money(self):
        return self._take(lambda: (n := self.rng.randrange(12, 98) * 1000 + self.rng.randrange(1, 10) * 100, _money(n)))

    def person(self):
        return self._take(lambda: (
            (f := self.rng.choice(_FACT_FIRST), last := self.rng.choice(_FACT_LAST)) and f"{f} {last}",
            (last,),
        ))

    def key(self):
        return self._take(lambda: (
            (w := self.rng.choice(_KEY_WORDS), d := self.rng.randrange(2, 10)) and f"{w}-{d}", _key(w, d)
        ))

    def port(self):
        return self._take(lambda: (p := self.rng.randrange(5000, 9900), (str(p),)))

    def date(self):
        return self._take(lambda: (
            (d := self.rng.randrange(1, 29), m := self.rng.choice(_MONTHS)) and f"{d} {m}", _date(d, m)
        ))

    def pick(self, pool):
        return self._take(lambda: (v := self.rng.choice(pool), (v.lower(),)))


def _fact(kind: str, variant: str, subject: str, key: str, v: _Values) -> PlantedFact:
    """One fact of `kind` about `subject`; see PlantedFact for the variants."""
    s = f"the {subject}"
    extras: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()

    if kind == "number":
        question = f"What is the budget cap for {s}, in euros?"
        state = lambda x: f"The budget for {s} is capped at {x} euros."  # noqa: E731
        update = lambda x: f"Update on {s}: its budget cap was revised to {x} euros."  # noqa: E731
        reject = lambda x: f"Someone proposed capping the budget for {s} at {x} euros, but that was turned down."  # noqa: E731
        draw = lambda: (lambda n, a: (f"{n:,}", a))(*v.money())  # noqa: E731
    elif kind == "name":
        question = f"Who is the on-call reviewer for {s}?"
        state = lambda x: f"The on-call reviewer for {s} is {x}."  # noqa: E731
        update = lambda x: f"Update on {s}: {x} has taken over as its on-call reviewer."  # noqa: E731
        reject = lambda x: f"{x} offered to be the on-call reviewer for {s}, but we decided against it."  # noqa: E731
        draw = v.person
    elif kind == "identifier":
        question = f"Which key label must exports from {s} be encrypted with?"
        state = lambda x: f"Exports from {s} must be encrypted with the key labelled {x}."  # noqa: E731
        update = lambda x: f"Update on {s}: its exports now use the key labelled {x}."  # noqa: E731
        reject = lambda x: f"The key labelled {x} was suggested for exports from {s}, but it was rejected."  # noqa: E731
        draw = v.key
    elif kind == "port":
        question = f"Which port does {s} listen on?"
        state = lambda x: f"{s[0].upper() + s[1:]} listens on port {x}."  # noqa: E731
        update = lambda x: f"Update on {s}: it has moved to port {x}."  # noqa: E731
        reject = lambda x: f"Port {x} was considered for {s}, but it was already taken."  # noqa: E731
        draw = v.port
    elif kind == "date":
        question = f"On what date does the migration freeze for {s} start?"
        state = lambda x: f"The migration freeze for {s} starts on {x}."  # noqa: E731
        update = lambda x: f"Update on {s}: its migration freeze now starts on {x}."  # noqa: E731
        reject = lambda x: f"A freeze start of {x} was floated for {s}, but nobody agreed to it."  # noqa: E731
        draw = v.date
    elif kind == "negation":
        tech, answers = v.pick(_AVOIDED_TECH)
        return PlantedFact(key, kind, f"We agreed not to use {tech} for {s}.",
                           f"Which technology did we agree not to use for {s}?", answers)
    elif kind == "quote":
        a, b = v.rng.sample(_PRIORITIES, 2)
        quote = f"{a} first, {b} second"
        v.used.add(_normalize(quote))
        return PlantedFact(key, kind, f"The client's exact words about {s} were '{quote}'.",
                           f"What were the client's exact words about {s}?", (quote, quote.replace(",", "")))
    elif kind == "choice":
        (chosen, answers), (r1, s1), (r2, s2) = v.pick(_VENDORS), v.pick(_VENDORS), v.pick(_VENDORS)
        question = f"Which vendor did we pick for {s}?"
        stale = s1 + s2
        if variant == "update":
            (new, new_answers) = v.pick(_VENDORS)
            return PlantedFact(key, kind, f"Update on {s}: we switched its vendor to {new}.", question, new_answers,
                               stale=answers + stale, variant=variant,
                               extras=(f"For {s} we picked {chosen} over {r1} and {r2}.",))
        if variant == "distractor":
            (late, late_answers) = v.pick(_VENDORS)
            extras, stale = (f"{late} also pitched for {s} late, but was not considered.",), stale + late_answers
        return PlantedFact(key, kind, f"For {s} we picked {chosen} over {r1} and {r2}.", question, answers,
                           stale=stale, variant=variant, extras=extras)
    else:
        raise ValueError(f"unknown fact kind {kind!r}")

    value, answers = draw()
    if variant == "update":
        old, old_answers = draw()
        return PlantedFact(key, kind, update(value), question, answers, stale=old_answers,
                           variant=variant, extras=(state(old),))
    if variant == "distractor":
        other, other_answers = draw()
        return PlantedFact(key, kind, state(value), question, answers, stale=other_answers,
                           variant=variant, extras=(reject(other),))
    return PlantedFact(key, kind, state(value), question, answers)


FACT_KINDS = ("number", "name", "identifier", "negation", "date", "port", "quote", "choice")
VARIANT_KINDS = {"number", "name", "identifier", "date", "port", "choice"}
VARIANTS = ("plain", "distractor", "update")


def generate_facts(n: int = 24, *, seed: int = 0, variants: Sequence[str] = VARIANTS) -> list[PlantedFact]:
    """`n` facts cycling through FACT_KINDS; each round of kinds uses the next
    variant (kinds that can't vary, negation and quote, stay plain)."""
    rng = random.Random(f"facts:{seed}")
    if n > len(_SUBJECTS):
        raise ValueError(f"at most {len(_SUBJECTS)} facts")
    subjects = rng.sample(_SUBJECTS, n)
    values = _Values(rng)
    facts = []
    for i, subject in enumerate(subjects):
        kind = FACT_KINDS[i % len(FACT_KINDS)]
        variant = variants[(i // len(FACT_KINDS)) % len(variants)] if kind in VARIANT_KINDS else "plain"
        facts.append(_fact(kind, variant, subject, f"{kind}-{subject.replace(' ', '-')}", values))
    return facts


def _filler_fact(rng: random.Random, subject: str) -> str:
    s = f"the {subject}"
    return rng.choice([
        lambda: f"The p95 latency of {s} is {rng.randrange(40, 900)} ms.",
        lambda: f"There are {rng.randrange(3, 80)} open tickets against {s}.",
        lambda: f"{s[0].upper() + s[1:]} was last deployed by {rng.choice(_FILLER_NAMES)}.",
        lambda: f"The error rate of {s} is {rng.randrange(1, 50) / 10}%.",
        lambda: f"{s[0].upper() + s[1:]} runs release {rng.randrange(1, 9)}.{rng.randrange(0, 30)}.{rng.randrange(0, 10)}.",
        lambda: f"The dashboard for {s} is maintained by {rng.choice(_FILLER_NAMES)}.",
        lambda: f"{s[0].upper() + s[1:]} handles about {rng.randrange(2, 90)} thousand requests an hour.",
        lambda: f"{s[0].upper() + s[1:]} stores its state in {rng.choice(_FILLER_TECH)}.",
        lambda: f"{s[0].upper() + s[1:]} has {rng.randrange(2, 40)} alerts configured.",
    ])()


_DENSE_ADVICE = [
    "I'd time-box the investigation and write down what done looks like first.",
    "It is worth measuring the current state before changing anything.",
    "A single owner usually helps more than new tooling.",
    "Start with the smallest reversible change and expand if it holds up.",
    "Keep the interface stable and iterate behind it.",
    "A short pilot with one team will surface most of the problems.",
    "Record the trade-off briefly so the rationale survives.",
    "A weekly metric with an alert threshold is usually enough to catch drift.",
]


def build_dense_scenario(
    facts: Optional[Sequence[PlantedFact]] = None,
    *,
    n_facts: int = 24,
    exchanges: int = 120,
    seed: int = 0,
) -> Scenario:
    """A long conversation where every turn carries specifics.

    Facts are planted in order over 8%–88% of the conversation (so the last few
    sit in the verbatim tail and the first ones pass through every summary). An
    update's older value goes somewhere before it; a rejected proposal
    somewhere near it. One planted statement per user turn at most.
    """
    rng = random.Random(seed)
    facts = list(facts) if facts is not None else generate_facts(n_facts, seed=seed)
    start, end = int(exchanges * 0.08), int(exchanges * 0.88)
    if sum(1 + len(f.extras) for f in facts) > exchanges:
        raise ValueError("more planted statements than exchanges")
    finals = [start + round(i * (end - start) / max(1, len(facts) - 1)) for i in range(len(facts))] if len(facts) > 1 else [start]
    slots: dict[int, tuple[PlantedFact, str, bool]] = {ex: (f, f.statement, True) for ex, f in zip(finals, facts)}
    if len(slots) != len(facts):
        raise ValueError("too many facts for this many exchanges")
    for fact, final in zip(facts, finals):
        for extra in fact.extras:
            if fact.variant == "update":
                window = range(max(0, final - 30), max(0, final - 3))
            else:
                window = range(max(0, final - 15), min(exchanges, final + 16))
            free = [ex for ex in window if ex not in slots] or [ex for ex in range(exchanges) if ex not in slots and
                                                                 (fact.variant != "update" or ex < final)]
            if not free:
                raise ValueError(f"no free exchange for an extra statement of {fact.key}")
            slots[rng.choice(free)] = (fact, extra, False)

    turns: list[Turn] = []
    positions: dict[str, int] = {}
    extra_positions: dict[str, list[int]] = {}
    for ex in range(exchanges):
        subject = rng.choice(_SUBJECTS)
        parts = [rng.choice(_OPENERS).format(t=f"the {subject}"), _filler_fact(rng, subject)]
        planted = slots.get(ex)
        if planted:
            fact, statement, is_final = planted
            (positions.__setitem__(fact.key, len(turns)) if is_final
             else extra_positions.setdefault(fact.key, []).append(len(turns)))
            parts.append(statement)
        parts += [_filler_fact(rng, rng.choice(_SUBJECTS)), rng.choice(_USER_BODY), _filler_fact(rng, subject)]
        turns.append(Turn("user", " ".join(parts), planted[0].key if planted else None))
        reply = [_filler_fact(rng, rng.choice(_SUBJECTS)) for _ in range(3)] + rng.sample(_DENSE_ADVICE, 3)
        rng.shuffle(reply)
        turns.append(Turn("assistant", " ".join(reply)))
    return Scenario(turns=turns, facts=facts, positions=positions, extra_positions=extra_positions)


# ─── Scoring ─────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[\"'`*_]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def committed_answer(answer: str) -> str:
    """The value a reply commits to: its first non-empty line, tags removed.

    Models often answer and then quote the source ("Litware. This was stated
    as: '...picked Litware over Margie and Contoso'"). Scoring the whole reply
    would count the quoted rejected vendors as a stale answer; a reply that
    lists two candidates without choosing commits to neither.
    """
    for line in re.sub(r"<[^>]*>", "\n", answer).splitlines():
        if line.strip():
            return line
    return ""


def is_correct(answer: str, fact: PlantedFact) -> bool:
    """Whether the committed answer has an accepted value and no stale one."""
    got = _normalize(committed_answer(answer))
    return any(_normalize(a) in got for a in fact.answers) and not is_stale(answer, fact)


def is_stale(answer: str, fact: PlantedFact) -> bool:
    """Whether the committed answer gives a superseded or rejected value."""
    got = _normalize(committed_answer(answer))
    return any(_normalize(a) in got for a in fact.stale)
