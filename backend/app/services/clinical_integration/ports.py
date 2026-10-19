"""Local, read-only core boundary; adapters own bounded I/O and authentication."""

from typing import Protocol

from backend.app.schemas.clinical_integration import ComponentVersion, CoreInput, CoreOutput


class CoreAdapter(Protocol):
    def current_version(self) -> ComponentVersion:
        """Trusted deployment version, not a version asserted by model output."""
        ...

    def collect(self, context: CoreInput) -> CoreOutput:
        """Read-only, bounded, repeatable operation. Never finalizes a finding.

        Network implementations must enforce connection/read deadlines and raise
        TimeoutError/ConnectionError without embedding credentials in results.
        No remote adapter is registered by this release.
        """
        ...
