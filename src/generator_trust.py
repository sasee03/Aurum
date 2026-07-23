"""Pipeline-scoped trust policy for persisted generator provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet


@dataclass(frozen=True)
class GeneratorTrustPolicy:
    """Describe which hardened generator provenances are trusted for one pipeline."""

    pipeline: str
    trusted_hardened_provenances: FrozenSet[str]

    @property
    def generation_available(self) -> bool:
        """Return whether this pipeline has any currently trusted generator path."""
        return bool(self.trusted_hardened_provenances)

    def trusts_run(self, provenance: Any) -> bool:
        """Return whether a persisted run came from a trusted generator for this pipeline."""
        return (
            isinstance(provenance, str)
            and provenance in self.trusted_hardened_provenances
        )
