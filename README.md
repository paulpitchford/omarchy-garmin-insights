# Garmin Insights for Omarchy

Garmin Insights is an Omarchy Quattro bar plugin that shows recent Garmin Connect activity totals. It covers today and the last 7, 30, and 90 calendar days, with separate rows for each Garmin activity type.

![Garmin Insights panel showing fabricated demo data](preview.png)

The plugin ID is `io.github.paulpitchford.garmin-insights`.

## What it does

- Shows activity count, duration, distance, and energy for the selected period.
- Breaks totals down by Garmin's original activity type, including types the plugin does not already know.
- Supports metric, imperial, or locale-selected units.
- Keeps a rolling 90-day local database and a smaller summary cache for the interface.
- Refreshes every 30 minutes by default and continues showing the last valid summary while offline.
- Uses a visible terminal for Garmin login and supports MFA in the same login process.
- Works on horizontal and vertical bars and shares one refresh service across monitors.
- Includes a synthetic demo mode that does not contact Garmin.

The plugin only reads activity summaries. It does not upload, edit, schedule, or delete Garmin data, and it does not download FIT files or routes.

## Roadmap

### Required before 0.1

Two feature phases remain before the first release: activity drill-down and update awareness. They are planned but are not available in the current build.

- Open a bounded activity list from the selected period or an activity-type row.
- Select an activity to see the allowlisted details already stored in the local database.
- Use an explicit action to open that activity on Garmin Connect in the default browser.
- Keep list and detail reads local. Drill-down will not make another Garmin API request or download routes, maps, or FIT files.
- Fix and retest private cache-directory creation before the first dependency command.
- Test an update from the current aggregate-only build to the drill-down build while retaining plugin settings, tokens, account scope, and normalized activities.
- Add a bounded top-level **Update available** indicator for supported Git-managed installs. It will check the fixed public repository at most once per 24 hours and offer a visible review action, but it will never update the checkout by itself.

The external link will be built from a fixed Garmin Connect HTTPS address and a validated numeric activity ID. Garmin data will not be allowed to provide a URL, host, scheme, path, or command. The browser uses its own Garmin session; plugin OAuth tokens will not be passed to it.

### After 0.1

Later design work may add optional daily health cards and bar metrics for Body Battery, steps, sleep, stress, training readiness, HRV, resting heart rate, intensity minutes, floors, and calories. Seven-day trends and panel controls for card order and visibility are also under consideration. Garmin China support remains an open decision.

## Requirements

- Omarchy with the Quattro shell plugin commands (`omarchy plugin` and `omarchy bar`).
- [`uv`](https://github.com/astral-sh/uv) at one of these paths:
  - `/usr/bin/uv`
  - `~/.local/bin/uv`
  - `~/.local/share/mise/shims/uv`
- A Garmin Connect account and network access for login and refreshes.
- An absolute `XDG_RUNTIME_DIR`, as provided by a normal Omarchy desktop session.

`uv` installs the required Python version and the locked backend packages. If you use the mise shim, install or configure `uv` through mise before setup; invoking the shim remains subject to your mise configuration and may trigger mise's own version resolution or download process. The plugin does not need root access and does not install a system service.

## Install

Review the repository before installing because Omarchy plugins run unsandboxed with your user account's permissions. Then add and enable it:

```bash
omarchy plugin add https://github.com/paulpitchford/omarchy-garmin-insights.git --enable
```

The plugin checkout is stored at:

```text
~/.config/omarchy/plugins/io.github.paulpitchford.garmin-insights
```

Left-click the Garmin Insights bar item to open its panel, then select **Set up backend**. A visible terminal runs the locked dependency setup. The Python environment is stored outside the plugin checkout at:

```text
$XDG_CACHE_HOME/omarchy-garmin-insights/uv-environment
```

When `XDG_CACHE_HOME` is unset, the path starts at `~/.cache`.

After setup finishes, select **Connect Garmin**. Enter the Garmin email in the terminal. Password and MFA input are hidden. The password and MFA code stay in that login process and are not written to files, command arguments, environment variables, QML properties, or logs.

A successful login starts the first refresh. The first refresh of each local calendar day reconciles the complete rolling 90-day window. Later refreshes reconcile a seven-day overlap.

### Try the interface without Garmin

Demo mode uses only fabricated data:

```bash
omarchy bar set io.github.paulpitchford.garmin-insights demoMode true --json
```

Turn it off before connecting an account:

```bash
omarchy bar set io.github.paulpitchford.garmin-insights demoMode false --json
```

## Use

- Left-click the bar item to open or close the panel.
- Middle-click to refresh.
- Right-click to run the action needed for the current state: setup, login, retry, or refresh.
- In the panel, use Left and Right to change period, Enter for the main action, `R` to refresh, Tab to switch panels, and Escape to close.

The horizontal bar shows the selected period's activity count. A vertical bar uses an icon-only form.

### Settings

Settings can be changed through the Omarchy bar settings interface or with `omarchy bar set`:

| Setting | Values | Default |
|---|---|---|
| `period` | `today`, `7Days`, `30Days`, `90Days` | `7Days` |
| `units` | `auto`, `metric`, `imperial` | `auto` |
| `refreshMinutes` | 5 to 360 | 30 |
| `demoMode` | `true`, `false` | `false` |

Examples:

```bash
omarchy bar set io.github.paulpitchford.garmin-insights period 30Days
omarchy bar set io.github.paulpitchford.garmin-insights units metric
omarchy bar set io.github.paulpitchford.garmin-insights refreshMinutes 60 --json
```

## Update

Updates are manual. An installed plugin is a Git checkout whose `origin` remains this repository. Omarchy does not automatically move it to a release tag or notify the plugin when a newer version exists.

Run:

```bash
omarchy plugin update io.github.paulpitchford.garmin-insights
```

The command fetches the repository's default branch. If there are changes, Omarchy shows the diff and asks for confirmation, performs a fast-forward-only update, validates the resulting plugin, and tells the shell to rescan plugins. A validation failure is rolled back automatically. Local changes inside the installed checkout can prevent a fast-forward, so treat that checkout as managed code rather than a customization directory.

Release tags provide auditable version points, but the default branch is the delivery channel used by `omarchy plugin update`. Changes are therefore developed and reviewed on branches, and the default branch must remain installable. The permanent plugin ID keeps bar settings attached to the plugin, while tokens, account scope, the activity database, and the summary cache remain in their separate XDG locations during code updates.

Before 0.1, the roadmap adds optional update awareness to the top-level panel. A supported Git-managed checkout will compare its local commit with the fixed public default branch no more than once per 24 hours. A different commit will show **Update available** and a **Review update** action. That action will open the existing Omarchy command in a visible terminal, where the user still sees the diff and confirmation prompt. The plugin will not fetch and merge its own code. The check is planned to be enabled by default with an explicit setting to turn it off. Its unauthenticated request to GitHub will be documented before the feature is enabled.

Python application code is installed from the checkout in the dedicated environment. If an update only changes that source, the existing environment continues to use the updated checkout. If `pyproject.toml` or `uv.lock` changes, rerun the locked dependency setup in a visible terminal before relying on the updated backend:

```bash
PLUGIN_DIR="$HOME/.config/omarchy/plugins/io.github.paulpitchford.garmin-insights"
if [[ ${XDG_CACHE_HOME:-} = /* ]]; then
  CACHE_ROOT="$XDG_CACHE_HOME"
else
  CACHE_ROOT="$HOME/.cache"
fi

if [[ -x /usr/bin/uv ]]; then
  UV_BIN=/usr/bin/uv
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  UV_BIN="$HOME/.local/share/mise/shims/uv"
fi

UV_PROJECT_ENVIRONMENT="$CACHE_ROOT/omarchy-garmin-insights/uv-environment" \
  "$UV_BIN" --directory "$PLUGIN_DIR" sync --locked --no-dev
```

## Backend commands

The panel runs routine commands through `uv run --locked --no-sync`. To run the same backend manually, prepare these variables in a terminal:

```bash
PLUGIN_DIR="$HOME/.config/omarchy/plugins/io.github.paulpitchford.garmin-insights"
if [[ ${XDG_CACHE_HOME:-} = /* ]]; then
  CACHE_ROOT="$XDG_CACHE_HOME"
else
  CACHE_ROOT="$HOME/.cache"
fi
UV_PROJECT_ENVIRONMENT="$CACHE_ROOT/omarchy-garmin-insights/uv-environment"

if [[ -x /usr/bin/uv ]]; then
  UV_BIN=/usr/bin/uv
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  UV_BIN="$HOME/.local/share/mise/shims/uv"
fi

backend() {
  UV_PROJECT_ENVIRONMENT="$UV_PROJECT_ENVIRONMENT" \
    "$UV_BIN" --directory "$PLUGIN_DIR" run --locked --no-sync \
    omarchy-garmin-insights "$@"
}
```

Available commands:

```bash
backend doctor
backend doctor --json
backend auth status --json
backend auth login
backend auth logout --confirm
backend auth purge --confirm
backend refresh --json
backend refresh --json --full
```

Run `auth login` only in a visible interactive terminal. `auth status` checks local files and makes no Garmin request, so configured tokens remain "unverified" until login or refresh succeeds.

`auth logout --confirm` removes Garmin tokens but keeps the account scope, activity database, and summary cache. `auth purge --confirm` removes all known authentication and activity data. Purge does not remove the downloaded Python environment.

## Storage and privacy

The backend applies standard XDG defaults when state, data, or cache variables are unset.

| Data | Path | Retention |
|---|---|---|
| Garmin tokens | `$XDG_STATE_HOME/omarchy-garmin-insights/auth/garmin_tokens.json` | Until logout or purge |
| Account fingerprint | `$XDG_DATA_HOME/omarchy-garmin-insights/account_scope.json` | Until purge |
| Normalised activities | `$XDG_DATA_HOME/omarchy-garmin-insights/activities.sqlite3` | Current rolling 90 days |
| Interface summary | `$XDG_CACHE_HOME/omarchy-garmin-insights/summary.json` | Replaced after a successful refresh |
| Refresh lock | `$XDG_RUNTIME_DIR/omarchy-garmin-insights/sync.lock` | Runtime coordination only |
| Python environment | `$XDG_CACHE_HOME/omarchy-garmin-insights/uv-environment` | Until removed manually |

Defaults are `~/.local/state`, `~/.local/share`, and `~/.cache`. Private application data directories are secured to mode `0700`; private files use mode `0600`. Storage operations reject unsafe final symlinks, unexpected owners, non-regular files, and oversized private files.

The account fingerprint is a one-way SHA-256 value used to prevent data from two Garmin accounts being merged. The raw account identifier, email address, and Garmin profile response are not saved.

The activity allowlist contains Garmin activity ID, optional activity name, original type key, local start time and date, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, total sets, and total repetitions. Activity names, identifiers, and start times are excluded from the QML summary. Coordinates, routes, maps, raw responses, and complete profile data are not persisted.

See [SECURITY.md](SECURITY.md) for reporting instructions and the complete security boundary.

## Disconnect, purge, and remove

Disable the plugin before maintenance so its shared service does not start another refresh:

```bash
omarchy plugin disable io.github.paulpitchford.garmin-insights
```

To disconnect while retaining local activity data, run the [backend command setup](#backend-commands), then:

```bash
backend auth logout --confirm
```

To delete known Garmin tokens, account scope, activities, and summary data:

```bash
backend auth purge --confirm
```

Remove the plugin checkout separately:

```bash
omarchy plugin remove io.github.paulpitchford.garmin-insights
```

Plugin removal intentionally leaves local data and the Python environment in place. To remove the dependency environment after purge and plugin removal:

```bash
if [[ ${XDG_CACHE_HOME:-} = /* ]]; then
  CACHE_ROOT="$XDG_CACHE_HOME"
else
  CACHE_ROOT="$HOME/.cache"
fi
rm -rf -- "$CACHE_ROOT/omarchy-garmin-insights/uv-environment"
```

Purge leaves empty application directories and the runtime lock. They contain no Garmin data. You may remove empty directories with `rmdir`, and the runtime directory is normally cleared when the user session ends.

Neither logout nor purge revokes tokens on Garmin's servers. They only remove local files.

## Network access and dependencies

Setup downloads locked packages from `pypi.org` and `files.pythonhosted.org`. If Python 3.13 is unavailable, `uv` can download a managed CPython build from the `astral-sh/python-build-standalone` releases through `github.com` and `release-assets.githubusercontent.com`.

The backend runtime dependency set is:

| Package | Version | Relationship | Licence |
|---|---:|---|---|
| `garminconnect` | 0.3.11 | Direct | MIT |
| `curl-cffi` | 0.16.2 | Transitive | MIT |
| `certifi` | 2026.7.22 | Transitive | MPL-2.0 |
| `cffi` | 2.1.1 | Transitive | MIT-0 |
| `pycparser` | 3.0 | Transitive | BSD-3-Clause |
| `requests` | 2.34.2 | Transitive | Apache-2.0 |
| `charset-normalizer` | 3.5.1 | Transitive | MIT |
| `idna` | 3.19 | Transitive | BSD-3-Clause |
| `urllib3` | 2.7.0 | Transitive | MIT |
| `ua-generator` | 2.1.3 | Transitive | Apache-2.0 |

Versions, source archives, and hashes are fixed in `uv.lock`. Package metadata and installed licence files are authoritative for transitive notices. Direct dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Omarchy supplies the plugin host, Quickshell, Qt, `qs.Commons`, `qs.Ui`, and the terminal launcher. The repository does not redistribute those system components. `uv` supplies a compatible CPython runtime when one is not already available. A selected mise shim can also contact destinations configured by mise; that tool-manager traffic is outside the plugin's fixed package and Garmin host list.

Garmin authentication can contact:

- `sso.garmin.com`
- `connect.garmin.com`
- `connectapi.garmin.com`
- `diauth.garmin.com`
- `mobile.integration.garmin.com`

Activity refreshes use the read-only `/activitylist-service/activities/search/activities` endpoint on `connectapi.garmin.com` through `get_activities_by_date`, without an activity-type filter.

`python-garminconnect` is an unofficial client. Garmin may change or rate-limit the web services it uses.

### Commands executed by the plugin

The QML service uses fixed executable paths and direct argument arrays:

- `/usr/bin/test -x` checks the three accepted `uv` locations.
- `/usr/bin/env` sets only `UV_PROJECT_ENVIRONMENT` for each backend process.
- The selected `uv` runs `run --locked --no-sync omarchy-garmin-insights auth status --json` and `run --locked --no-sync omarchy-garmin-insights refresh --json` in the background.
- `/usr/share/omarchy/bin/omarchy-launch-terminal` opens visible setup and login terminals.
- Setup runs `uv sync --locked --no-dev`.
- Login runs `uv run --locked --no-sync omarchy-garmin-insights auth login`.

The Python backend does not start subprocesses. It reads and writes only the documented local paths and makes the documented Garmin requests.

## Troubleshooting

### Backend setup required

Install `uv` at one of the accepted paths listed under [Requirements](#requirements), then reopen the panel and select **Set up backend**. The plugin does not download or execute an installer for `uv`.

If setup was interrupted, select **Set up backend** again. The locked sync is idempotent.

### Connect or reconnect Garmin

Open the panel and select **Connect Garmin** or **Reconnect Garmin**. Authentication failures and HTTP 429 responses are not retried automatically. A rate limit should be allowed to expire before trying again.

If a different Garmin account reports `account_mismatch`, the retained data belongs to the previous account scope. Use logout to reconnect the same account, or purge explicitly before adopting a different account.

### Offline or stale summary

The plugin keeps the last valid cache after network failures, rate limiting, malformed Garmin data, an interrupted database update, or an interrupted cache write. It marks the summary stale rather than replacing missing measurements with zero.

Middle-click the widget or press `R` in the panel to retry. Only one refresh can run at a time. A refresh has a 120-second overall Garmin request deadline and at most one retry for transient network or server failures.

### No cached summary

A first successful refresh is needed before real data can be displayed. If the cache is missing or invalid, the backend rebuilds it after the next successful refresh. QML never queries SQLite directly.

### Local storage error

Run:

```bash
backend doctor
```

Check the reported XDG paths. The application directories and files must belong to the current user and must not be replaced with symlinks. A refresh also requires an absolute `XDG_RUNTIME_DIR`.

### Inspect safe machine output

Use the JSON forms of `doctor`, `auth status`, and `refresh`. Errors contain a reviewed code and fixed message. Unknown exception text, remote response bodies, credentials, and command arguments are not reflected in output.

Process exit categories are `0` for success, `2` for invalid arguments, `10` for configuration, `20` for authentication, `30` for network or Garmin service failures, `40` for invalid data, `50` for local storage, `60` for concurrency, and `70` for unexpected internal failures.

## Summary contract

Summary schema version 1 contains today, 7-day, 30-day, and 90-day periods. Today includes today. The other periods include today and the preceding 6, 29, or 89 local dates.

Every metric has a `contributingActivityCount`. A metric is `null` when no activity supplied a usable value; missing measurements are never converted to zero. Average heart rate and average power are weighted by activity duration. Average speed is weighted by moving duration. Values without a positive matching duration do not contribute. Maximum heart rate is the highest supplied value, and the remaining measurements are sums.

The cache is limited to 20,000 activities, 256 original activity type keys, and 1 MiB of JSON. Measurements remain in SI units until the QML presentation boundary.

## Development

The Python backend supports Python 3.12 and 3.13. Set up the development environment:

```bash
uv sync --locked --dev
```

Run the Python quality suite:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run pyscn check --max-complexity 12 --max-cycles 0 src
```

Run QML and Omarchy checks:

```bash
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests/qml
omarchy plugin validate "$PLUGIN_DIR"
/usr/lib/qt6/bin/qmllint -I "$OMARCHY_PATH/shell" \
  "$PLUGIN_DIR/BarWidget.qml" \
  "$PLUGIN_DIR/Panel.qml" \
  "$PLUGIN_DIR/Service.qml"
```

`PLUGIN_DIR` must point to a clean checkout or staging copy. A development tree containing `.venv` symlinks is intentionally rejected by Omarchy validation.

Tests and previews must use fabricated identities and activities. Do not add Garmin exports, tokens, FIT files, routes, coordinates, account details, or personal API responses to this repository.

## Disclaimer

This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Garmin, Omarchy, 37signals, or the Omarchy Plugins marketplace. Activity information is for personal reference and is not medical advice.

## License

This project is licensed under the [MIT License](LICENSE).
