"""Transactional state machine. All job mutations take the same PostgreSQL row lock."""

import hashlib
import asyncio
import json
import time

from sqlalchemy import func, select, text

from ..config import Settings
from ..llm import Reply
from ..database import Database
from ..models import (
    Agent,
    Artifact,
    Budget,
    Dependency,
    Event,
    Inference,
    Job,
    RepositorySource,
    Task,
    ToolExecution,
    User,
    WorkerHeartbeat,
    uid,
)
from ..observability import sanitize
from ..schemas import ACTIVE, TERMINAL, AgentSpec, JobRequest, JobView, RepositoryView
from ..repositories import RepositoryError, normalize_source, remove_snapshot, snapshot_path
from ..tools import READ_TOOLS
from ..domain.budgets import BudgetAccount, InferenceCharge, usage_cost
from ..domain.errors import AgentBudgetExhausted, BudgetExhausted, Rejected
from ..domain.investigations import AgentAllowance, Claim


class Store:
    def __init__(self, database: Database, settings: Settings):
        self.db, self.settings = database, settings

    @staticmethod
    def repository_view(source):
        return RepositoryView.model_validate(source, from_attributes=True).model_dump()

    async def repository_sources(self, owner):
        async with self.db.sessions() as session:
            records = await session.scalars(
                select(RepositorySource)
                .where(RepositorySource.owner_id == owner, RepositorySource.status != "DELETED")
                .order_by((RepositorySource.status == "READY").desc(), RepositorySource.created_at.desc())
                .limit(self.settings.max_repository_snapshots + 100)
            )
            return [self.repository_view(source) for source in records]

    async def admit_repository(self, request, owner):
        source = normalize_source(request.location, request.ref, self.settings)
        await self.db.ensure_user(owner)
        stale = []
        async with self.db.sessions.begin() as session:
            await session.scalar(select(User).where(User.id == owner).with_for_update())
            if self.db.engine.dialect.name == "postgresql":
                await session.execute(text("SELECT pg_advisory_xact_lock(4815162343)"))
            expired = list(
                await session.scalars(
                    select(RepositorySource).where(
                        RepositorySource.status == "PREPARING",
                        RepositorySource.created_at
                        < time.time() - self.settings.repository_prepare_seconds - 60,
                    )
                )
            )
            for record in expired:
                record.status = "FAILED"
                record.error = {
                    "code": "preparation_interrupted",
                    "message": "Preparation was interrupted; import the repository again",
                }
                stale.append(record.id)
            await session.flush()
            count = await session.scalar(
                select(func.count())
                .select_from(RepositorySource)
                .where(
                    RepositorySource.owner_id == owner, RepositorySource.status.in_(["PREPARING", "READY"])
                )
            )
            pending = await session.scalar(
                select(func.count())
                .select_from(RepositorySource)
                .where(RepositorySource.status == "PREPARING")
            )
            if count >= self.settings.max_repository_snapshots:
                raise RepositoryError(
                    "Saved repository capacity reached; remove an unused snapshot", "repository_capacity", 409
                )
            if pending >= self.settings.max_repository_preparations:
                raise RepositoryError(
                    "Repository preparation capacity reached; try again shortly", "repository_capacity", 409
                )
            record = RepositorySource(id=uid(), owner_id=owner, **source)
            session.add(record)
            await session.flush()
            result = self.repository_view(record)
        for source_id in stale:
            for suffix in (".partial", ".git-work", ""):
                await asyncio.to_thread(remove_snapshot, self.settings, source_id, suffix)
        return result

    async def finish_repository(self, source_id, info=None, error=None):
        async with self.db.sessions.begin() as session:
            record = await session.get(RepositorySource, source_id, with_for_update=True)
            if record.status != "PREPARING":
                raise RepositoryError("Preparation is no longer active", "repository_conflict", 409)
            if error:
                record.status, record.error = "FAILED", error
            else:
                record.status = "READY"
                record.revision, record.file_count, record.size_bytes = (
                    info["revision"],
                    info["file_count"],
                    info["size_bytes"],
                )
            await session.flush()
            return self.repository_view(record)

    async def delete_repository(self, source_id, owner):
        async with self.db.sessions.begin() as session:
            await session.scalar(select(User).where(User.id == owner).with_for_update())
            record = await session.get(RepositorySource, source_id, with_for_update=True)
            if not record or record.owner_id != owner or record.status == "DELETED":
                raise LookupError("Repository not found")
            active = await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.workspace_id == source_id, Job.status == "RUNNING")
            )
            if active or record.status == "PREPARING":
                raise RepositoryError(
                    "This snapshot is preparing or in use by a running investigation",
                    "repository_in_use",
                    409,
                )
            record.status = "DELETING"
        for suffix in ("", ".partial", ".git-work"):
            await asyncio.to_thread(remove_snapshot, self.settings, source_id, suffix)
        async with self.db.sessions.begin() as session:
            record = await session.get(RepositorySource, source_id)
            record.status = "DELETED"

    async def repository_root(self, workspace_id):
        if workspace_id in self.settings.workspaces:
            return self.settings.workspaces[workspace_id]
        async with self.db.sessions() as session:
            record = await session.get(RepositorySource, workspace_id)
            if not record or record.status != "READY":
                raise Rejected("Repository snapshot is not available")
        path = snapshot_path(self.settings, workspace_id)
        if not path.is_dir():
            raise Rejected("Repository snapshot storage is unavailable")
        return str(path)

    def event(self, session, job, kind, data=None, agent_id=None):
        job.updated_at = time.time()
        session.add(
            Event(
                job_id=job.id,
                agent_id=agent_id,
                type=kind,
                data=sanitize(data or {}),
            )
        )

    def transition(self, session, job, agent, status, data=None):
        before = agent.status
        agent.status = status
        if status in TERMINAL:
            agent.ended_at = time.time()
            agent.lease_owner = None
            agent.lease_until = None
        self.event(session, job, "agent.status", {"from": before, "status": status, **(data or {})}, agent.id)

    async def create_job(self, request: JobRequest, owner: str, idempotency_key: str | None = None):
        request = request.model_copy(update={"objective": sanitize(request.objective)})
        allocation = {**self.settings.model_allocation, **request.model_overrides}
        allocation.update(complex=allocation["orchestrator"], summary=allocation["routine"])
        for purpose, model in allocation.items():
            self.settings.policy(model)
            if (
                self.settings.effort(purpose)
                and self.settings.effort(purpose) not in self.settings.policy(model).reasoning_efforts
            ):
                raise Rejected(f"Unsupported reasoning effort for {purpose} model {model!r}")
        if idempotency_key and len(idempotency_key) > 200:
            raise Rejected("Idempotency-Key exceeds 200 characters")
        await self.db.ensure_user(owner)
        async with self.db.sessions.begin() as session:
            # Serialize admission and idempotency checks for this tenant.
            await session.scalar(select(User).where(User.id == owner).with_for_update())
            if request.workspace_id not in self.settings.workspaces:
                source = await session.get(RepositorySource, request.workspace_id)
                if not source or source.owner_id != owner or source.status != "READY":
                    raise Rejected("Unknown, unavailable or unauthorized workspace")
            if idempotency_key:
                existing = await session.scalar(
                    select(Job).where(Job.owner_id == owner, Job.idempotency_key == idempotency_key)
                )
                if existing:
                    if (
                        existing.objective != request.objective
                        or existing.workspace_id != request.workspace_id
                        or existing.mode != request.mode
                        or (existing.model_allocation or self.settings.model_allocation) != allocation
                        or existing.allow_patch_proposals != request.allow_patch_proposals
                        or (
                            request.mode == "fixed"
                            and existing.fixed_agent_count
                            != (request.fixed_agent_count or self.settings.fixed_agent_count)
                        )
                    ):
                        raise Rejected("Idempotency-Key was already used for another request")
                    return existing.id
            count = await session.scalar(
                select(func.count()).select_from(Job).where(Job.owner_id == owner, Job.status == "RUNNING")
            )
            if count >= self.settings.max_active_jobs:
                raise Rejected("Active job capacity reached")
            fixed = request.fixed_agent_count or self.settings.fixed_agent_count
            if request.mode == "fixed" and fixed > self.settings.max_total_agents:
                raise Rejected("Fixed team exceeds MAX_TOTAL_AGENTS")
            job = Job(
                id=uid(),
                owner_id=owner,
                **request.model_dump(exclude={"fixed_agent_count", "model_overrides"}),
                model_allocation=allocation,
                fixed_agent_count=fixed,
                idempotency_key=idempotency_key,
            )
            session.add(job)
            await session.flush()
            session.add(
                Budget(
                    job_id=job.id,
                    max_agents=self.settings.max_total_agents,
                    max_concurrency=self.settings.max_concurrent_agents,
                    max_depth=self.settings.max_agent_depth,
                    max_tokens=self.settings.max_total_tokens,
                    max_cost_usd=self.settings.max_total_cost_usd,
                )
            )
            self.event(session, job, "job.created", {"mode": job.mode, "trace_id": job.trace_id})
            return job.id

    async def agents(self, session, job_id):
        return list(
            await session.scalars(
                select(Agent).where(Agent.job_id == job_id).order_by(Agent.created_at, Agent.id)
            )
        )

    async def snapshot(self, job_id: str, owner: str | None = None) -> dict:
        async with self.db.sessions() as session:
            job = await session.get(Job, job_id)
            if not job or (owner is not None and job.owner_id != owner):
                raise LookupError("Job not found")
            agents = await self.agents(session, job_id)
            budget = await session.get(Budget, job_id)
            artifacts = list(
                await session.scalars(
                    select(Artifact).where(Artifact.job_id == job_id, Artifact.kind == "result")
                )
            )
            results = {item.agent_id: item.content for item in artifacts}
            dependencies = list(
                (
                    await session.execute(
                        select(Dependency)
                        .join(Agent, Agent.id == Dependency.agent_id)
                        .where(Agent.job_id == job_id)
                    )
                ).scalars()
            )
            views = []
            inferences = list(await session.scalars(select(Inference).where(Inference.job_id == job_id)))
            for agent in agents:
                spec = agent.spec
                views.append(
                    {
                        "id": agent.id,
                        "task_id": agent.task_id,
                        "parent_agent_id": agent.parent_agent_id,
                        "role": spec["role"],
                        "objective": spec["objective"],
                        "status": agent.status,
                        "depth": agent.depth,
                        "allowed_tools": spec["allowed_tools"],
                        "model": spec["model"],
                        "model_purpose": spec.get("model_purpose", "routine"),
                        "model_reason": spec.get("model_reason", ""),
                        "steps": agent.steps,
                        "tokens": agent.tokens,
                        "cost_usd": agent.cost_usd,
                        "result": results.get(agent.id),
                        "error": agent.error,
                        "dependencies": [d.depends_on_id for d in dependencies if d.agent_id == agent.id],
                        "created_at": agent.created_at,
                        "started_at": agent.started_at,
                        "ended_at": agent.ended_at,
                    }
                )
            return JobView(
                id=job.id,
                objective=job.objective,
                workspace_id=job.workspace_id,
                repository=self.repository_view(source)
                if (source := await session.get(RepositorySource, job.workspace_id))
                else None,
                mode=job.mode,
                status=job.status,
                created_at=job.created_at,
                updated_at=job.updated_at,
                ended_at=job.ended_at,
                report=job.report,
                error=job.error,
                trace_id=job.trace_id,
                supervisor_steps=job.supervisor_steps,
                metrics={
                    "total_agents": budget.agents_created,
                    "tokens": budget.tokens,
                    "estimated_cost_usd": budget.cost_usd,
                    "reserved_tokens": budget.reserved_tokens,
                    "reserved_cost_usd": budget.reserved_cost_usd,
                    "max_concurrency": budget.max_observed_concurrency,
                    "redundant_requests": budget.redundant_requests,
                    "recoveries": budget.recoveries,
                    "cached_input_tokens": sum(i.usage_details.get("cached_tokens", 0) for i in inferences),
                    "cache_write_tokens": sum(
                        i.usage_details.get("cache_write_tokens", 0) for i in inferences
                    ),
                    "reasoning_tokens": sum(i.usage_details.get("reasoning_tokens", 0) for i in inferences),
                    "unknown_usage_calls": sum(i.status == "ESTIMATED_UNKNOWN" for i in inferences),
                    "model_allocation": job.model_allocation or self.settings.model_allocation,
                    "model_costs": {
                        name: sum(i.cost_usd for i in inferences if i.model == name)
                        for name in sorted({i.model for i in inferences})
                    },
                    "limits": {
                        "agents": budget.max_agents,
                        "tokens": budget.max_tokens,
                        "cost_usd": budget.max_cost_usd,
                        "depth": budget.max_depth,
                        "concurrency": budget.max_concurrency,
                    },
                    "statuses": {
                        status: sum(a.status == status for a in agents)
                        for status in sorted(ACTIVE | TERMINAL)
                    },
                },
                agents=views,
            ).model_dump()

    async def spawn(
        self, session, job, specs: list[AgentSpec], reason: str, benefit: str, parent: Agent | None = None
    ) -> list[str]:
        """Caller holds the job lock; the whole batch succeeds or is rejected."""
        if job.status != "RUNNING":
            raise Rejected("Job is not running")
        budget = await session.get(Budget, job.id)
        existing = await self.agents(session, job.id)
        if not specs:
            raise Rejected("Provide at least one agent specification")
        if job.mode == "single" and len(existing) + len(specs) > 1:
            raise Rejected("Single mode forbids delegation")
        if job.mode == "fixed" and len(existing) + len(specs) > job.fixed_agent_count:
            raise Rejected("Fixed mode team size is exhausted")
        if budget.agents_created + len(specs) > budget.max_agents:
            raise Rejected("Agent creation budget exhausted")
        if parent and (job.mode != "adaptive" or "request_subagents" not in parent.spec["allowed_tools"]):
            raise Rejected("Parent is not authorized to delegate")
        allowed = READ_TOOLS | {"request_subagents"}
        if self.settings.allow_git_history:
            allowed |= {"inspect_git_history"}
        task_rows = list(await session.scalars(select(Task).where(Task.job_id == job.id)))
        keys = {task.task_key: next(a.id for a in existing if a.task_id == task.id) for task in task_rows}
        fingerprints = {task.fingerprint for task in task_rows}
        planned = {}
        new_agents = []
        for spec in specs:
            if spec.task_key in keys or spec.task_key in planned:
                raise Rejected("Duplicate task key")
            fingerprint = hashlib.sha256(" ".join(spec.objective.casefold().split()).encode()).hexdigest()
            if fingerprint in fingerprints:
                budget.redundant_requests += 1
                raise Rejected("Duplicate task objective (role-independent fingerprint)")
            fingerprints.add(fingerprint)
            parent_id = parent.id if parent else spec.parent_agent_id
            parent_obj = next((a for a in existing if a.id == parent_id), None)
            if parent_id and (not parent_obj or parent_obj.status in TERMINAL):
                raise Rejected("Parent must be an active agent in this job")
            if parent and spec.parent_agent_id not in (None, parent.id):
                raise Rejected("Agent cannot attach children to another parent")
            depth = parent_obj.depth + 1 if parent_obj else 0
            if depth > budget.max_depth:
                raise Rejected("Maximum recursion depth exceeded")
            if not set(spec.allowed_tools) <= allowed:
                raise Rejected("Unknown or unauthorized tool capability")
            if parent and not set(spec.allowed_tools) <= set(parent.spec["allowed_tools"]):
                raise Rejected("Children cannot escalate parent tool permissions")
            if job.mode != "adaptive" and "request_subagents" in spec.allowed_tools:
                raise Rejected("Delegation tool is disabled in baseline modes")
            if (
                spec.max_steps > self.settings.max_agent_steps
                or spec.token_budget > self.settings.max_agent_tokens
            ):
                raise Rejected("Agent step or token limit exceeds administrator policy")
            allocation = job.model_allocation or self.settings.model_allocation
            selected_model = self.settings.allocate(
                spec.model_purpose,
                spec.model or allocation[spec.model_purpose],
                spec.model_reason,
                allocation["routine"],
            )
            if spec.expected_output_schema:
                import jsonschema

                jsonschema.Draft202012Validator.check_schema(spec.expected_output_schema)
                serialized = json.dumps(spec.expected_output_schema)
                if (
                    any(key in serialized for key in ("$ref", "$dynamicRef", "pattern", "format"))
                    or len(serialized) > 6000
                ):
                    raise Rejected("Output schema references or oversized schemas are not permitted")
            task = Task(
                id=uid(),
                job_id=job.id,
                task_key=spec.task_key,
                fingerprint=fingerprint,
                objective=spec.objective,
            )
            agent = Agent(
                id=uid(),
                job_id=job.id,
                task_id=task.id,
                parent_agent_id=parent_id,
                depth=depth,
                status="CREATED",
                spec={
                    **spec.model_dump(),
                    "parent_agent_id": parent_id,
                    "model": selected_model,
                },
            )
            planned[spec.task_key] = agent.id
            new_agents.append((spec, task, agent))
        # Dependencies can reference earlier tasks or siblings, but cannot form cycles.
        graph = {}
        for spec, _task, agent in new_agents:
            deps = []
            for key in spec.depends_on:
                dependency = keys.get(key) or planned.get(key)
                if not dependency or dependency == agent.id:
                    raise Rejected("Unknown or self-referential dependency")
                if parent and dependency == parent.id:
                    raise Rejected("Child cannot depend on its waiting parent")
                deps.append(dependency)
            graph[agent.id] = deps
        # Include existing prerequisite edges and parent waits. A child depending on
        # an agent that depends on its parent would otherwise deadlock the whole job.
        prior_dependencies = list(
            await session.scalars(
                select(Dependency).join(Agent, Agent.id == Dependency.agent_id).where(Agent.job_id == job.id)
            )
        )
        active_ids = {a.id for a in existing if a.status not in TERMINAL}
        for dependency in prior_dependencies:
            if dependency.agent_id in active_ids and dependency.depends_on_id in active_ids:
                graph.setdefault(dependency.agent_id, []).append(dependency.depends_on_id)
        for existing_parent in existing:
            if existing_parent.status == "WAITING_FOR_CHILDREN":
                graph.setdefault(existing_parent.id, []).extend(
                    a.id
                    for a in existing
                    if a.parent_agent_id == existing_parent.id and a.status not in TERMINAL
                )
        if parent:
            graph.setdefault(parent.id, []).extend(a.id for _, _, a in new_agents)
        visiting, visited = set(), set()

        def visit(node):
            if node in visiting:
                raise Rejected("Dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for child in graph.get(node, []):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        for spec, task, agent in new_agents:
            session.add(task)
            await session.flush()
            session.add(agent)
            await session.flush()
            self.event(
                session,
                job,
                "agent.created",
                {
                    "role": spec.role,
                    "depth": agent.depth,
                    "parent_agent_id": agent.parent_agent_id,
                    "allowed_tools": spec.allowed_tools,
                },
                agent.id,
            )
            self.transition(session, job, agent, "QUEUED")
        for _, _, agent in new_agents:
            for dependency in graph[agent.id]:
                session.add(Dependency(agent_id=agent.id, depends_on_id=dependency))
        budget.agents_created += len(new_agents)
        ids = [agent.id for _, _, agent in new_agents]
        self.event(
            session,
            job,
            "spawn.decision",
            {
                "decision": "SPAWN",
                "reason": reason,
                "expected_benefit": benefit,
                "requested_agents": len(specs),
                "budget_approved": True,
                "agent_ids": ids,
            },
            parent.id if parent else None,
        )
        return ids

    def valid_claim(self, job, agent, claim):
        target = agent or job
        return (
            job.status == "RUNNING"
            and target.lease_owner == claim.worker_id
            and target.lease_until is not None
            and target.lease_until > time.time()
            and (agent is None or agent.status == "RUNNING")
        )

    async def inference_capacity(self, claim: Claim, model: str) -> tuple[int, str]:
        policy = self.settings.policy(model)
        async with self.db.locked(claim.job_id) as (session, job):
            agent = await session.get(Agent, claim.agent_id) if claim.agent_id else None
            if not self.valid_claim(job, agent, claim):
                raise Rejected("Claim was cancelled or expired")
            budget = await session.get(Budget, job.id)
            remaining = budget.max_tokens - budget.tokens - budget.reserved_tokens
            minimum = policy.max_output_tokens + 257
            if remaining < minimum:
                raise BudgetExhausted("Job token budget exhausted")
            minimum_cost = (
                257 * policy.input_per_million * policy.cache_write_multiplier
                + policy.max_output_tokens * policy.output_per_million
            ) / 1e6
            if budget.cost_usd + budget.reserved_cost_usd + minimum_cost > budget.max_cost_usd:
                raise BudgetExhausted("Job estimated cost budget exhausted")
            limits = [(policy.context_tokens, "context"), (remaining, "job")]
            if agent:
                agent_remaining = agent.spec["token_budget"] - agent.tokens
                if agent_remaining < minimum:
                    raise AgentBudgetExhausted("Agent token budget exhausted; supervisor may replan")
                limits.append((agent_remaining, "agent"))
            # Refresh before counting as well as before generation, under the fenced lease.
            (agent or job).lease_until = time.time() + self.settings.lease_seconds
            return min(limits, key=lambda item: item[0])

    async def reserve(self, claim: Claim, model: str, input_bound: int, output_bound: int, purpose="routine"):
        policy = self.settings.policy(model)
        charge = InferenceCharge.estimate(input_bound, output_bound, policy)
        total, cost = charge.tokens, charge.cost_usd
        async with self.db.locked(claim.job_id) as (session, job):
            agent = await session.get(Agent, claim.agent_id) if claim.agent_id else None
            if not self.valid_claim(job, agent, claim):
                raise Rejected("Claim was cancelled or expired")
            budget = await session.get(Budget, job.id)
            account = BudgetAccount(
                budget.max_tokens,
                budget.tokens,
                budget.reserved_tokens,
                budget.max_cost_usd,
                budget.cost_usd,
                budget.reserved_cost_usd,
            )
            account.authorize(
                charge, policy.context_tokens, agent.spec["token_budget"] - agent.tokens if agent else None
            )
            # Refresh between bounded requests under the same fenced claim.
            # A turn may summarize then act, or plan then synthesize.
            (agent or job).lease_until = time.time() + self.settings.lease_seconds
            budget.reserved_tokens += total
            budget.reserved_cost_usd += cost
            inference = Inference(
                id=uid(),
                job_id=job.id,
                agent_id=claim.agent_id,
                model=model,
                reserved_tokens=total,
                reserved_cost=cost,
                pricing=policy.model_dump(),
                purpose=purpose,
            )
            session.add(inference)
            self.event(
                session, job, "llm.started", {"model": model, "reserved_tokens": total}, claim.agent_id
            )
            return inference.id

    async def settle(self, inference_id: str, usage: Reply | tuple[int, int] | None):
        async with self.db.sessions() as lookup:
            info = await lookup.get(Inference, inference_id)
            job_id = info.job_id
        async with self.db.locked(job_id) as (session, job):
            inference = await session.get(Inference, inference_id)
            if inference.status == "ACCOUNTED" or (inference.status == "ESTIMATED_UNKNOWN" and usage is None):
                return
            was_reserved = inference.status == "RESERVED"
            budget = await session.get(Budget, job_id)
            from ..config import ModelPolicy

            policy = (
                ModelPolicy.model_validate(inference.pricing)
                if inference.pricing
                else self.settings.policy(inference.model)
            )
            previous_tokens = (
                inference.input_tokens + inference.output_tokens
                if inference.status == "ESTIMATED_UNKNOWN"
                else 0
            )
            previous_cost = inference.cost_usd if inference.status == "ESTIMATED_UNKNOWN" else 0
            if usage:
                inp, out = (usage.input_tokens, usage.output_tokens) if isinstance(usage, Reply) else usage
                if isinstance(usage, Reply):
                    inference.usage_details = usage.usage_details
                    inference.response_id, inference.reported_model = usage.response_id, usage.reported_model
                cost = usage_cost(policy, inp, out, inference.usage_details)
                tokens = inp + out
                inference.status = "ACCOUNTED"
            else:
                # Unknown outcome may have been billed; never refund uncertain requests.
                inp, out = inference.reserved_tokens, 0
                cost, tokens = inference.reserved_cost, inference.reserved_tokens
                inference.status = "ESTIMATED_UNKNOWN"
            inference.input_tokens, inference.output_tokens, inference.cost_usd = inp, out, cost
            if was_reserved:
                budget.reserved_tokens = max(0, budget.reserved_tokens - inference.reserved_tokens)
                budget.reserved_cost_usd = max(0, budget.reserved_cost_usd - inference.reserved_cost)
            budget.tokens += tokens - previous_tokens
            budget.cost_usd += cost - previous_cost
            if inference.agent_id:
                agent = await session.get(Agent, inference.agent_id)
                agent.tokens += tokens - previous_tokens
                agent.cost_usd += cost - previous_cost
            self.event(
                session,
                job,
                "llm.usage",
                {
                    "model": inference.model,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "estimated_cost_usd": cost,
                    "accounting": inference.status,
                    "usage_details": inference.usage_details,
                    "reserved_cost_usd": inference.reserved_cost,
                    "reconciled_cost_difference_usd": cost - (previous_cost or inference.reserved_cost),
                    "purpose": inference.purpose,
                    "response_id": inference.response_id,
                    "reported_model": inference.reported_model,
                },
                inference.agent_id,
            )
            if (
                tokens > inference.reserved_tokens
                or cost > inference.reserved_cost + 1e-12
                or budget.tokens > budget.max_tokens
                or budget.cost_usd > budget.max_cost_usd
            ):
                await self.terminate(
                    session,
                    job,
                    "CANCELLED",
                    {
                        "code": "provider_usage_exceeded_reservation",
                        "message": "Provider reported usage above the enforced reservation; execution stopped",
                    },
                )

    async def escalate(self, session, job, agent, request):
        allocation = job.model_allocation or self.settings.model_allocation
        selected = self.settings.allocate(
            request.purpose, allocation[request.purpose], request.reason, allocation["routine"]
        )
        if selected == agent.spec["model"]:
            raise Rejected("Agent already uses the requested stronger model")
        budget = await session.get(Budget, job.id)
        policy = self.settings.policy(selected)
        bound = min(policy.context_tokens, agent.spec["token_budget"] - agent.tokens)
        input_bound = bound - policy.max_output_tokens
        cost = (
            max(0, input_bound) * policy.input_per_million * policy.cache_write_multiplier
            + policy.max_output_tokens * policy.output_per_million
        ) / 1e6
        if (
            input_bound < 1000
            or budget.tokens + budget.reserved_tokens + bound > budget.max_tokens
            or budget.cost_usd + budget.reserved_cost_usd + cost > budget.max_cost_usd
        ):
            self.event(
                session,
                job,
                "model.escalation_rejected",
                {"reason": request.reason, "budget_approved": False},
                agent.id,
            )
            raise Rejected("Insufficient remaining budget for stronger reasoning")
        previous = agent.spec["model"]
        agent.spec = {
            **agent.spec,
            "model": selected,
            "model_purpose": request.purpose,
            "model_reason": request.reason,
        }
        data = {
            "previous_model": previous,
            "model": selected,
            "reason": request.reason,
            "expected_benefit": request.expected_benefit,
            "budget_approved": True,
            "next_call_cost_bound_usd": cost,
            "requires_call_reservation": True,
        }
        self.event(session, job, "model.escalated", data, agent.id)
        return data

    async def terminate(self, session, job, status, error=None):
        # A terminating job may still have remote requests in flight. Conservatively
        # settle them now so cancellation followed by a crash cannot strand reservations.
        budget = await session.get(Budget, job.id)
        for inference in list(
            await session.scalars(
                select(Inference).where(Inference.job_id == job.id, Inference.status == "RESERVED")
            )
        ):
            inference.status = "ESTIMATED_UNKNOWN"
            inference.input_tokens = inference.reserved_tokens
            inference.cost_usd = inference.reserved_cost
            budget.tokens += inference.reserved_tokens
            budget.cost_usd += inference.reserved_cost
            budget.reserved_tokens = max(0, budget.reserved_tokens - inference.reserved_tokens)
            budget.reserved_cost_usd = max(0, budget.reserved_cost_usd - inference.reserved_cost)
            if inference.agent_id:
                inflight_agent = await session.get(Agent, inference.agent_id)
                inflight_agent.tokens += inference.reserved_tokens
                inflight_agent.cost_usd += inference.reserved_cost
            self.event(
                session,
                job,
                "llm.usage",
                {
                    "accounting": "ESTIMATED_UNKNOWN",
                    "reason": "job_terminated",
                    "reserved_tokens": inference.reserved_tokens,
                },
                inference.agent_id,
            )
        job.status, job.error, job.ended_at = status, error, time.time()
        job.lease_owner, job.lease_until = None, None
        for agent in await self.agents(session, job.id):
            if agent.status not in TERMINAL:
                self.transition(session, job, agent, "CANCELLED" if status != "TIMED_OUT" else "TIMED_OUT")
        self.event(session, job, "job.status", {"status": status, "error": error})

    async def cancel(self, job_id, owner):
        async with self.db.locked(job_id) as (session, job):
            if job.owner_id != owner:
                raise LookupError("Job not found")
            if job.status == "RUNNING":
                await self.terminate(session, job, "CANCELLED")

    async def cancel_branch(self, session, job, agent_id):
        agents = await self.agents(session, job.id)
        if not any(a.id == agent_id for a in agents):
            raise Rejected("Unknown agent for cancellation")
        ids = {agent_id}
        while True:
            added = {a.id for a in agents if a.parent_agent_id in ids} - ids
            if not added:
                break
            ids |= added
        for agent in agents:
            if agent.id in ids and agent.status not in TERMINAL:
                self.transition(session, job, agent, "CANCELLED")

    async def recover(self, session, job, agents):
        now = time.time()
        budget = await session.get(Budget, job.id)
        for agent in agents:
            if agent.status == "RUNNING" and (agent.lease_until or 0) < now:
                agent.failures += 1
                agent.lease_owner, agent.lease_until = None, None
                target = "QUEUED" if agent.failures <= self.settings.max_retries else "FAILED"
                agent.error = {
                    "code": "lease_expired",
                    "message": "Worker lease expired; turn may be retried",
                    "retryable": target == "QUEUED",
                }
                self.transition(session, job, agent, target)
                budget.recoveries += 1
        if job.lease_owner and (job.lease_until or 0) < now:
            job.lease_owner, job.lease_until = None, None
            budget.recoveries += 1
            self.event(session, job, "supervisor.recovered", {"reason": "lease_expired"})
        # Reservations from abandoned inference are conservatively charged here.
        for inference in list(
            await session.scalars(
                select(Inference).where(
                    Inference.job_id == job.id,
                    Inference.status == "RESERVED",
                    Inference.created_at < now - self.settings.lease_seconds,
                )
            )
        ):
            inference.status = "ESTIMATED_UNKNOWN"
            inference.cost_usd = inference.reserved_cost
            inference.input_tokens = inference.reserved_tokens
            budget.reserved_tokens = max(0, budget.reserved_tokens - inference.reserved_tokens)
            budget.reserved_cost_usd = max(0, budget.reserved_cost_usd - inference.reserved_cost)
            budget.tokens += inference.reserved_tokens
            budget.cost_usd += inference.reserved_cost
            if inference.agent_id:
                agent = await session.get(Agent, inference.agent_id)
                agent.tokens += inference.reserved_tokens
                agent.cost_usd += inference.reserved_cost
            self.event(session, job, "llm.recovered", {"accounting": "ESTIMATED_UNKNOWN"}, inference.agent_id)

    async def claim(self, worker_id: str) -> Claim | None:
        worker_id = f"{worker_id[:50]}:{uid()}"
        async with self.db.sessions() as session:
            candidates = list(
                await session.scalars(
                    select(Job.id)
                    .where(Job.status == "RUNNING")
                    .order_by(Job.last_scheduled, Job.created_at)
                    .limit(100)
                )
            )
        for job_id in candidates:
            async with self.db.locked(job_id) as (session, job):
                if job.status != "RUNNING" or job.last_scheduled > time.time():
                    continue
                agents = await self.agents(session, job.id)
                await self.recover(session, job, agents)
                if time.time() - job.created_at > self.settings.max_job_seconds:
                    await self.terminate(session, job, "TIMED_OUT")
                    continue
                budget = await session.get(Budget, job.id)
                if budget.tokens >= budget.max_tokens or budget.cost_usd >= budget.max_cost_usd:
                    await self.terminate(
                        session,
                        job,
                        "CANCELLED",
                        {"code": "budget_exhausted", "message": "Execution budget exhausted"},
                    )
                    continue
                # Wake waiting parents only after all descendants they requested have settled.
                for agent in agents:
                    if agent.status == "WAITING_FOR_CHILDREN":
                        children = [a for a in agents if a.parent_agent_id == agent.id]
                        if all(a.status in TERMINAL for a in children):
                            self.transition(session, job, agent, "QUEUED")
                dependency_rows = list(
                    await session.scalars(
                        select(Dependency)
                        .join(Agent, Agent.id == Dependency.agent_id)
                        .where(Agent.job_id == job.id)
                    )
                )
                by_id = {a.id: a for a in agents}
                # Propagate prerequisite failure before asking the supervisor to replan.
                for dependent in agents:
                    if dependent.status == "QUEUED":
                        prereqs = [
                            by_id[d.depends_on_id] for d in dependency_rows if d.agent_id == dependent.id
                        ]
                        if any(p.status in TERMINAL - {"COMPLETED"} for p in prereqs):
                            dependent.error = {
                                "code": "dependency_failed",
                                "message": "A prerequisite failed",
                            }
                            self.transition(session, job, dependent, "FAILED")
                if self.db.engine.dialect.name == "postgresql":
                    await session.execute(text("SELECT pg_advisory_xact_lock(4815162342)"))
                global_running = await session.scalar(
                    select(func.count()).select_from(Agent).where(Agent.status == "RUNNING")
                )
                global_supervisors = await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.status == "RUNNING", Job.lease_owner.is_not(None))
                )
                if global_running + global_supervisors >= self.settings.max_concurrent_agents:
                    continue
                running = sum(a.status == "RUNNING" for a in agents)
                completed_roots = sum(a.parent_agent_id is None and a.status in TERMINAL for a in agents)
                # Revisit completed independent branches while other branches are still
                # working, so the model can cancel redundant work or request verification.
                if (
                    job.mode == "adaptive"
                    and completed_roots > job.supervisor_seen_roots
                    and not job.lease_owner
                    and not all(a.status in TERMINAL for a in agents)
                ):
                    if job.supervisor_steps < self.settings.max_supervisor_steps:
                        job.lease_owner = worker_id
                        job.lease_until = time.time() + self.settings.lease_seconds
                        job.last_scheduled = time.time()
                        return Claim(job.id, None, worker_id)
                if running < budget.max_concurrency and not job.lease_owner:
                    for agent in sorted(agents, key=lambda item: (item.steps, item.created_at)):
                        if agent.status != "QUEUED" or agent.next_attempt > time.time():
                            continue
                        deps = [by_id[d.depends_on_id] for d in dependency_rows if d.agent_id == agent.id]
                        if any(d.status in TERMINAL - {"COMPLETED"} for d in deps):
                            agent.error = {"code": "dependency_failed", "message": "A prerequisite failed"}
                            self.transition(session, job, agent, "FAILED")
                            continue
                        if not all(d.status == "COMPLETED" for d in deps):
                            continue
                        if agent.steps >= agent.spec["max_steps"]:
                            agent.error = {"code": "step_limit", "message": "Maximum agent steps reached"}
                            self.transition(session, job, agent, "TIMED_OUT")
                            continue
                        agent.lease_owner, agent.lease_until = (
                            worker_id,
                            time.time() + self.settings.lease_seconds,
                        )
                        agent.started_at = agent.started_at or time.time()
                        self.transition(session, job, agent, "RUNNING")
                        job.last_scheduled = time.time()
                        budget.max_observed_concurrency = max(budget.max_observed_concurrency, running + 1)
                        return Claim(job.id, agent.id, worker_id)
                if not job.lease_owner and all(a.status in TERMINAL for a in agents):
                    if job.supervisor_steps >= self.settings.max_supervisor_steps:
                        await self.terminate(
                            session,
                            job,
                            "FAILED",
                            {
                                "code": "supervisor_step_limit",
                                "message": "Supervisor transition limit reached",
                            },
                        )
                        continue
                    job.lease_owner, job.lease_until = worker_id, time.time() + self.settings.lease_seconds
                    job.last_scheduled = time.time()
                    return Claim(job.id, None, worker_id)
        return None

    async def heartbeat(self, worker_id: str):
        async with self.db.sessions.begin() as session:
            heartbeat = await session.get(WorkerHeartbeat, worker_id)
            if heartbeat:
                heartbeat.updated_at = time.time()
            else:
                session.add(WorkerHeartbeat(id=worker_id, updated_at=time.time()))
            # Heartbeats do not extend inference leases. A fresh budget reservation
            # can refresh a valid claim between requests; stalled calls still expire.

    async def events(self, job_id: str, after: int = 0, limit: int = 200, latest: bool = False):
        async with self.db.sessions() as session:
            records = list(
                await session.scalars(
                    select(Event)
                    .where(Event.job_id == job_id, Event.id > after)
                    .order_by(Event.id.desc() if latest else Event.id)
                    .limit(limit)
                )
            )
            if latest:
                records.reverse()
            return [
                {
                    "id": e.id,
                    "type": e.type,
                    "agent_id": e.agent_id,
                    "created_at": e.created_at,
                    "data": e.data,
                }
                for e in records
            ]

    async def context(self, job_id: str, agent_id: str | None = None):
        snapshot = await self.snapshot(job_id)
        # UI accounting, timestamps and traces add no investigative evidence to a prompt.
        for key in ("created_at", "updated_at", "ended_at", "trace_id", "report"):
            snapshot.pop(key, None)
        snapshot["metrics"] = {
            key: snapshot["metrics"][key]
            for key in (
                "total_agents",
                "tokens",
                "estimated_cost_usd",
                "reserved_tokens",
                "reserved_cost_usd",
                "model_allocation",
                "limits",
            )
        }
        for view in snapshot["agents"]:
            for key in ("created_at", "started_at", "ended_at", "model_reason", "allowed_tools"):
                view.pop(key, None)
        async with self.db.sessions() as session:
            job = await session.get(Job, job_id)
            if agent_id:
                agent = await session.get(Agent, agent_id)
                summary = await session.scalar(
                    select(Artifact)
                    .where(Artifact.agent_id == agent_id, Artifact.kind == "context_summary")
                    .order_by(Artifact.created_at.desc())
                    .limit(1)
                )
                through = summary.content["through_created_at"] if summary else 0
                history = list(
                    await session.scalars(
                        select(ToolExecution)
                        .where(ToolExecution.agent_id == agent_id, ToolExecution.created_at > through)
                        .order_by(ToolExecution.created_at.desc())
                        .limit(12)
                    )
                )
                snapshot["agent_spec"] = agent.spec
                last_input = (
                    await session.scalar(
                        select(Inference.input_tokens)
                        .where(
                            Inference.agent_id == agent_id,
                            Inference.status == "ACCOUNTED",
                            # A summary sees only a batch of observations, not the full
                            # agent context. Its small input cannot predict the next action.
                            Inference.purpose != "summary",
                        )
                        .order_by(Inference.created_at.desc())
                        .limit(1)
                    )
                    or 0
                )
                remaining_steps = agent.spec["max_steps"] - agent.steps
                remaining_tokens = agent.spec["token_budget"] - agent.tokens
                output_limit = self.settings.policy(agent.spec["model"]).max_output_tokens
                allowance = AgentAllowance(remaining_steps, remaining_tokens, last_input, output_limit)
                snapshot["execution_budget"] = {
                    "remaining_steps": remaining_steps,
                    "remaining_tokens": remaining_tokens,
                    "finish_required": allowance.finish_required,
                    "note": "Cumulative allowance includes repeated input and output; submit_result uses a turn.",
                }
                dependencies = next(a["dependencies"] for a in snapshot["agents"] if a["id"] == agent_id)
                related = set(dependencies) | {
                    a["id"] for a in snapshot["agents"] if a["parent_agent_id"] == agent_id
                }
                for view in snapshot["agents"]:
                    if view["id"] not in related:
                        result = view.pop("result", None)
                        if result:
                            view["result_summary"] = result["summary"][:500]
                snapshot["context_summary"] = summary.content if summary else None
                snapshot["tool_history"] = [
                    {"name": h.name, "arguments": h.arguments, "output": h.output, "created_at": h.created_at}
                    for h in reversed(history)
                ]
            else:
                snapshot["supervisor_history"] = job.supervisor_history[-10:]
            snapshot["available_tools"] = sorted(
                READ_TOOLS
                | ({"request_subagents"} if job.mode == "adaptive" else set())
                | ({"inspect_git_history"} if self.settings.allow_git_history else set())
            )
            snapshot["model_options"] = {
                purpose: {
                    "model": model,
                    "reasoning_effort": self.settings.effort(purpose),
                    "pricing": self.settings.policy(model).model_dump(),
                }
                for purpose, model in (job.model_allocation or self.settings.model_allocation).items()
            }
            return snapshot
