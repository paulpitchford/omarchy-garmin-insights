# Garmin Activities for Omarchy

Garmin Activities for Omarchy is a planned bar plugin for viewing recent Garmin Connect activity totals. It will cover today and the last 7, 30, and 90 calendar days, with breakdowns that respect the differences between cycling, running, walking, swimming, strength training, and other activity types.

> [!IMPORTANT]
> This project is pre-alpha and is not installable as an Omarchy plugin yet. The Python backend can authenticate with Garmin, synchronize recent activities, and write the bounded summary cache. The QML interface has not been implemented.

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

The Python backend uses a locked `uv` environment. Authentication, activity fetching, SQLite storage, and the bounded JSON summary cache are implemented. QML will read that cache rather than credentials, raw Garmin responses, or SQLite.

A refresh uses a seven-day overlap unless the current local date has no successful full reconciliation. In that case, it fetches the current 90-day window. Full reconciliations remove records that have aged out of that window. The Garmin call has one retry for transient network or server failures and a 120-second deadline for the complete request. Authentication failures and HTTP 429 responses fail without a retry. The QML service will eventually run this command every 30 minutes and keep the last successful summary available when a refresh fails.

Machine-readable commands use a versioned JSON envelope. Errors contain only a reviewed code and fixed safe message; unexpected exception text and command arguments are not reflected in output. Process statuses are grouped by category: `0` for success, `2` for invalid arguments, `10` for configuration, `20` for authentication, `30` for network or remote-service failures, `40` for invalid data, `50` for local storage, `60` for concurrency, and `70` for unexpected internal failures. Some categories are reserved for commands implemented in later phases.

Authentication commands are available now:

```bash
uv run --locked omarchy-garmin-activities auth status --json
uv run --locked omarchy-garmin-activities auth login
uv run --locked omarchy-garmin-activities auth logout --confirm
uv run --locked omarchy-garmin-activities auth purge --confirm
```

Run `auth login` in a visible terminal. It reads the password and any MFA code with hidden input in the same Python process. `auth status` checks local configuration only, so stored tokens are reported as configured but unverified until `auth login` or a later Garmin request succeeds. Logout removes tokens but keeps account-scoped local data. Purge removes the token, account scope, and all other known plugin data files. Both operations are idempotent and require `--confirm`.

Activity synchronization commands are also available:

```bash
uv run --locked omarchy-garmin-activities refresh --json
uv run --locked omarchy-garmin-activities refresh --json --full
```

`refresh` requires stored tokens and an absolute `XDG_RUNTIME_DIR`. It acquires a non-blocking owner-only lock, so two refresh processes cannot overlap. The first refresh each local day is a full reconciliation; `--full` requests one explicitly. A failed fetch, malformed response, account mismatch, or interrupted database transaction leaves the previous activity rows intact. After reconciliation, the command rebuilds the complete 90-day summary and atomically replaces the previous cache.

## Summary cache contract

The summary cache is versioned separately from the CLI envelope. Schema version 1 contains today, 7-day, 30-day, and 90-day periods. Each period has overall totals and breakdowns by Garmin's original activity type key. Type keys are kept as display text, including unfamiliar values; the cache does not group them into a different stored type.

The first contract includes activity count, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, sets, and repetitions. Measurements remain in SI units. Every metric includes a `contributingActivityCount`. A metric is `null` when no activity supplied a usable value, and missing measurements never add zero to a total.

Average heart rate and average power are weighted by activity duration. Average speed is weighted by moving duration. Values without a positive matching duration do not contribute to those weighted averages. Maximum heart rate is the highest supplied value. Other measurements are sums of supplied values.

The cache is limited to 20,000 activities, 256 original type keys, and 1 MiB of JSON. It does not contain activity names, Garmin activity IDs, start times, coordinates, or routes.

## Privacy and security

Garmin activity data can reveal routines, health information, and location. The implementation will follow these rules:

- Login happens in a visible terminal. Passwords and MFA codes are never passed through command arguments or environment variables.
- Only Garmin tokens are retained. They are stored at `$XDG_STATE_HOME/omarchy-garmin-activities/auth/garmin_tokens.json` with owner-only permissions.
- A pseudonymous account fingerprint is stored at `$XDG_DATA_HOME/omarchy-garmin-activities/account_scope.json` to prevent data from two accounts being merged. The raw Garmin account identifier, email address, and profile response are not saved.
- Normalised activity data is stored at `$XDG_DATA_HOME/omarchy-garmin-activities/activities.sqlite3` with owner-only permissions. The current 90-day window is retained.
- Aggregates for the QML interface are stored at `$XDG_CACHE_HOME/omarchy-garmin-activities/summary.json` with owner-only permissions. The cache excludes activity names, identifiers, and start times.
- The allowlisted activity fields are the Garmin activity ID, optional name, original type key, local start time and date, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, total sets, and total repetitions. Energy is converted from Garmin kilocalories to joules; other measurements remain in their canonical stored units.
- Complete Garmin API responses are not saved.
- Coordinates, routes, profile responses, and email addresses are not written to the activity database or display cache.
- FIT, GPX, TCX, and KML files are not downloaded by the first release.
- Tests and demos use fabricated data. Personal Garmin exports do not belong in this repository.
- Removing the plugin does not silently delete local data. Disconnect and purge actions will require explicit confirmation.

See [SECURITY.md](SECURITY.md) for reporting instructions.

## Dependencies and network access

The backend uses:

- [uv](https://github.com/astral-sh/uv) for the locked Python environment; and
- [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) 0.3.11, an MIT-licensed, unofficial Garmin Connect client installed from PyPI.

The direct dependency is fixed in `pyproject.toml`, and all transitive versions and package hashes are recorded in `uv.lock`. During environment setup, `uv` downloads packages from `pypi.org` and `files.pythonhosted.org`. Garmin authentication can contact `sso.garmin.com`, `connect.garmin.com`, `connectapi.garmin.com`, `diauth.garmin.com`, and `mobile.integration.garmin.com`. The backend does not send credentials anywhere else.

Activity refreshes use the read-only `/activitylist-service/activities/search/activities` endpoint on `connectapi.garmin.com` through `get_activities_by_date`, without an activity-type filter. `python-garminconnect` is not an official Garmin API. Garmin may change or rate-limit the web services it uses.

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

The repository now has a typed Python package, stable CLI contracts, private XDG storage, interactive Garmin login with same-process MFA, account-scope protection, bounded activity validation, versioned SQLite storage, incremental refreshes, daily 90-day reconciliation, process locking, and a bounded summary cache. Tests mock Garmin and use fabricated activities. The Omarchy manifest and QML interface are next. Installation instructions will be added only when the plugin can display cached activity summaries safely.

## Disclaimer

This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Garmin, Omarchy, 37signals, or the Omarchy Plugins marketplace. Activity information is provided for personal reference and is not medical advice.

## License

This project is licensed under the [MIT License](LICENSE).
