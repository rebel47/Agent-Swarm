"""Portable types for tests; PostgreSQL is required by runtime configuration."""

import time
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class RepositorySource(Base):
    __tablename__ = "repository_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    location: Mapped[str] = mapped_column(String(2000))
    ref: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="PREPARING")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    model_allocation: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    objective: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))
    fixed_agent_count: Mapped[int] = mapped_column(Integer, default=1)
    allow_patch_proposals: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    ended_at: Mapped[float | None] = mapped_column(Float)
    trace_id: Mapped[str] = mapped_column(String(32), default=lambda: uuid.uuid4().hex)
    report: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    supervisor_steps: Mapped[int] = mapped_column(Integer, default=0)
    supervisor_seen_roots: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    supervisor_history: Mapped[list] = mapped_column(JSON, default=list)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[float | None] = mapped_column(Float)
    last_scheduled: Mapped[float] = mapped_column(Float, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key"),
        CheckConstraint("mode in ('single','fixed','adaptive')"),
        CheckConstraint("status in ('RUNNING','COMPLETED','FAILED','CANCELLED','TIMED_OUT')"),
    )


class Budget(Base):
    __tablename__ = "execution_budgets"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    max_agents: Mapped[int] = mapped_column(Integer)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    max_depth: Mapped[int] = mapped_column(Integer)
    max_tokens: Mapped[int] = mapped_column(Integer)
    max_cost_usd: Mapped[float] = mapped_column(Float)
    agents_created: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    max_observed_concurrency: Mapped[int] = mapped_column(Integer, default=0)
    redundant_requests: Mapped[int] = mapped_column(Integer, default=0)
    recoveries: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        CheckConstraint("agents_created >= 0 and tokens >= 0 and reserved_tokens >= 0"),
        CheckConstraint("cost_usd >= 0 and reserved_cost_usd >= 0"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    task_key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    objective: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("job_id", "task_key"),
        UniqueConstraint("job_id", "fingerprint"),
    )


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    parent_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True)
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float)
    ended_at: Mapped[float | None] = mapped_column(Float)
    error: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (
        CheckConstraint("depth >= 0 and steps >= 0 and tokens >= 0"),
        CheckConstraint(
            "status in ('CREATED','QUEUED','RUNNING','WAITING_FOR_CHILDREN',"
            "'COMPLETED','FAILED','CANCELLED','TIMED_OUT')"
        ),
        Index("ix_agents_queue", "job_id", "status", "next_attempt", "created_at"),
    )


class Dependency(Base):
    __tablename__ = "agent_dependencies"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    __table_args__ = (CheckConstraint("agent_id != depends_on_id"),)


class Event(Base):
    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    type: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (Index("ix_events_replay", "job_id", "id"),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Inference(Base):
    __tablename__ = "inferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="RESERVED")
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    reserved_cost: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    usage_details: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    pricing: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    purpose: Mapped[str] = mapped_column(String(30), default="routine", server_default="routine")
    response_id: Mapped[str | None] = mapped_column(String(200))
    reported_model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    updated_at: Mapped[float] = mapped_column(Float)
