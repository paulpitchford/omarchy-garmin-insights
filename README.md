# Garmin Activities for Omarchy

Garmin Activities for Omarchy is a planned bar plugin for viewing recent Garmin Connect activity totals. It will cover today and the last 7, 30, and 90 calendar days, with breakdowns that respect the differences between cycling, running, walking, swimming, strength training, and other activity types.

> [!IMPORTANT]
> This project is pre-alpha and is not installable as an Omarchy plugin yet. The Python project, quality checks, XDG path resolution, and initial CLI contract are in place. Garmin connectivity and the QML interface have not been implemented.

The intended plugin ID is `io.github.paulpitchford.garmin-activities`.

## Planned behaviour

The first release will:

- connect to one Garmin account through an interactive terminal login;
- support Garmin MFA without storing the account password;
- fetch activity summaries through the read-only parts of `python-garminconnect`;
- keep a local, normalised activity database for incremental refreshes;
- show cached information while offline;
- handle missing metrics and unfamiliar activity types without treating them as zero;
- store measurements in SI units and convert them for display; and
- avoid downloading FIT files because the activity summary API already provides the data needed for the first version.

The plugin will not upload, edit, or delete Garmin data.

## Technical outline

Omarchy runs plugins inside one long-lived Quickshell process. This plugin will use a singleton QML service for scheduling and shared state, plus a bar widget and its panel. The service will run a short-lived Python command when data needs refreshing. There will be no Python daemon or systemd service.

The Python backend will use a locked `uv` environment. It will authenticate, fetch read-only activity summaries, normalise an explicit allowlist of fields, update SQLite, and generate a bounded JSON summary for QML. QML will not read credentials, raw Garmin responses, or SQLite directly.

The planned default refresh interval is 30 minutes. Recent data will refresh incrementally, with a full 90-day reconciliation once per day. Authentication failures and Garmin rate limits will stop automatic retries and leave the last successful summary available.

## Privacy and security

Garmin activity data can reveal routines, health information, and location. The implementation will follow these rules:

- Login happens in a visible terminal. Passwords and MFA codes are never passed through command arguments or environment variables.
- Only Garmin tokens are retained. They are stored in a dedicated owner-only directory under `$XDG_STATE_HOME`.
- Normalised activity data is stored under `$XDG_DATA_HOME` with owner-only permissions.
- Complete Garmin API responses are not saved.
- Coordinates, routes, profile responses, and email addresses are not written to the activity database or display cache.
- FIT, GPX, TCX, and KML files are not downloaded by the first release.
- Tests and demos use fabricated data. Personal Garmin exports do not belong in this repository.
- Removing the plugin does not silently delete local data. Disconnect and purge actions will require explicit confirmation.

See [SECURITY.md](SECURITY.md) for reporting instructions.

## Dependencies

The backend is expected to depend on:

- [uv](https://github.com/astral-sh/uv) for the locked Python environment; and
- [python-garminconnect](https://github.com/cyberjunky/python-garminconnect), an MIT-licensed, unofficial Garmin Connect client.

Dependency versions and transitive packages will be committed in `uv.lock`. The project will use a published PyPI release rather than an unpinned Git dependency. Third-party licences will be recorded when the dependency is added.

`python-garminconnect` is not an official Garmin API. Garmin may change or rate-limit the web services it uses.

## Development

The Python backend targets Python 3.12 and 3.13. The checked-in `.python-version` selects Python 3.13 for development, and `uv` can install it when needed.

Set up the locked environment:

```bash
uv sync --locked --dev
```

Run the complete local quality suite:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run pyscn check --max-complexity 12 --max-cycles 0 src
```

Inspect the current backend contract:

```bash
uv run --locked omarchy-garmin-activities doctor
uv run --locked omarchy-garmin-activities doctor --json
```

GitHub Actions runs the same formatting, linting, typing, testing, coverage, and structural checks. Omarchy validation and `qmllint` will join the suite when the QML plugin files exist. The project rules are in [AGENTS.md](AGENTS.md).

## Project status

The repository now has a typed Python package, a versioned JSON command contract, XDG path resolution, tests, locked development tooling, and CI. The next backend work is private directory creation and atomic file handling, followed by the mocked Garmin authentication boundary. Installation instructions will be added only when setup can complete and the plugin can display cached activity summaries safely.

## Disclaimer

This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Garmin, Omarchy, 37signals, or the Omarchy Plugins marketplace. Activity information is provided for personal reference and is not medical advice.

## License

This project is licensed under the [MIT License](LICENSE).
