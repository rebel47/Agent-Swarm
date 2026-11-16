"""Scripted providers exist only in the explicitly configured test suite."""

from collections import deque
import json

from app.llm import Reply


class ScriptedProvider:
    def __init__(self, decisions=(), turns=()):
        self.decisions = deque(decisions)
        self.turns = deque(turns)
        self.calls = []
        self.last_decision = None
        self.models_used = []
        self.counts = []

    async def count_input_tokens(self, messages, tools, model, purpose, choice="required"):
        self.counts.append((messages, tools, model, purpose, choice))
        # Test-only tokenizer approximation. Production always uses the OpenAI endpoint.
        return len(json.dumps([messages, tools], ensure_ascii=False).encode()) // 4 + 128

    async def decide(self, messages, model):
        self.calls.append(("supervisor", messages))
        self.models_used.append(model)
        value = self.decisions.popleft()
        if isinstance(value, Exception):
            raise value
        self.last_decision = value
        return Reply(value, 100, 50)

    async def act(self, messages, tools, model, purpose="routine"):
        self.calls.append(("agent", messages))
        self.models_used.append(model)
        value = self.turns.popleft()
        if isinstance(value, Exception):
            raise value
        return Reply(value, 100, 50)

    async def structured(self, messages, schema, model, purpose):
        self.calls.append((purpose, messages))
        self.models_used.append(model)
        if purpose == "synthesis":
            return Reply(self.last_decision.report, 100, 50)
        return Reply(
            schema(summary="Persisted tool observations summarized", evidence_references=["app.py:2"]),
            100,
            50,
        )
