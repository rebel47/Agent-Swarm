"""Bounded repository acquisition. No checkout, hooks, filters or repository code execution."""

import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from ..config import Settings
from ..observability import redact
from ..tools import DENIED_PARTS, Repository, ToolDenied
from ..domain.errors import RepositoryError


def snapshot_path(settings, source_id, suffix=""):
    try:
        if str(uuid.UUID(source_id)) != source_id:
            raise ValueError()
    except ValueError:
        raise RepositoryError("Invalid repository snapshot ID") from None
    root = Path(settings.repository_cache_dir).resolve()
    path = root / (source_id + suffix)
    if path.is_symlink() or path.resolve().parent != root:
        raise RepositoryError("Repository cache boundary violation")
    return path


def remove_snapshot(settings, source_id, suffix=""):
    path = snapshot_path(settings, source_id, suffix)
    if path.exists():
        # Only a validated UUID immediately within the configured cache can be removed.
        def retry(operation, name, error):
            candidate = Path(name)
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(path):
                raise RepositoryError("Repository cleanup boundary violation")
            candidate.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            operation(name)

        shutil.rmtree(path, onerror=retry)


def normalize_source(location, ref, settings):
    location = location.strip()
    if location.startswith('"') and location.endswith('"'):
        location = location[1:-1]
    if not location or any(ord(c) < 32 for c in location):
        raise RepositoryError("Enter a repository URL or an absolute project folder path")
    if ref and (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", ref) or ".." in ref or ref.endswith(".lock")
    ):
        raise RepositoryError("Enter a valid Git branch or tag name")
    if "://" in location or location.startswith("git@"):
        try:
            url = urlsplit(location)
            allowed = (
                url.scheme == "https"
                and url.hostname in settings.repository_git_hosts
                and url.port in (None, 443)
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
            )
        except ValueError:
            allowed = False
        if not allowed:
            raise RepositoryError(
                "Use a public HTTPS Git URL on an allowed host, without credentials, query or fragment"
            )
        parts = url.path.strip("/").split("/")
        if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in (".", "..") for p in parts):
            raise RepositoryError(
                "Use the repository root URL, for example https://github.com/owner/repository"
            )
        if url.hostname == "github.com" and len(parts) != 2:
            raise RepositoryError("Use a GitHub repository root URL; enter the branch separately")
        path = "/".join(parts)
        if not path.endswith(".git"):
            path += ".git"
        return {"kind": "git", "location": "https://" + url.hostname + "/" + path, "ref": ref}
    if ref:
        raise RepositoryError("A branch or tag applies only to a Git URL")
    resolve_local(location, settings)
    return {"kind": "local", "location": location, "ref": None}


def resolve_local(location, settings):
    if ".." in re.split(r"[/\\]", location) or location.startswith(("//", "\\\\")):
        raise RepositoryError("Use an absolute project folder inside a configured local projects root")
    windows = bool(re.match(r"^[A-Za-z]:[/\\]", location))
    user_path = PureWindowsPath(location) if windows else Path(location)
    if not user_path.is_absolute():
        raise RepositoryError("A local repository requires an absolute folder path")
    for prefix, mounted in settings.local_repository_roots.items():
        base = PureWindowsPath(prefix) if windows else Path(prefix)
        try:
            relative = user_path.relative_to(base)
        except ValueError:
            continue
        root = Path(mounted).resolve(strict=True)
        candidate = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink() or (
                current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400
            ):
                raise RepositoryError("Linked folders and reparse points are not allowed")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise RepositoryError(
                "Project folder does not exist inside the configured local projects root"
            ) from None
        if not resolved.is_relative_to(root) or not resolved.is_dir():
            raise RepositoryError("Select a project directory inside a configured local projects root")
        if any(p.casefold() in DENIED_PARTS or p.startswith(".") for p in relative.parts):
            raise RepositoryError("This directory is excluded from repository review")
        return resolved
    raise RepositoryError(
        "This local path is outside the configured projects folders. Choose a folder under: "
        + (", ".join(settings.local_repository_roots) or "(no local projects root configured)")
    )


def tree_bytes(root):
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass
    return total


class GitRunner:
    def __init__(self, settings, scratch, deadline):
        self.settings, self.scratch, self.deadline = settings, scratch, deadline
        self.env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        self.env.update(
            HOME=str(scratch),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_ALLOW_PROTOCOL="https",
            GIT_LFS_SKIP_SMUDGE="1",
            LC_ALL="C",
        )
        empty = scratch / "empty"
        empty.mkdir()
        self.command = [
            "git",
            "-c",
            "core.hooksPath=" + str(empty),
            "-c",
            "init.templateDir=" + str(empty),
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.proxy=",
            "-c",
            "http.extraHeader=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-c",
            "submodule.recurse=false",
        ]

    def run(self, args, cwd=None, limit=8192):
        if time.monotonic() >= self.deadline:
            raise RepositoryError("Repository preparation timed out", "repository_timeout", 504)
        with (
            tempfile.TemporaryFile(dir=self.scratch) as output,
            tempfile.TemporaryFile(dir=self.scratch) as errors,
        ):
            options = (
                {"start_new_session": True}
                if os.name != "nt"
                else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            )
            try:
                process = subprocess.Popen(
                    [*self.command, *args],
                    cwd=cwd or self.scratch,
                    env=self.env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    **options,
                )
            except FileNotFoundError:
                raise RepositoryError("Git is not installed on the backend", "git_unavailable", 503) from None
            try:
                while process.poll() is None:
                    if time.monotonic() > self.deadline:
                        raise RepositoryError("Repository preparation timed out", "repository_timeout", 504)
                    if (
                        os.fstat(output.fileno()).st_size > limit
                        or os.fstat(errors.fileno()).st_size > 65536
                        or tree_bytes(self.scratch) > self.settings.max_repository_bytes
                    ):
                        raise RepositoryError(
                            "Repository exceeds the configured download or output limit",
                            "repository_too_large",
                            413,
                        )
                    time.sleep(0.05)
                output.seek(0)
                data = output.read(limit + 1)
                if len(data) > limit or tree_bytes(self.scratch) > self.settings.max_repository_bytes:
                    raise RepositoryError(
                        "Repository exceeds the configured download or output limit",
                        "repository_too_large",
                        413,
                    )
                if process.returncode:
                    errors.seek(0)
                    detail = redact(errors.read(2000).decode(errors="replace")).replace(
                        str(self.scratch), "[snapshot]"
                    )
                    raise RepositoryError(
                        "Git could not read this public repository or branch. " + detail,
                        "repository_fetch_failed",
                        502,
                    )
                return data
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                            timeout=5,
                        )
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait(timeout=5)


class RepositoryImporter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def prepare(self, source_id, source):
        root = Path(self.settings.repository_cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        target = snapshot_path(self.settings, source_id)
        stage = snapshot_path(self.settings, source_id, ".partial")
        scratch = snapshot_path(self.settings, source_id, ".git-work")
        if target.exists() or stage.exists() or scratch.exists():
            raise RepositoryError("Repository preparation already exists", "repository_conflict", 409)
        stage.mkdir()
        deadline = time.monotonic() + self.settings.repository_prepare_seconds
        try:
            if source["kind"] == "git":
                scratch.mkdir()
                runner = GitRunner(self.settings, scratch, deadline)
                clone = scratch / "clone"
                args = ["clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags", "--no-checkout"]
                if source["ref"]:
                    args += ["--branch", source["ref"]]
                runner.run([*args, "--", source["location"], str(clone)])
                revision = runner.run(["rev-parse", "HEAD"], clone).decode().strip()
                if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
                    raise RepositoryError("Git returned an invalid commit ID", "repository_fetch_failed", 502)
                listing = runner.run(["ls-tree", "-r", "-l", "-z", "HEAD"], clone, limit=4194304)
                files = []
                for record in listing.split(b"\0"):
                    if not record:
                        continue
                    fields, name = record.split(b"\t", 1)
                    mode, kind, oid, size = fields.split()
                    path = name.decode("utf-8", errors="strict")
                    if (
                        mode in (b"100644", b"100755")
                        and kind == b"blob"
                        and self.allowed(path, stage)
                        and int(size) <= self.settings.max_file_bytes
                    ):
                        files.append((path, oid.decode()))

                def reader(item):
                    return runner.run(
                        ["cat-file", "blob", item[1]], clone, limit=self.settings.max_file_bytes
                    )

            else:
                local = resolve_local(source["location"], self.settings)
                policy = self.settings.model_copy(
                    update={"max_repository_files": self.settings.max_repository_files + 1}
                )
                repository = Repository(local, policy)
                files = [(path, None) for path in repository.files()]
                revision = None

                def reader(item):
                    path = repository.resolve(item[0])
                    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                    descriptor = os.open(path, flags)
                    with os.fdopen(descriptor, "rb") as file:
                        info = os.fstat(file.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                            raise RepositoryError("Linked or non-regular project file was rejected")
                        data = file.read(self.settings.max_file_bytes + 1)
                    if len(data) > self.settings.max_file_bytes:
                        raise RepositoryError("A project file changed beyond the configured size limit")
                    return data

            if len(files) > self.settings.max_repository_files:
                raise RepositoryError(
                    "Repository has too many reviewable files; narrow the project folder or raise MAX_REPOSITORY_FILES",
                    "repository_too_large",
                    413,
                )
            total, count = 0, 0
            digest = hashlib.sha256()
            for item in files:
                if time.monotonic() > deadline:
                    raise RepositoryError("Repository preparation timed out", "repository_timeout", 504)
                try:
                    data = reader(item)
                except (ToolDenied, OSError):
                    raise RepositoryError(
                        "A project file changed or could not be read; retry the snapshot"
                    ) from None
                if b"\0" in data:
                    continue
                total += len(data)
                if total > self.settings.max_repository_bytes:
                    raise RepositoryError(
                        "Repository exceeds the configured snapshot size limit", "repository_too_large", 413
                    )
                destination = stage / item[0]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                digest.update(item[0].encode() + b"\0" + data)
                count += 1
            if not count:
                raise RepositoryError("No supported source files were found in this repository")
            stage.rename(target)
            return {
                "revision": revision or "sha256:" + digest.hexdigest(),
                "file_count": count,
                "size_bytes": total,
            }
        except BaseException:
            remove_snapshot(self.settings, source_id, ".partial")
            raise
        finally:
            remove_snapshot(self.settings, source_id, ".git-work")

    def allowed(self, path, root):
        value = PurePosixPath(path)
        if any(ord(c) < 32 for c in path) or any(c in path for c in '<>"|?*'):
            return False
        if any(
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", PurePosixPath(part).stem)
            for part in value.parts
        ):
            return False
        if (
            value.is_absolute()
            or len(path) > 500
            or any(p in (".", "..") for p in value.parts)
            or ":" in path
            or "\\" in path
        ):
            return False
        if any(p.lower() in DENIED_PARTS or p.startswith(".") for p in value.parts[:-1]):
            return False
        return Repository(root, self.settings).allowed_name(Path(path))
