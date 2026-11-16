# Review a repository from a URL or local folder

The investigation form now has **Repository URL or local path** beside the objective.
Leave the repository dropdown on **Git URL or local project folder**, enter a repository,
write your objective and click **Investigate**. The app prepares an owned source snapshot,
then starts the usual OpenAI/LangGraph investigation. Saved snapshots and the original
small/complex examples remain available in the dropdown.

Examples:

```text
https://github.com/owner/repository
https://gitlab.com/group/subgroup/repository.git
https://bitbucket.org/team/repository
E:/projects/my-application
/home/alex/projects/my-application
```

For a Git URL, the optional branch/tag field selects the version to fetch. Omit it to use
the remote default branch. Use the repository root URL rather than a browser /tree/ URL.
The job shows the source URL/path, immutable revision and count of copied source files.
Each new URL/path submission creates a fresh snapshot. Selecting a saved snapshot reuses its
recorded version. Agents inspect the snapshot and propose fixes; original projects are read-only.

## Local folders in Docker

Docker can read host folders explicitly mounted into its containers. Set one absolute host
projects root in .env, using forward slashes on Windows:

```ini
LOCAL_PROJECTS_PATH=E:/projects
```

Restart with docker compose up -d. Docker mounts this folder read-only at /local-projects
and automatically maps paths beginning with E:/projects. You can then enter any project
folder inside that root, such as E:/projects/my-application, without editing Compose for
each project. The UI displays the configured root. Paths outside it produce an explicit error.

This workspace is configured with LOCAL_PROJECTS_PATH=E:/agent-swarm-mvp.
For a different projects directory, change that value and run docker compose up -d.
Without this variable, Docker mounts the parent of this project and accepts container-style
paths under /local-projects. Never use the browser computer's path to refer to a folder on
a different server: local paths belong to the machine hosting the backend/Docker.

For a native backend, configure allowed prefixes and their real directories directly:

```ini
LOCAL_REPOSITORY_ROOTS={"E:/projects":"E:/projects"}
```

Docker supplies its own mapping from LOCAL_PROJECTS_PATH. Register additional mounts/mappings
in a Compose override if multiple independent project roots are needed.

## Remote Git repositories

The defaults allow public HTTPS repositories on github.com, gitlab.com and bitbucket.org.
REPOSITORY_GIT_HOSTS is an administrator-controlled JSON list for other trusted HTTPS Git
hosts. Credentials in URLs, SSH, file URLs, local network targets outside the host allowlist,
query strings and fragments are rejected. Renamed repositories may need their canonical URL
because redirects are disabled.

Private remote authentication is not implemented. Clone a private repository locally with
your normal credentials and submit its local folder. OpenAI keys are never passed to Git.
No GitHub account connection, repository write access or provider API key is needed for a
public repository.

Git is installed in the backend Docker image. Native installations require Git on PATH.
The importer uses a [shallow clone without checkout](https://git-scm.com/docs/git-clone),
then reads only approved regular source blobs. Hooks, credential helpers, inherited Git
configuration and redirects are disabled using [Git configuration controls](https://git-scm.com/docs/git-config).
Repository hooks, checkout filters, submodules and Git LFS downloads are not executed.

## Limits, ownership and storage

All import/list/removal routes require application authentication. Imports belong to the
same tenant as their jobs. Other tenants cannot select or remove a source. The backend has
write access to managed snapshot storage; workers mount it read-only. Registered repository
mounts and local projects mounts remain read-only.

The source filter excludes environment files, credentials, secret directories, dependency
trees, binary files, links and oversized files. Source statements are still untrusted data,
and evidence validation/tool output bounds remain active. Git snapshots retain a commit ID;
local snapshots retain a SHA-256 digest of the copied content.

Defaults:

| Setting | Default |
|---|---:|
| MAX_REPOSITORY_BYTES | 52,428,800 (50 MiB) |
| MAX_REPOSITORY_FILES | 2,000 |
| MAX_FILE_BYTES | 262,144 |
| MAX_REPOSITORY_SNAPSHOTS | 20 ready/preparing snapshots per tenant |
| MAX_REPOSITORY_PREPARATIONS | 2 across the backend |
| REPOSITORY_PREPARE_SECONDS | 120 |

The Next.js proxy allows 180 seconds for the default 120-second preparation deadline. If you
raise the backend deadline, also raise experimental.proxyTimeout in frontend/next.config.mjs
and rebuild the frontend. Downloads and Git output are monitored against size/deadline limits. Unsupported files do not
enter the final source snapshot. Too many supported files fails explicitly instead of silently
truncating the snapshot. Use a narrower local project folder or authorized larger limits for
large repositories.

Snapshots live in the persistent repository-cache Docker volume, outside the read-only app
filesystem. Failed preparation removes partial files; interrupted preparations expire and
are cleaned on subsequent imports. The form shows preparation progress and returns errors
before creating a billable investigation. Preparing a repository itself makes no OpenAI calls.
New jobs freeze their selected repository ID; workers resolve it from persistent storage.

Choose a saved snapshot and click **Remove saved snapshot** to reclaim storage. Removal is
blocked while any job using it is running or preparation is active. Historical results and
source metadata remain available after snapshot removal.

## API

```text
POST /api/v1/repositories
{"location":"https://github.com/owner/repository","ref":null}

GET /api/v1/repositories
DELETE /api/v1/repositories/{id}
GET /api/v1/workspaces

POST /api/v1/jobs
{"objective":"Review correctness and edge cases","workspace_id":"<prepared repository id>"}
```

POST /repositories returns 201 only after a READY snapshot is stored. Its response includes
id, kind, location, ref, revision, file_count, size_bytes and status. HTTP disconnection does
not cancel a running bounded import. Import failure is recorded as FAILED and returns the
actual bounded Git failure or an actionable validation error. Jobs cannot use a failed,
deleted, unprepared or foreign-owned source. /workspaces includes saved READY sources,
the configured local roots and allowed Git hosts.
