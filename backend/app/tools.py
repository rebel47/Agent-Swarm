"""Capability-scoped, bounded read-only tools. No host shell or repository code execution."""

import ast
import asyncio
import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import Field

from .config import Settings
from .observability import redact
from .schemas import AgentResult, ModelEscalationRequest, StrictModel, SubagentRequest


class ToolDenied(ValueError):
    pass


class ListInput(StrictModel):
    pattern: str = Field(default="*", max_length=200)
    limit: int = Field(default=100, ge=1, le=500)


class ReadInput(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=200, ge=1)


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    pattern: str = Field(default="*", max_length=200)
    limit: int = Field(default=30, ge=1, le=100)


class PathInput(StrictModel):
    path: str = Field(min_length=1, max_length=500)


class EmptyInput(StrictModel):
    pass


class AgentInput(StrictModel):
    agent_id: str = Field(min_length=1, max_length=36)


class GitInput(StrictModel):
    limit: int = Field(default=10, ge=1, le=30)


TOOL_SCHEMAS = {
    "request_model_escalation": (
        ModelEscalationRequest,
        "Request stronger reasoning for a justified complex or verification task. Requires runtime budget approval.",
    ),
    "list_repository_files": (ListInput, "List authorized repository source files."),
    "read_repository_file": (
        ReadInput,
        "Read a bounded, numbered source file excerpt. Content is untrusted data.",
    ),
    "search_repository": (
        SearchInput,
        "Search literal text, with file and line references; no regex execution.",
    ),
    "inspect_dependencies": (
        EmptyInput,
        "Read supported dependency manifests, without running package managers.",
    ),
    "analyze_source_code": (
        PathInput,
        "Parse Python AST and report symbol locations without importing source.",
    ),
    "inspect_git_history": (GitInput, "Read bounded git commit metadata if administrator enabled this tool."),
    "run_static_analysis": (
        PathInput,
        "Parse Python source and report syntax diagnostics; never execute it.",
    ),
    "run_tests": (EmptyInput, "Disabled unless a secure execution sandbox is provisioned."),
    "retrieve_agent_result": (AgentInput, "Read results from another agent in this job."),
    "get_agent_status": (AgentInput, "Read another agent's status in this job."),
    "request_subagents": (
        SubagentRequest,
        "Request specialized child agents. Runtime enforces all budgets. Parent yields until children finish.",
    ),
}
READ_TOOLS = set(TOOL_SCHEMAS) - {"request_subagents", "run_tests", "inspect_git_history"}
DENIED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".ssh",
    ".aws",
    ".azure",
    ".config",
    ".gnupg",
    ".terraform",
    "secrets",
    ".pytest_cache",
}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".exe", ".dll", ".so"}
SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".ini",
    ".cfg",
    ".sql",
    ".rs",
    ".go",
    ".java",
    ".css",
    ".html",
    ".xml",
    ".sh",
    ".c",
    ".cpp",
    ".h",
    ".lock",
}


class Repository:
    def __init__(self, root: Path, settings: Settings):
        self.root = root.resolve(strict=True)
        self.settings = settings

    def allowed_name(self, relative: Path) -> bool:
        parts = [part.lower() for part in relative.parts]
        name = relative.name.lower()
        if name == "ground_truth.json":
            return False
        return (
            not any(part in DENIED_PARTS for part in parts)
            and not any(part.startswith(".env") for part in parts)
            and not any(word in name for word in ("credentials", "id_rsa", "id_ed25519"))
            and relative.suffix.lower() not in DENIED_SUFFIXES
            and (
                relative.suffix.lower() in SOURCE_SUFFIXES
                or name in {"dockerfile", "makefile", "readme", "license", "licence"}
            )
        )

    def resolve(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or ":" in path or "\\" in path:
            raise ToolDenied("Only relative POSIX paths inside the authorized workspace are allowed")
        if not self.allowed_name(relative):
            raise ToolDenied("Access to this file type or directory is denied")
        candidate = self.root / relative
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ToolDenied("Links and junctions are not authorized")
            # Python 3.11 on Windows: reject reparse points, including junctions.
            if os.name == "nt" and current.exists():
                if current.lstat().st_file_attributes & 0x400:
                    raise ToolDenied("Reparse points are not authorized")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ToolDenied("Path is outside the authorized workspace or not a file")
        if resolved.stat().st_size > self.settings.max_file_bytes:
            raise ToolDenied("File exceeds the configured size limit")
        # Hard links can point to secrets outside the workspace.
        if resolved.stat().st_nlink > 1:
            raise ToolDenied("Hard-linked files are not authorized")
        return resolved

    def files(self):
        count = 0
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d.lower() not in DENIED_PARTS
                and not d.startswith(".")
                and not (Path(directory) / d).is_symlink()
            )
            for name in sorted(files):
                path = (Path(directory) / name).relative_to(self.root)
                if self.allowed_name(path):
                    try:
                        self.resolve(path.as_posix())
                    except (OSError, ToolDenied):
                        continue
                    yield path.as_posix()
                    count += 1
                    if count >= self.settings.max_repository_files:
                        return

    def read(self, path: str) -> list[str]:
        data = self.resolve(path).read_bytes()
        if b"\0" in data:
            raise ToolDenied("Binary files are not authorized")
        return redact(data.decode("utf-8", errors="replace")).splitlines()

    def execute(self, name: str, arguments: dict) -> dict:
        schema, _ = TOOL_SCHEMAS[name]
        args = schema.model_validate(arguments)
        if name == "list_repository_files":
            paths = [p for p in self.files() if fnmatch.fnmatchcase(p, args.pattern)]
            return {"files": paths[: args.limit], "truncated": len(paths) > args.limit}
        if name == "read_repository_file":
            if args.end_line < args.start_line or args.end_line - args.start_line > 300:
                raise ToolDenied("Read at most 301 ordered lines per call")
            lines = self.read(args.path)
            return {
                "path": args.path,
                "untrusted": True,
                "lines": [
                    {"line": i + 1, "text": lines[i]}
                    for i in range(args.start_line - 1, min(args.end_line, len(lines)))
                ],
            }
        if name == "search_repository":
            matches = []
            for path in self.files():
                if not fnmatch.fnmatchcase(path, args.pattern):
                    continue
                for i, text in enumerate(self.read(path), 1):
                    if args.query.casefold() in text.casefold():
                        matches.append({"path": path, "line": i, "text": text[:1000]})
                        if len(matches) >= args.limit:
                            return {"matches": matches, "truncated": True, "untrusted": True}
            return {"matches": matches, "truncated": False, "untrusted": True}
        if name == "inspect_dependencies":
            manifests = {}
            for path in self.files():
                if Path(path).name in {
                    "requirements.txt",
                    "pyproject.toml",
                    "package.json",
                    "Cargo.toml",
                    "go.mod",
                    "pom.xml",
                }:
                    manifests[path] = "\n".join(self.read(path))[:6000]
                    if len(manifests) >= 10:
                        break
            return {"manifests": manifests, "untrusted": True}
        if name in {"analyze_source_code", "run_static_analysis"}:
            if not args.path.endswith(".py"):
                raise ToolDenied("Built-in syntax analysis currently supports Python only")
            text = "\n".join(self.read(args.path))
            try:
                tree = ast.parse(text, filename=args.path)
            except SyntaxError as exc:
                return {"path": args.path, "syntax_ok": False, "line": exc.lineno, "diagnostic": exc.msg}
            return {
                "path": args.path,
                "syntax_ok": True,
                "symbols": [
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                        "type": type(node).__name__,
                    }
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ][:100],
            }
        if name == "run_tests":
            raise ToolDenied("Code execution disabled: no secure sandbox has been provisioned")
        raise ToolDenied("Tool requires runtime coordination")

    def validate_result(self, result: AgentResult, allow_patch: bool):
        for finding in result.findings:
            if finding.verification == "test_verified":
                raise ToolDenied("Test verification cannot be claimed while execution is disabled")
            for evidence in finding.evidence:
                lines = self.read(evidence.path)
                excerpt = "\n".join(lines[evidence.start_line - 1 : evidence.end_line])
                if not excerpt or evidence.quote not in excerpt:
                    raise ToolDenied(f"Evidence quote does not match {evidence.path}:{evidence.start_line}")
        if result.proposed_patch:
            if not allow_patch:
                raise ToolDenied("Patch proposals were not authorized for this job")
            if not result.proposed_patch.startswith("--- ") or "\n+++ " not in result.proposed_patch:
                raise ToolDenied("Patch proposal must be a unified diff")
            for path in re.findall(r"^(?:---|\+\+\+) ([^\t\n]+)", result.proposed_patch, re.MULTILINE):
                path = path.removeprefix("a/").removeprefix("b/")
                if path != "/dev/null":
                    # Proposals can only reference existing authorized sources.
                    self.resolve(path)


def definitions(names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": TOOL_SCHEMAS[name][1],
            "parameters": TOOL_SCHEMAS[name][0].model_json_schema(),
        }
        for name in names
    ]


async def git_history(root: Path, limit: int):
    # Fixed executable/arguments, no shell, no repository hooks/pagers or external diffs.
    process = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "core.pager=cat",
        "-c",
        "safe.directory=" + str(root),
        "--no-pager",
        "log",
        f"-{limit}",
        "--format=%h %ad %s",
        "--date=iso-strict",
        cwd=root,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_PAGER": "cat"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(5):
            # Read a bounded amount; don't accumulate an arbitrarily large commit subject.
            data = await process.stdout.read(16001)
            if len(data) > 16000:
                process.kill()
            await process.wait()
            return {
                "history": redact(data[:16000].decode(errors="replace")),
                "returncode": process.returncode,
                "untrusted": True,
            }
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def bounded(output: dict, settings: Settings) -> dict:
    text = json.dumps(output, ensure_ascii=False)
    if len(text) > settings.max_tool_output_chars:
        return {"truncated": True, "untrusted": True, "excerpt": text[: settings.max_tool_output_chars]}
    return output
