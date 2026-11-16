"""Public compatibility facade; adapters live in the infrastructure layer."""

from .infrastructure.database import (
    Database,
)

__all__ = ["Database"]
