"""Prepare the private cache root before uv can create environment metadata."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

if __package__:
    from omarchy_garmin.storage import UnsafeStoragePathError, ensure_private_directory
else:  # Direct stdlib-only invocation before the locked environment exists.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from omarchy_garmin.storage import UnsafeStoragePathError, ensure_private_directory


def run(argv: Sequence[str]) -> int:
    """Secure one absolute application cache root without exposing path details."""
    if len(argv) != 1:
        return 2
    try:
        ensure_private_directory(Path(argv[0]))
    except (OSError, UnsafeStoragePathError, ValueError):
        return 1
    return 0


def main() -> int:
    """Run the cache preflight with the current process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
