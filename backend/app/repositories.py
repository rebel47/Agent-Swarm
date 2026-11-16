"""Public compatibility facade; adapters live in the infrastructure layer."""

from .infrastructure.source_import import (
    RepositoryError,
    RepositoryImporter,
    GitRunner,
    snapshot_path,
    remove_snapshot,
    normalize_source,
    resolve_local,
    tree_bytes,
)

__all__ = [
    "RepositoryError",
    "RepositoryImporter",
    "GitRunner",
    "snapshot_path",
    "remove_snapshot",
    "normalize_source",
    "resolve_local",
    "tree_bytes",
]
