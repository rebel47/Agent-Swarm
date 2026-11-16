"""Repository acquisition through real filesystem, Git, API ownership and worker execution."""

import os
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import create_app
from app.models import RepositorySource
from app.repositories import (
    GitRunner,
    RepositoryError,
    RepositoryImporter,
    normalize_source,
    remove_snapshot,
    snapshot_path,
)
from app.runtime import Runtime
from app.schemas import AgentTurn, JobRequest, RepositoryRequest, SupervisorDecision
from tests.fakes import ScriptedProvider
from tests.test_runtime import decision, drain, result


@pytest.fixture
def project(settings):
    root = Path(settings.workspaces["test"])
    settings.local_repository_roots = {str(root.parent): str(root.parent)}
    return root


@pytest.mark.parametrize(
    "location",
    [
        "http://github.com/owner/repo",
        "file:///tmp/repo",
        "ssh://github.com/owner/repo",
        "git@github.com:owner/repo",
        "https://localhost/owner/repo",
        "https://127.0.0.1/owner/repo",
        "https://github.com.evil.example/owner/repo",
        "https://user:password@github.com/owner/repo",
        "https://github.com/owner/repo?token=secret",
        "https://github.com/owner/repo#main",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/../repo",
        "https://github.com:8443/owner/repo",
        "https://[invalid/owner/repo",
    ],
)
def test_untrusted_git_sources_rejected_before_network(settings, location):
    with pytest.raises(RepositoryError):
        normalize_source(location, None, settings)


def test_git_hosts_and_branch_normalization(settings):
    assert normalize_source("https://github.com/octocat/Hello-World", "main", settings) == {
        "kind": "git",
        "location": "https://github.com/octocat/Hello-World.git",
        "ref": "main",
    }
    assert normalize_source("https://gitlab.com/group/subgroup/repo.git", None, settings)["kind"] == "git"
    assert normalize_source("https://bitbucket.org/team/repo", None, settings)["kind"] == "git"
    for ref in ("--upload-pack=bad", "main..other", "branch;command", "x.lock"):
        with pytest.raises(RepositoryError):
            normalize_source("https://github.com/owner/repo", ref, settings)


def test_local_mapping_and_escape_rejection(settings, project, tmp_path):
    settings.local_repository_roots = {"E:/projects": str(project.parent)}
    assert normalize_source("e:\\projects\\repository", None, settings)["kind"] == "local"
    for path in (
        "E:/projects/../elsewhere",
        "E:/projects-other/repository",
        "D:/projects/repository",
        "relative/path",
        "//server/share/project",
        "E:/projects/repository/app.py",
    ):
        with pytest.raises(RepositoryError):
            normalize_source(path, None, settings)
    with pytest.raises(RepositoryError):
        normalize_source("E:/projects/repository", "main", settings)


def test_local_snapshot_excludes_secrets_links_dependencies_and_binary(settings, project):
    (project / ".env").write_text("OPENAI_API_KEY=not-to-be-copied")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "secret.js").write_text("secret")
    (project / "binary.py").write_bytes(b"\0binary")
    (project / "secrets").mkdir()
    (project / "secrets" / "key.py").write_text("secret")
    os.link(project / "app.py", project / "linked.py")
    # Restore an ordinary file because the hardlink also makes the original ineligible.
    (project / "safe.py").write_text("value = 42\n")
    source = normalize_source(str(project), None, settings)
    source_id = str(uuid.uuid4())
    info = RepositoryImporter(settings).prepare(source_id, source)
    snapshot = snapshot_path(settings, source_id)
    assert {p.name for p in snapshot.iterdir()} == {"safe.py"}
    assert info["revision"].startswith("sha256:") and info["file_count"] == 1
    (project / "safe.py").write_text("changed = True\n")
    assert (snapshot / "safe.py").read_text() == "value = 42\n"
    remove_snapshot(settings, source_id)
    assert not snapshot.exists() and (project / "safe.py").exists()


def test_snapshot_limits_and_safe_cleanup(settings, project):
    settings.max_repository_bytes = 1024
    (project / "big.py").write_text("x" * 2000)
    source_id = str(uuid.uuid4())
    with pytest.raises(RepositoryError, match="size limit"):
        RepositoryImporter(settings).prepare(source_id, normalize_source(str(project), None, settings))
    assert not snapshot_path(settings, source_id, ".partial").exists()
    for source_id in ("..", "../outside", "not-a-uuid"):
        with pytest.raises(RepositoryError):
            remove_snapshot(settings, source_id)


def test_git_runner_clears_credentials_and_rejects_expired_work(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-git")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.sshCommand")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "arbitrary-program")
    runner = GitRunner(settings, tmp_path, time.monotonic() - 1)
    assert "OPENAI_API_KEY" not in runner.env and "GIT_CONFIG_COUNT" not in runner.env
    assert runner.env["GIT_ALLOW_PROTOCOL"] == "https"
    assert "http.followRedirects=false" in runner.command
    with pytest.raises(RepositoryError, match="timed out"):
        runner.run(["--version"])


def test_real_git_snapshot_never_checks_out_or_runs_filters(settings, tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    seed.mkdir()
    setup = tmp_path / "setup"
    setup.mkdir()
    runner = GitRunner(settings, setup, time.monotonic() + 30)
    runner.run(["init", str(seed)])
    (seed / "app.py").write_text("value = 42\n")
    (seed / ".env").write_text("secret=never-export")
    (seed / ".gitattributes").write_text("*.py filter=malicious\n")
    runner.run(["add", "."], seed)
    runner.run(
        ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"], seed
    )
    runner.run(["branch", "-M", "review-fixture"], seed)
    original = GitRunner.run
    seen = []

    def fixture_transport(self, args, cwd=None, limit=8192):
        seen.append(args)
        if args[0] == "clone":
            assert "--no-checkout" in args and args[-2] == "https://github.com/test/fixture.git"
            assert args[args.index("--branch") + 1] == "review-fixture"
            # Only the test transport permits file://, substituting a local fixture for HTTPS.
            self.env["GIT_ALLOW_PROTOCOL"] = "file"
            self.command.extend(["-c", "protocol.file.allow=always"])
            args = [*args[:-2], seed.as_uri(), args[-1]]
        return original(self, args, cwd, limit)

    monkeypatch.setattr(GitRunner, "run", fixture_transport)
    source_id = str(uuid.uuid4())
    source = normalize_source("https://github.com/test/fixture", "review-fixture", settings)
    info = RepositoryImporter(settings).prepare(source_id, source)
    snapshot = snapshot_path(settings, source_id)
    assert (snapshot / "app.py").read_text() == "value = 42\n"
    assert not (snapshot / ".env").exists() and not (snapshot / ".git").exists()
    assert len(info["revision"]) == 40
    assert not snapshot_path(settings, source_id, ".git-work").exists()
    assert all(args[0] not in ("checkout", "submodule") for args in seen)


def test_authenticated_repository_api_ownership_capacity_and_deletion(settings, project):
    auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/repositories", json={"location": str(project)}).status_code == 401
        response = client.post("/api/v1/repositories", headers=auth, json={"location": str(project)})
        assert response.status_code == 201, response.text
        repository = response.json()
        assert repository["status"] == "READY" and repository["file_count"] == 1
        assert client.get("/api/v1/workspaces", headers=auth).json()["local_roots"] == list(
            settings.local_repository_roots
        )
        assert repository["id"] in {
            r["id"] for r in client.get("/api/v1/workspaces", headers=auth).json()["items"]
        }
        settings.max_repository_snapshots = 1
        assert (
            client.post("/api/v1/repositories", headers=auth, json={"location": str(project)}).status_code
            == 409
        )

        async def other_owner():
            with pytest.raises(ValueError, match="unauthorized"):
                await client.app.state.store.create_job(
                    JobRequest(objective="Inspect source correctness", workspace_id=repository["id"]),
                    "other-owner",
                )
            with pytest.raises(LookupError):
                await client.app.state.store.delete_repository(repository["id"], "other-owner")

        client.portal.call(other_owner)
        body = {"objective": "Inspect source correctness", "workspace_id": repository["id"]}
        job = client.post("/api/v1/jobs", headers=auth, json=body).json()
        assert client.delete("/api/v1/repositories/" + repository["id"], headers=auth).status_code == 409
        client.post("/api/v1/jobs/" + job["id"] + "/cancel", headers=auth)
        assert client.delete("/api/v1/repositories/" + repository["id"], headers=auth).status_code == 200
        assert client.post("/api/v1/jobs", headers=auth, json=body).status_code == 409
        assert (
            client.get("/api/v1/jobs/" + job["id"], headers=auth).json()["repository"]["status"] == "DELETED"
        )


def test_git_failure_is_reported_and_releases_preparation_capacity(settings, monkeypatch):
    def fail(self, source_id, source):
        raise RepositoryError("Remote repository was not found", "repository_fetch_failed", 502)

    monkeypatch.setattr(RepositoryImporter, "prepare", fail)
    auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        for _ in range(2):
            response = client.post(
                "/api/v1/repositories", headers=auth, json={"location": "https://github.com/owner/missing"}
            )
            assert response.status_code == 502
            assert response.json()["detail"]["message"] == "Remote repository was not found"
        records = client.get("/api/v1/repositories", headers=auth).json()
        assert len(records) == 2 and all(r["status"] == "FAILED" for r in records)


@pytest.mark.asyncio
async def test_imported_repository_enters_real_runtime_and_retains_snapshot(store, project, spec):
    source = await store.admit_repository(RepositoryRequest(location=str(project)), "default")
    info = RepositoryImporter(store.settings).prepare(source["id"], source)
    await store.finish_repository(source["id"], info=info)
    job_id = await store.create_job(
        JobRequest(objective="Inspect division reliability", workspace_id=source["id"]), "default"
    )
    (project / "app.py").write_text("print('original changed after snapshot')\n")
    provider = ScriptedProvider(
        decisions=[
            decision([spec]),
            SupervisorDecision(
                action="FINISH",
                reason="Source evidence is sufficient for final reporting",
                expected_benefit="Deliver source findings",
                report=result(),
            ),
        ],
        turns=[AgentTurn(result=result())],
    )
    await drain(store, Runtime(store, provider))
    snapshot = await store.snapshot(job_id)
    assert snapshot["status"] == "COMPLETED" and snapshot["repository"]["revision"] == info["revision"]
    assert snapshot["report"]["findings"][0]["evidence"][0]["quote"] == "return a / b"


@pytest.mark.asyncio
async def test_stale_preparation_recovery_and_global_admission(store, project):
    store.settings.max_repository_preparations = 1
    first = await store.admit_repository(RepositoryRequest(location=str(project)), "default")
    with pytest.raises(RepositoryError, match="preparation capacity"):
        await store.admit_repository(RepositoryRequest(location=str(project)), "default")
    async with store.db.sessions.begin() as session:
        record = await session.get(RepositorySource, first["id"])
        record.created_at = time.time() - store.settings.repository_prepare_seconds - 100
    second = await store.admit_repository(RepositoryRequest(location=str(project)), "default")
    assert second["id"] != first["id"]
    async with store.db.sessions() as session:
        record = await session.scalar(select(RepositorySource).where(RepositorySource.id == first["id"]))
        assert record.status == "FAILED" and record.error["code"] == "preparation_interrupted"
