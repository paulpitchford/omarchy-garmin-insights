import json
import tomllib
from pathlib import Path
from typing import cast


def load_manifest() -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    return cast(dict[str, object], json.loads((repository_root / "manifest.json").read_text()))


def test_manifest_and_python_package_versions_match() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest = load_manifest()
    pyproject = tomllib.loads((repository_root / "pyproject.toml").read_text())

    assert manifest["version"] == pyproject["project"]["version"]


def test_candidate_metadata_describes_activity_and_bounded_wellness() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest = load_manifest()
    pyproject = tomllib.loads((repository_root / "pyproject.toml").read_text())
    bar_widget = cast(dict[str, object], manifest["barWidget"])

    assert "activity" in str(manifest["description"]).lower()
    assert "wellness" in str(manifest["description"]).lower()
    assert "wellness" in str(bar_widget["description"]).lower()
    assert "wellness" in str(pyproject["project"]["description"]).lower()
    assert (repository_root / "screenshots" / "wellness-today.png").is_file()
    assert (repository_root / "screenshots" / "wellness-trends.png").is_file()


def test_update_checks_are_an_explicit_default_enabled_boolean_setting() -> None:
    manifest = load_manifest()
    bar_widget = cast(dict[str, object], manifest["barWidget"])
    defaults = cast(dict[str, object], bar_widget["defaults"])
    schema = cast(list[dict[str, object]], bar_widget["schema"])

    assert defaults["checkForUpdates"] is True
    assert schema[3] == {
        "key": "checkForUpdates",
        "type": "boolean",
        "label": "Check for updates",
        "defaultValue": True,
    }
