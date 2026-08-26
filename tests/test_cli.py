import json
from io import StringIO
from pathlib import Path
from typing import Any

from omarchy_garmin.cli import OUTPUT_SCHEMA_VERSION, run


def test_doctor_json_has_stable_machine_contract() -> None:
    stdout = StringIO()

    exit_status = run(
        ["doctor", "--json"],
        stdout=stdout,
        environment={"XDG_RUNTIME_DIR": "/run/user/1000"},
        home=Path("/home/example"),
    )

    payload: dict[str, Any] = json.loads(stdout.getvalue())
    assert exit_status == 0
    assert payload["schemaVersion"] == OUTPUT_SCHEMA_VERSION
    assert payload["command"] == "doctor"
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["runtimeDirectoryAvailable"] is True
    assert payload["data"]["paths"] == {
        "cache": "/home/example/.cache/omarchy-garmin-activities",
        "data": "/home/example/.local/share/omarchy-garmin-activities",
        "runtime": "/run/user/1000/omarchy-garmin-activities",
        "state": "/home/example/.local/state/omarchy-garmin-activities",
    }


def test_doctor_human_output_marks_missing_runtime_directory() -> None:
    stdout = StringIO()

    exit_status = run(
        ["doctor"],
        stdout=stdout,
        environment={},
        home=Path("/home/example"),
    )

    assert exit_status == 0
    assert "Garmin Activities backend is ready." in stdout.getvalue()
    assert "Runtime: unavailable" in stdout.getvalue()
