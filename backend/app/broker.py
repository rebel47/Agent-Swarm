"""Public compatibility facade; adapters live in the infrastructure layer."""

from .infrastructure.queue import (
    Broker,
)

__all__ = ["Broker"]
