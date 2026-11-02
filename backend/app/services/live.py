"""Runs that outlive the socket that started them.

A chat turn or a debate is a task the server owns, not the browser tab: a
reload, a dropped socket or a second tab doesn't stop it, and any socket for
the same thread (or debate session) can attach to it. The only things that
end a run early are an explicit stop (from any tab), a CLI or MCP caller
cancelling its own call, and the server shutting down.

A ``RunRegistry`` keeps, per key (a thread id for chat, a session id for
debates):
- the live runs, each with what it has emitted so far (its ``RunState``),
  so an attaching socket gets one coalesced frame per run instead of a replay
  of every token;
- the watchers: whoever wants the key's frames, for the runs live now and
  the ones started later.

Delivering to a watcher is a plain call that must not block (the
connections put frames on their own outbound queue), so a slow or vanished
socket never holds up a model run. Buffers die with their run; after it
ends, the checkpoints are the record.

Spend stays bounded without a socket: a chat run is one call per model, and
a debate stops at MAX_ROUNDS.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from app.services.debate import DebateControl

log = logging.getLogger(__name__)

Frame = dict[str, Any]
Deliver = Callable[[Frame], None]


class RunState(Protocol):
    """What a run has emitted, kept so a socket that attaches mid-run can
    catch up with one frame."""

    def record(self, frame: Frame) -> None: ...

    def resume(self) -> Optional[Frame]:
        """The frame that brings an attaching client up to date, or None
        when there is nothing left to show (the run has said its last)."""
        ...


class LiveRun:
    """One task the registry owns, and its state."""

    def __init__(self, registry: "RunRegistry", key: str, state: RunState):
        self.registry = registry
        self.key = key
        self.state = state
        self.task: Optional[asyncio.Task] = None

    def emit(self, frame: Frame) -> None:
        """Record the frame, then deliver it to every watcher of the key."""
        self.state.record(frame)
        self.registry.publish(self.key, frame)

    @property
    def done(self) -> bool:
        return self.task is None or self.task.done()


class RunRegistry:
    """Live runs and their watchers, by key. One per kind of run (chat turns
    by thread, debates by session), created at app startup."""

    def __init__(self) -> None:
        self._runs: dict[str, list[LiveRun]] = {}
        self._watchers: dict[str, list[Deliver]] = {}

    # ─── watching ────────────────────────────────────────────────
    def watch(self, key: str, deliver: Deliver) -> list[LiveRun]:
        """Deliver the key's frames from now on. ``deliver`` first gets the
        resume frame of every live run; nothing is awaited between those and
        the subscription, so no frame is lost or doubled. Returns the live
        runs."""
        live = self.live(key)
        for run in live:
            frame = run.state.resume()
            if frame is not None:
                deliver(frame)
        self._watchers.setdefault(key, []).append(deliver)
        return live

    def unwatch(self, key: str, deliver: Deliver) -> None:
        watchers = self._watchers.get(key, [])
        if deliver in watchers:
            watchers.remove(deliver)
        if not watchers:
            self._watchers.pop(key, None)

    def publish(self, key: str, frame: Frame) -> None:
        for deliver in list(self._watchers.get(key, ())):
            try:
                deliver(frame)
            except Exception:
                log.exception("[Runs] a watcher failed; dropping it")
                self.unwatch(key, deliver)

    # ─── runs ────────────────────────────────────────────────────
    def start(self, key: str, state: RunState, body: Callable[[LiveRun], Awaitable[None]]) -> LiveRun:
        """Run ``body(run)`` as a task the registry owns. The task inherits
        the caller's context (its storage)."""
        run = LiveRun(self, key, state)
        self._runs.setdefault(key, []).append(run)
        run.task = asyncio.create_task(self._own(run, body))
        return run

    async def _own(self, run: LiveRun, body: Callable[[LiveRun], Awaitable[None]]) -> None:
        try:
            await body(run)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(f"[Runs] run on {run.key} failed")
        finally:
            runs = self._runs.get(run.key, [])
            if run in runs:
                runs.remove(run)
            if not runs:
                self._runs.pop(run.key, None)

    def live(self, key: str) -> list[LiveRun]:
        return [run for run in self._runs.get(key, ()) if not run.done]

    async def cancel(self, key: str, runs: Optional[list[LiveRun]] = None) -> int:
        """Cancel the key's live runs (or just ``runs``) and wait until each
        has finished its own cleanup; returns how many were running."""
        targets = [run for run in (runs if runs is not None else self.live(key)) if not run.done]
        for run in targets:
            run.task.cancel()
        await asyncio.gather(*(run.task for run in targets), return_exceptions=True)
        return len(targets)

    async def close(self) -> None:
        """Server shutdown: stop every run, letting each settle what it
        stored (a debate records that it was interrupted)."""
        for key in list(self._runs):
            await self.cancel(key)


@dataclass
class LiveRuns:
    """The app's registries, on ``app.state.runs``."""

    chat: RunRegistry = field(default_factory=RunRegistry)
    debates: RunRegistry = field(default_factory=RunRegistry)

    async def close(self) -> None:
        await self.chat.close()
        await self.debates.close()


# ─── What a chat run keeps ───────────────────────────────────────────────────


@dataclass
class ChatTurn:
    """The models one burst of frames asked, in the order asked; shared by
    the turn's runs."""

    turn_id: str
    models: list[str] = field(default_factory=list)
    named: bool = False


class ChatRunState:
    """One model's reply in a chat turn: who, where it forked, and the text
    so far. Resumes as ``stream_resume``."""

    def __init__(self, turn: ChatTurn, model: str, where: Frame, *, message: Optional[str], kind: Optional[str]):
        self.turn = turn
        self.model = model
        self.where = where
        self.message = message
        self.kind = kind
        self.model_color: Optional[str] = None
        self.started = False
        self.ended = False
        self.content = ""

    def record(self, frame: Frame) -> None:
        kind = frame.get("type")
        if frame.get("model") != self.model:
            return
        if kind == "stream_start":
            self.started = True
            self.model_color = frame.get("model_color")
        elif kind == "stream_token":
            self.content += frame.get("token", "")
        elif kind in ("stream_end", "error", "stream_stopped"):
            self.ended = True

    def resume(self) -> Optional[Frame]:
        if not self.started or self.ended:
            return None
        return {
            "type": "stream_resume",
            **self.where,
            "model_color": self.model_color,
            "content_so_far": self.content,
            "message": self.message,
            "kind": self.kind,
            "turn_models": list(self.turn.models),
        }


# ─── What a debate run keeps ─────────────────────────────────────────────────


class DebateRunState:
    """A debate run's live controls and where it stands: the round in
    progress with each participant's answer so far, the synthesis being
    written, the status. Resumes as ``debate_resume``; earlier rounds are
    the transcript's to tell."""

    def __init__(self, session_id: str, control: Optional[DebateControl] = None):
        self.session_id = session_id
        # Per run, not per socket: pause, resume and inject from any tab
        # reach the same object.
        self.control = control or DebateControl()
        self.status = "running"
        self.round: Optional[int] = None
        self.question: Optional[str] = None
        self.answers: dict[str, dict[str, Any]] = {}
        self.synthesis: Optional[dict[str, Any]] = None
        self.convergence_score: Optional[float] = None

    def record(self, frame: Frame) -> None:
        kind = frame.get("type")
        model = frame.get("model")
        if kind == "debate_session_created":
            self.question = frame.get("question", self.question)
        elif kind == "debate_session_status" and frame.get("status") in ("running", "paused", "completed"):
            self.status = frame["status"]
        elif kind == "debate_round_start":
            self.round = frame.get("round", 0)
            self.answers = {}
        elif kind == "stream_start" and model:
            self.answers[model] = {"model": model, "content": "", "done": False}
        elif kind == "stream_token" and model:
            if self.synthesis is not None and not self.synthesis["done"] and self.synthesis["model"] == model:
                self.synthesis["content"] += frame.get("token", "")
            elif model in self.answers:
                self.answers[model]["content"] += frame.get("token", "")
        elif kind == "stream_end" and model:
            self.answers[model] = {
                "model": model, "content": frame.get("content") or self.answers.get(model, {}).get("content", ""),
                "done": True, "checkpoint_id": frame.get("checkpoint_id") or None,
            }
        elif kind == "error" and model:
            self.answers[model] = {
                **self.answers.get(model, {"model": model, "content": ""}), "done": True, "error": frame.get("message"),
            }
        elif kind == "debate_round_end" and frame.get("convergence_score") is not None:
            self.convergence_score = frame["convergence_score"]
        elif kind == "debate_synthesis_start":
            self.synthesis = {"model": model, "content": "", "done": False}
        elif kind == "debate_synthesis_end":
            self.synthesis = {"model": model, "content": frame.get("content") or "", "done": True,
                              "error": frame.get("error")}

    def resume(self) -> Frame:
        status = self.status
        if status == "running" and self.control.paused:
            status = "pausing"
        return {
            "type": "debate_resume",
            "session_id": self.session_id,
            "status": status,
            "round": self.round,
            "question": self.question,
            "answers": list(self.answers.values()),
            "synthesis": self.synthesis,
            "convergence_score": self.convergence_score,
        }
