"""Backend support for Garmin Activities for Omarchy."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("omarchy-garmin-activities")
except PackageNotFoundError:  # pragma: no cover - supports an unpackaged source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
