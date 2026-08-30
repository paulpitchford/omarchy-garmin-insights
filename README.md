# Garmin Insights for Omarchy

Garmin Insights is an Omarchy Quattro bar plugin for recent Garmin Connect activities and bounded daily wellness data. It covers activity periods from today through the last 90 calendar days and keeps 30 days of approved wellness values.

![Garmin Insights Overview showing fabricated activity and wellness data](preview.png)

Current release: [`v0.1.1`](https://github.com/paulpitchford/omarchy-garmin-insights/releases/tag/v0.1.1)

The plugin ID is `io.github.paulpitchford.garmin-insights`.

## Screenshots

These screenshots use the plugin's built-in synthetic demo. They contain no data from a Garmin account.

| Wellness Today | Wellness Trends |
|---|---|
| ![Fabricated Wellness Today in Garmin Insights](screenshots/wellness-today.png) | ![Fabricated Training Readiness trend in Garmin Insights](screenshots/wellness-trends.png) |

| Activity list | Activity detail |
|---|---|
| ![Fabricated activity list in Garmin Insights](screenshots/activity-list.png) | ![Fabricated strength activity details in Garmin Insights](screenshots/activity-detail.png) |

## What it does

- Opens on an Overview with current Body Battery, Sleep, and Steps signals alongside the weekly activity chart and latest activity.
- Shows Training Readiness, Body Battery, Sleep, Steps, HRV, and resting heart rate in a separate Wellness view.
- Charts one wellness metric family at a time over 7 or 30 days. Sleep has Score, Duration, and Stages views.
- Shows activity count, duration, distance, and energy for the selected period.
- Charts activity time, distance, elevation gain, or energy across 7 and 30 daily points or 13 trailing buckets for 90 days.
- Adds proportional count fills behind the existing activity-type rows while keeping their exact values and drill-down actions.
- Opens a bounded local activity list for a period or original Garmin activity type.
- Shows the stored allowlisted details for one activity and can explicitly open it on Garmin Connect.
- Breaks totals down by Garmin's original activity type, including types the plugin does not already know.
- Supports metric, imperial, or locale-selected units.
- Keeps a rolling 90-day activity window, 30 days of wellness scalars, and separate bounded display caches.
- Refreshes activities every 30 minutes by default. Wellness uses independent 30-minute, four-hour, daily, weekly, and one-hour backfill limits according to source and request type.
- Keeps each domain's last valid data while offline and makes bounded activity recovery attempts after resume or a connectivity failure.
- Checks supported Git-managed installs for updates at most once per 24 hours and opens Omarchy's review flow on request.
- Uses a visible terminal for Garmin login and supports MFA in the same login process.
- Works on horizontal and vertical bars and shares one refresh service across monitors.
- Includes a synthetic demo mode that does not contact Garmin.

The plugin reads activity summaries and the approved daily wellness endpoints listed below. It does not upload, edit, schedule, or delete Garmin data, and it does not download FIT files or routes. It does not request Stress, intraday heart-rate samples, Body Battery events, health snapshots, device data, location data, hydration, weight, or blood-pressure data.

Activity drill-down is local-only. It does not make another Garmin API request or download routes, maps, or FIT files. The external action uses the fixed `https://connect.garmin.com/app/activity/<activity-id>` pattern after validating the decimal identifier. Garmin data cannot provide a URL, host, scheme, path, or command. The browser uses its own Garmin session; plugin OAuth tokens are not passed to it.

## Scope not included

Stress, intensity minutes, floors, daily calories, wellness bar rotation, user-reordered cards, a 90-day heatmap, intraday Body Battery, sleep start and end times, correlations, coaching, alerts, thresholds, and medical interpretation are not included. Garmin China support remains an open decision.

## Requirements

- Omarchy with the Quattro shell plugin commands (`omarchy plugin` and `omarchy bar`).
- `/usr/bin/python3`, supplied by Omarchy and used for the stdlib-only cache permission preflight and update-check state helper.
- `/usr/bin/git`, supplied by Omarchy and used for local checkout validation and the fixed-repository update query.
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

A successful login starts a sequential activity and wellness refresh. The first activity refresh of each local calendar day reconciles the complete rolling 90-day window; later activity refreshes reconcile a seven-day overlap. Wellness starts with a 30-day reconciliation, then follows the bounded cadence described under [Wellness contract](#wellness-contract). One domain can succeed and update while the other fails.

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
- In the panel, use Left and Right across Overview, Wellness, Activities, and Settings. Arrow keys move through each page and Enter activates the selected control.
- Wellness Today and Trends keep their selection while the panel is open. Trends expose exact dated values through pointer and keyboard paths.
- In a list, use Up and Down to select an activity, Right or Enter to open details, and Left or Escape to go back.
- In a detail view, choose **Open in Garmin Connect** explicitly; Left or Escape returns to the list.
- Press `R` to refresh both domains sequentially, Tab to switch panels, and Escape to cancel a confirmation, unwind a nested page, or close the panel.

Mouse users can open Wellness, browse activities, select an original activity type, open a list row, and use the explicit Garmin Connect action. Activity and wellness charts provide exact values through their documented pointer or keyboard paths. When content is taller than the fitted panel, a vertical scrollbar appears while the header refresh control and footer help remain visible. Lists contain at most 20 rows per page. The horizontal bar still shows the selected activity period's count. A vertical bar uses an icon-only form.

Settings can stop or enable future wellness collection after explicit confirmation. Stopping collection retains existing wellness rows and caches. Logout removes tokens but keeps local activity and wellness data. Purge removes authentication, the account database, and activity and wellness display caches. These are separate confirmed actions under **Account and data**.

### Settings

Settings can be changed through the Omarchy bar settings interface or with `omarchy bar set`:

| Setting | Values | Default |
|---|---|---|
| `period` | `today`, `7Days`, `30Days`, `90Days` | `7Days` |
| `units` | `auto`, `metric`, `imperial` | `auto` |
| `refreshMinutes` | 5 to 360 | 30 |
| `checkForUpdates` | `true`, `false` | `true` |
| `demoMode` | `true`, `false` | `false` |

Examples:

```bash
omarchy bar set io.github.paulpitchford.garmin-insights period 30Days
omarchy bar set io.github.paulpitchford.garmin-insights units metric
omarchy bar set io.github.paulpitchford.garmin-insights refreshMinutes 60 --json
omarchy bar set io.github.paulpitchford.garmin-insights checkForUpdates false --json
```

## Update

The plugin checks for updates but never changes its checkout. Update checks are enabled by default. A supported install must be a real Git checkout at the documented plugin path, on `main`, with the exact `https://github.com/paulpitchford/omarchy-garmin-insights.git` origin. Copied or symlinked plugins, worktrees, detached heads, other branches, changed origins, Git configuration includes, and URL rewrites do not use this feature.

The shared service waits 30 seconds after startup, then uses `/usr/bin/git ls-remote` to compare the installed commit with the fixed `refs/heads/main` commit. It records the attempt in the private cache so automatic checks run no more than once per 24 hours, including after a shell restart. **Check again** is an explicit exception to that cadence. Empty, malformed, oversized, failed, offline, or timed-out results are ignored and do not change Garmin status or cached Garmin data.

When the commits differ, Settings shows **Update available**. Select **Review update** to open a visible terminal running the following command without `--yes`:

```bash
omarchy plugin update io.github.paulpitchford.garmin-insights
```

The command fetches the repository's default branch. If there are changes, Omarchy shows the diff and asks for confirmation, performs a fast-forward-only update, validates the resulting plugin, and tells the shell to rescan plugins. A validation failure is rolled back automatically. Local changes inside the installed checkout can prevent a fast-forward, so treat that checkout as managed code rather than a customization directory.

A rescan does not reliably replace QML components and singleton services that are already loaded. After updating, complete any dependency sync described below, then restart the shell:

```bash
omarchy restart shell
```

The restart replaces the existing Quickshell process; it does not start a second shell. Bar settings and Garmin data remain in their separate configuration and XDG paths.

Release tags provide auditable version points, but the default branch is the delivery channel used by `omarchy plugin update`. Changes are therefore developed and reviewed on branches, and the default branch must remain installable. The permanent plugin ID keeps bar settings attached to the plugin, while tokens, account scope, the database, and display caches remain in their separate XDG locations during code updates.

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
omarchy restart shell
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
backend wellness refresh --json
backend wellness refresh --json --manual
backend wellness collection --disable --confirm
backend wellness collection --enable --confirm
backend cache read --json --kind summary
backend cache read --json --kind activity-trends
backend cache read --json --kind wellness
backend activities list --json --period 7Days --as-of 2026-08-26
backend activities list --json --period 30Days --as-of 2026-08-26 --type-key running --offset 20
backend activities detail --json --activity-id 900000000001
```

Run `auth login` only in a visible interactive terminal. `auth status` checks local files and makes no Garmin request, so configured tokens remain "unverified" until login or refresh succeeds.

`wellness refresh --manual` bypasses current-value cadence but not historical reconciliation or backfill cooldowns. A collection change requires `--confirm`, makes no Garmin request, and does not delete retained data.

`auth logout --confirm` removes Garmin tokens but keeps the account scope, activity and wellness database rows, and display caches. `auth purge --confirm` removes all known Garmin authentication, activity data, wellness data, and display caches. Purge does not remove the downloaded Python environment.

## Storage and privacy

The backend and update helper use the same XDG paths. Standard defaults apply when state, data, or cache variables are unset.

| Data | Path | Retention |
|---|---|---|
| Garmin tokens | `$XDG_STATE_HOME/omarchy-garmin-insights/auth/garmin_tokens.json` | Until logout or purge |
| Account fingerprint | `$XDG_DATA_HOME/omarchy-garmin-insights/account_scope.json` | Until purge |
| Normalised activities and daily wellness scalars | `$XDG_DATA_HOME/omarchy-garmin-insights/activities.sqlite3` | Activities: rolling 90 days; wellness: rolling 30 days |
| Interface summary | `$XDG_CACHE_HOME/omarchy-garmin-insights/summary.json` | Replaced after a successful activity refresh |
| Activity trends | `$XDG_CACHE_HOME/omarchy-garmin-insights/activity-trends.json` | Replaced after a successful activity refresh when generation succeeds |
| Wellness presentation | `$XDG_CACHE_HOME/omarchy-garmin-insights/wellness.json` | Replaced after successful source commits when generation succeeds |
| Update-check metadata | `$XDG_CACHE_HOME/omarchy-garmin-insights/update-check.json` | Last attempt and compared commit IDs |
| Refresh lock | `$XDG_RUNTIME_DIR/omarchy-garmin-insights/sync.lock` | Runtime coordination only |
| Update-check lock | `$XDG_RUNTIME_DIR/omarchy-garmin-insights/update-check.lock` | Runtime coordination only |
| Python environment | `$XDG_CACHE_HOME/omarchy-garmin-insights/uv-environment` | Until removed manually |

Defaults are `~/.local/state`, `~/.local/share`, and `~/.cache`. Private application data directories are secured to mode `0700`; private files use mode `0600`. Storage operations reject unsafe final symlinks, unexpected owners, non-regular files, and oversized private files.

The long-lived QML service does not open display-cache paths. It invokes the short-lived `cache read` backend command with a fixed reviewed cache kind. The backend opens the final component without following symlinks and in nonblocking mode, verifies that it is a regular owner-owned file, and reads no more than that contract's byte limit. The QML service applies a five-second command deadline and validates the bounded response before replacing in-memory state.

The account fingerprint is a one-way SHA-256 value used to prevent data from two Garmin accounts being merged. The raw account identifier, email address, display name, and Garmin profile response are not saved. Private wellness cadence and collection state stay in SQLite and never enter the display contract. Update-check metadata contains only a timestamp and validated public Git commit IDs. It contains no Garmin account, activity, or wellness data.

The activity allowlist contains Garmin activity ID, optional activity name, original type key, local start time and date, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, total sets, and total repetitions. Activity names, identifiers, type strings, and start times are excluded from the activity-trends cache; summary schema version 1 also excludes names, identifiers, and start times. Separate bounded list and detail responses expose only the fields needed for an explicit local drill-down. Coordinates, routes, maps, raw responses, complete URLs, and complete profile data are not persisted or returned by those contracts.

Wellness storage contains only the local date and approved daily scalars: Steps and Garmin's goal; Body Battery charged, drained, low, high, and latest; Sleep score, duration, and stage durations; Training Readiness score and Garmin level; HRV averages, Garmin status, and balanced baseline bounds; and resting heart rate. Body Battery samples and Training Readiness selection timestamps are discarded at the boundary. Missing values stay null, explicit zero remains zero, and remote status text is displayed only as plain text.

See [SECURITY.md](SECURITY.md) for reporting instructions and the complete security boundary.

## Disconnect, purge, and remove

Disable the plugin before maintenance so its shared service does not start another refresh:

```bash
omarchy plugin disable io.github.paulpitchford.garmin-insights
```

To stop future wellness requests without disconnecting or deleting retained data, run the [backend command setup](#backend-commands), then:

```bash
backend wellness collection --disable --confirm
```

To disconnect while retaining local activity and wellness data:

```bash
backend auth logout --confirm
```

To delete known Garmin tokens, account scope, activities, wellness data, and display caches:

```bash
backend auth purge --confirm
```

Remove the plugin checkout separately:

```bash
omarchy plugin remove io.github.paulpitchford.garmin-insights
```

Plugin removal intentionally leaves local data, update-check metadata, and the Python environment in place. To remove the dependency environment and non-sensitive update-check metadata after purge and plugin removal:

```bash
if [[ ${XDG_CACHE_HOME:-} = /* ]]; then
  CACHE_ROOT="$XDG_CACHE_HOME"
else
  CACHE_ROOT="$HOME/.cache"
fi
rm -rf -- "$CACHE_ROOT/omarchy-garmin-insights/uv-environment"
rm -f -- "$CACHE_ROOT/omarchy-garmin-insights/update-check.json"
rmdir -- "$CACHE_ROOT/omarchy-garmin-insights" 2>/dev/null || true
```

Purge leaves application directories, runtime locks, and update-check metadata. None of these contains Garmin data after purge. The runtime directory is normally cleared when the user session ends.

Neither logout nor purge revokes tokens on Garmin's servers. They only remove local files.

## Network access and dependencies

Setup downloads locked packages from `pypi.org` and `files.pythonhosted.org`. If Python 3.13 is unavailable, `uv` can download a managed CPython build from the `astral-sh/python-build-standalone` releases through `github.com` and `release-assets.githubusercontent.com`.

An enabled update check makes an ordinary unauthenticated Git HTTPS request to `https://github.com/paulpitchford/omarchy-garmin-insights.git`. It sends no Garmin token, account data, activity data, analytics identifier, referrer, or telemetry. GitHub and the network path still receive the normal connection metadata, such as the source IP address and TLS request details. Set `checkForUpdates` to `false` to disable this request.

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

Activity refreshes use the read-only `/activitylist-service/activities/search/activities` endpoint on `connectapi.garmin.com` through `get_activities_by_date`, without an activity-type filter. List and detail reads use SQLite only and make no network request. The explicit detail action opens `https://connect.garmin.com/app/activity/<validated-decimal-id>` in the default browser.

A wellness command verifies the account with `/userprofile-service/socialProfile`, then uses only these read-only endpoint shapes from `garminconnect==0.3.11`:

- `/usersummary-service/usersummary/daily/{displayName}` for the current Steps, goal, and resting heart rate summary;
- `/usersummary-service/stats/steps/daily/{start}/{end}` for daily Steps;
- `/wellness-service/wellness/bodyBattery/reports/daily` for daily Body Battery reduction;
- `/sleep-service/stats/sleep/daily/{start}/{end}` and `/wellness-service/wellness/dailySleepData/{displayName}` for Sleep;
- `/hrv-service/hrv/daily/{start}/{end}` and `/hrv-service/hrv/{date}` for HRV;
- `/userstats-service/wellness/daily/{displayName}` with metric ID 60 for resting heart rate; and
- `/metrics-service/metrics/trainingreadiness/{date}` for Training Readiness.

One wellness command makes at most one verification call, 18 planned data calls, and one retry of a single transport or HTTP 5xx failure, with no more than 20 HTTP attempts in total and a 120-second Garmin deadline. Authentication failures and HTTP 429 do not retry. The shared QML service runs activity and wellness commands sequentially under a 249-second combined deadline. Both backend commands use the same owner-only lock.

`python-garminconnect` is an unofficial client. Garmin may change or rate-limit the web services it uses.

### Commands executed by the plugin

The QML service uses fixed executable paths and direct argument arrays:

- `/usr/bin/test -x` checks the three accepted `uv` locations.
- `/usr/bin/python3` runs the tracked stdlib-only cache bootstrap before uv, rejecting unsafe paths and securing `$XDG_CACHE_HOME/omarchy-garmin-insights` as mode `0700`.
- `/usr/bin/python3` also runs the tracked update helper to validate the installed checkout and atomically claim or record the 24-hour cadence. The helper does not make network requests or start subprocesses.
- `/usr/bin/git` reads the supported checkout's top level, branch, and local commit with bounded direct commands. It queries only the fixed public repository and `refs/heads/main`, with interactive credentials and Git configuration rewrites disabled.
- `/usr/bin/env` sets only `UV_PROJECT_ENVIRONMENT` for each backend process.
- The selected `uv` runs `run --locked --no-sync omarchy-garmin-insights auth status --json`, sequential activity and wellness refreshes, confirmed local collection/logout/purge actions, fixed-kind cache reads, and bounded activity list or detail reads in the background.
- `/usr/bin/xdg-open` opens the installed local `README.md` when **Help and privacy** is selected.
- `/usr/share/omarchy/bin/omarchy-launch-terminal` opens visible setup, login, and update-review terminals.
- Setup runs `uv sync --locked --no-dev`.
- Login runs `uv run --locked --no-sync omarchy-garmin-insights auth login`.
- Update review runs `/usr/bin/omarchy plugin update io.github.paulpitchford.garmin-insights` without `--yes`.

The Python backend does not start subprocesses. It reads and writes only the documented local paths and makes the documented Garmin requests.

## Troubleshooting

### No update indicator

The update controls appear only for the supported checkout described in [Update](#update). Confirm that the plugin is installed at `~/.config/omarchy/plugins/io.github.paulpitchford.garmin-insights`, its origin is the exact public HTTPS URL, and it is attached to `main`. The controls stay hidden for copied, symlinked, detached, locally reconfigured, or otherwise unsupported checkouts.

Automatic checks wait 30 seconds and then respect the 24-hour cache. Use **Check again** for a manual query. GitHub being offline, a timeout, or an invalid response does not create a Garmin error banner. Check normal HTTPS connectivity to GitHub if a manual check produces no result.

### Updated files but old interface

If `omarchy plugin update` reports success but the panel still shows the previous interface, run:

```bash
omarchy restart shell
```

Plugin rescanning and file watching do not reliably evict QML components that are already loaded. Confirm the installed checkout moved to the expected commit as well as checking the visible interface.

### Backend setup required

Install `uv` at one of the accepted paths listed under [Requirements](#requirements), then reopen the panel and select **Set up backend**. The plugin does not download or execute an installer for `uv`.

If setup was interrupted, select **Set up backend** again. The locked sync is idempotent.

### Connect or reconnect Garmin

Open the panel and select **Connect Garmin** or **Reconnect Garmin**. Authentication failures and HTTP 429 responses are not retried automatically. A rate limit should be allowed to expire before trying again.

If a different Garmin account reports `account_mismatch`, the retained data belongs to the previous account scope. Use logout to reconnect the same account, or purge explicitly before adopting a different account.

### Offline or stale summary

The plugin keeps the last valid cache after network failures, rate limiting, malformed Garmin data, an interrupted database update, or an interrupted cache write. It marks the summary stale rather than replacing missing measurements with zero.

After a suspend-length timer gap, the shared service waits 15 seconds for networking to settle before making a normal refresh. An offline or remote-service result can then schedule at most two more refresh commands, after 30 seconds and two minutes. A successful refresh clears the offline state. Authentication expiry, rate limiting, and local storage failures do not use this recovery sequence. The plugin does not run a generic internet probe or add a connectivity-tracking service.

Middle-click the widget or press `R` in the panel to retry immediately; a manual refresh uses any already pending recovery attempt rather than starting an overlapping request. Only one refresh can run at a time. Each backend refresh has a 120-second overall Garmin request deadline and at most one retry for transient network or server failures.

### No cached summary

A first successful activity refresh is needed before real activity data can be displayed. If a display cache is missing or invalid, the relevant backend refresh rebuilds it after a successful commit. QML never queries SQLite directly.

### Missing or unsupported wellness values

A missing source or metric stays unavailable rather than becoming zero. A source-level 404 is shown as unsupported, while an empty date remains missing. Valid retained values keep their dates after an isolated source failure. Device and account support varies, so one unsupported source does not hide other wellness categories or activity data.

Stopping wellness collection prevents every future wellness request but keeps retained rows and presentation data. Use **Settings > Wellness collection** or `backend wellness collection --enable --confirm` to resume. Re-enabling starts a bounded refresh; it does not bypass historical or backfill cooldowns.

### Local storage error

Run:

```bash
backend doctor
```

Check the reported XDG paths. The application directories and files must belong to the current user and must not be replaced with symlinks. A refresh also requires an absolute `XDG_RUNTIME_DIR`.

### Inspect safe machine output

Use the JSON forms of `doctor`, `auth status`, `refresh`, `wellness refresh`, `wellness collection`, `cache read`, `activities list`, and `activities detail`. Errors contain a reviewed code and fixed message. Unknown exception text, SQL details, remote response bodies, credentials, and command arguments are not reflected in output.

Process exit categories are `0` for success, `2` for invalid arguments, `10` for configuration, `20` for authentication, `30` for network or Garmin service failures, `40` for invalid data, `50` for local storage, `60` for concurrency, and `70` for unexpected internal failures.

## Summary contract

Summary schema version 1 contains today, 7-day, 30-day, and 90-day periods. Today includes today. The other periods include today and the preceding 6, 29, or 89 local dates.

Every metric has a `contributingActivityCount`. A metric is `null` when no activity supplied a usable value; missing measurements are never converted to zero. Average heart rate and average power are weighted by activity duration. Average speed is weighted by moving duration. Values without a positive matching duration do not contribute. Maximum heart rate is the highest supplied value, and the remaining measurements are sums.

The cache is limited to 20,000 activities, 256 original activity type keys, and 1 MiB of JSON. Measurements remain in SI units until the QML presentation boundary.

## Activity-trends contract

Activity-trends schema version 1 is a separate optional cache generated from the same normalized 90-day SQLite snapshot after reconciliation. It makes no additional Garmin request. The 7- and 30-day periods contain daily points. The 90-day period contains one six-day oldest bucket followed by twelve seven-day buckets, all anchored to the summary's local end date.

Each point contains only its calendar boundaries, partial-current-period marker, activity count, and summed duration, distance, elevation, and energy with contributor counts. It contains no activity identifiers, names, start times, type strings, routes, coordinates, or raw responses. A day or bucket with no activities is an explicit zero. If activities exist but none supplied a metric, that metric remains `null`. QML validates the complete shape and displays trends only when their generation timestamp, dates, and activity counts match the current summary. Missing, stale, malformed, oversized, or unwritable trends do not replace or hide a valid summary.

The trend cache is capped at 50 points and 64 KiB, written atomically with mode `0600`, and removed by explicit purge. Measurements remain in SI units. The Activities view can chart time, distance, elevation gain, or energy, one metric at a time.

## Wellness contract

Wellness presentation schema version 1 always contains 30 ordered local dates ending on `asOfLocalDate`. Every date has fixed nullable groups for the approved scalars. It also contains 7-day and 30-day contributor counts for each scalar, the seven source states with freshness and a stable failure classification, collection state, and current-day partial markers for Steps and Body Battery. It contains no account scope, request metadata, exception text, timestamps used to select a readiness snapshot, or remote extras. The cache is capped at 64 KiB.

Today is the machine's local date. Sleep belongs to Garmin's returned calendar date for the night ending on that date. Range-capable sources receive an initial 30-day reconciliation and another full reconciliation no more than once per seven local dates; other local dates use a seven-day overlap. Current Steps and Body Battery can refresh every 30 minutes. Current Sleep and Training Readiness can refresh every four hours. Detailed Sleep backfill targets the current seven dates, while Training Readiness backfill targets the retained 30 dates. Backfill selects at most two dates per source, four single-date calls per command, and has a one-hour cooldown.

Each successful source commits and updates its own freshness independently. Invalid, unsupported, interrupted, or failed sources keep their previous rows and freshness. A null does not overwrite a retained non-null value. Disabling collection is idempotent and makes no Garmin request. Logout retains wellness rows; purge removes them.

## Activity drill-down contracts

`activities list` accepts one reviewed period key, the summary's local end date, an optional original type key, and a page offset. It returns newest-first local records in fixed pages of at most 20, with `hasMore` and a bounded next offset. Older summary dates are marked stale. `activities detail` accepts only a canonical decimal activity ID and returns either the complete allowlisted local record or `{\"found\":false,\"activity\":null}` if reconciliation removed it.

Both commands open SQLite read-only, apply a two-second query deadline, cap JSON at 64 KiB, validate every field again before serialization, and never authenticate, refresh, or contact Garmin. QML applies the same shape, value, string, ordering, identifier, and size checks before displaying a response. Missing metrics remain absent from the detail view rather than appearing as zero.

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
  "$PLUGIN_DIR/PanelShell.qml" \
  "$PLUGIN_DIR/PanelSession.qml" \
  "$PLUGIN_DIR/OverviewShellPage.qml" \
  "$PLUGIN_DIR/WellnessShellPage.qml" \
  "$PLUGIN_DIR/WellnessTrendChart.qml" \
  "$PLUGIN_DIR/ActivitiesView.qml" \
  "$PLUGIN_DIR/SettingsView.qml" \
  "$PLUGIN_DIR/DomainStatusRow.qml" \
  "$PLUGIN_DIR/ActivityTimeChart.qml" \
  "$PLUGIN_DIR/Service.qml"
```

`PLUGIN_DIR` must point to a clean checkout or staging copy. A development tree containing `.venv` symlinks is intentionally rejected by Omarchy validation.

Tests and previews must use fabricated identities and activities. Do not add Garmin exports, tokens, FIT files, routes, coordinates, account details, or personal API responses to this repository.

## Disclaimer

This is an independent community project. It is not affiliated with, sponsored by, or endorsed by Garmin, Omarchy, 37signals, or the Omarchy Plugins marketplace. Activity information is for personal reference and is not medical advice.

## License

This project is licensed under the [MIT License](LICENSE).
