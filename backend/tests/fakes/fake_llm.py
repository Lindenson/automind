"""Scripted fake LLM implementing the application `LLM` port (constitution IX).

Outputs are queued per role. `structured` validates the queued dict against the requested schema,
so cassettes are checked like real model output. An empty queue raises, so a test never silently
gets a default answer. Each call is charged to the current TurnBudget like a real model.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from automind.shared.metering.usage import current_budget

T = TypeVar("T", bound=BaseModel)


class ScriptExhausted(AssertionError):
    pass


@dataclass
class Call:
    role: str
    kind: str
    system: str
    user: str


@dataclass
class FakeLLM:
    queues: dict[str, deque[Any]] = field(default_factory=lambda: defaultdict(deque))
    responders: dict[str, Any] = field(default_factory=dict)  # role -> fn(system, user) when no queued output
    calls: list[Call] = field(default_factory=list)
    tokens_per_call: tuple[int, int] = (1000, 100)
    model: str = "fake:model"

    def queue(self, role: str, *outputs: Any) -> FakeLLM:
        self.queues[role].extend(outputs)
        return self

    def _next(self, role: str, kind: str, system: str, user: str) -> Any:
        b = current_budget.get()
        if b is not None:
            b.before_llm_call(role)
        self.calls.append(Call(role, kind, system, user))
        if self.queues[role]:
            out = self.queues[role].popleft()
        elif role in self.responders:
            out = self.responders[role](system, user)
        else:
            raise ScriptExhausted(f"no scripted {kind} output left for role {role!r}")
        if b is not None:
            b.after_llm_call(self.model, *self.tokens_per_call)
        if isinstance(out, BaseException):
            raise out
        return out

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        out = self._next(role, "structured", system, user)
        return out if isinstance(out, schema) else schema.model_validate(out)

    async def text(self, role: str, system: str, user: str) -> str:
        return str(self._next(role, "text", system, user))

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> FakeAgent:
        return FakeAgent(self, role, tools, system_prompt)

    def roles_called(self) -> list[str]:
        return [c.role for c in self.calls]


@dataclass
class FakeAgent:
    """`create_agent`-compatible fake: optionally calls scripted tools, then returns a scripted answer.

    Queue for the role either a string (final answer) or {"tool_calls": [{"name", "args"}], "answer": str}.
    """

    llm: FakeLLM
    role: str
    tools: list[Any]
    system_prompt: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    async def ainvoke(self, inputs: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        user = str(inputs.get("messages", [("user", "")])[-1][1])
        script = self.llm._next(self.role, "agent", self.system_prompt, user)
        messages: list[Any] = []
        if isinstance(script, dict):
            by_name = {getattr(t, "name", ""): t for t in self.tools}
            for tc in script.get("tool_calls", []):
                if tc["name"] not in by_name:
                    raise AssertionError(f"agent {self.role} called tool {tc['name']!r} outside its scope")
                result = await by_name[tc["name"]].ainvoke(tc.get("args", {}))
                self.tool_calls.append({"name": tc["name"], "args": tc.get("args", {}), "result": result})
                messages.append(_Msg("tool", result))
            answer = script.get("answer", "")
        else:
            answer = str(script)
        messages.append(_Msg("ai", answer))
        return {"messages": messages}


@dataclass
class _Msg:
    type: str
    content: Any

    @property
    def text(self) -> str:
        return self.content if isinstance(self.content, str) else str(self.content)


@dataclass
class FixedEstimator:
    """Research cost estimate for tests: a fixed € per job and per follow-up round share."""

    eur_per_job: float = 0.01

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float:
        return round(len(jobs) * self.eur_per_job * (1 + 0.5 * rounds), 4)
