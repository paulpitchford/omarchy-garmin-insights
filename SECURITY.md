# Security policy

## Reporting a vulnerability

Do not report credentials, personal activity data, account identifiers, precise locations, or exploit details in a public issue.

Report security problems through [GitHub private vulnerability reporting](https://github.com/paulpitchford/omarchy-garmin-insights/security/advisories/new). Include the affected version or commit, what you observed, and reproduction details that do not expose private Garmin data.

General bugs that contain no sensitive information may use the public issue tracker.

## Security boundaries

This plugin runs unsandboxed inside `omarchy-shell` with the current user's permissions. Its Python backend also runs as the current user. The project treats every command, dependency, file path, and remote response as a security boundary.

The implementation must:

- use only the reviewed Garmin operations needed for activity summaries and bounded daily wellness;
- collect credentials in a visible terminal with hidden password input;
- store tokens, activity data, and wellness scalars in owner-only XDG directories;
- avoid passing secrets in command arguments, environment variables, logs, notifications, or QML properties;
- normalise an allowlist of Garmin fields instead of persisting raw responses;
- exclude coordinates and route data from persistent storage;
- use direct process argument arrays for background commands;
- bound subprocess runtime and output;
- use an owner-only runtime directory for locks;
- pin Python dependencies in a reviewed lockfile;
- query only the fixed public repository when update checks are enabled; and
- require explicit confirmation before changing wellness collection, logging out, deleting local data, or updating code.

The plugin does not download FIT files and does not upload, edit, or delete Garmin account data. It does not request Stress, intraday heart-rate samples, Body Battery events, health snapshots, device or location data, hydration, weight, or blood pressure.

## Current authentication boundary

Authentication uses the PyPI release of `python-garminconnect` pinned in `pyproject.toml` and `uv.lock`. Login runs in a visible terminal and contacts only the documented Garmin hosts: `sso.garmin.com`, `connect.garmin.com`, `connectapi.garmin.com`, `diauth.garmin.com`, and `mobile.integration.garmin.com`. Password and MFA input is hidden, remains in the login process, and is never written to command output or local storage.

Tokens are stored at `$XDG_STATE_HOME/omarchy-garmin-insights/auth/garmin_tokens.json`. The application directories use mode `0700`, and private files use mode `0600`. Reads open final components in nonblocking no-follow mode and reject symlinks, non-regular files such as FIFOs, unexpected owners, and oversized content. The backend stores a pseudonymous account fingerprint separately so tokens for another account cannot be used with existing local activity or wellness data.

`auth logout --confirm` removes only the token file. `auth purge --confirm` removes the token, account scope, activity and wellness database, and all Garmin display caches. Neither command makes a Garmin request or revokes server-side tokens. Login, logout, purge, collection changes, activity refreshes, and wellness refreshes use the same lock when a private runtime directory is available, so state-changing operations cannot overlap.

## Current synchronization boundary

`refresh` restores only the plugin's dedicated tokens and calls `get_activities_by_date` without an activity-type filter. It uses at most one transient retry and has a 120-second overall Garmin request deadline. Authentication failures and rate limits fail immediately. An owner-only lock at `$XDG_RUNTIME_DIR/omarchy-garmin-insights/sync.lock` prevents overlapping refreshes.

The backend validates a maximum of 20,000 activities per refresh. It keeps only reviewed summary fields and drops every other response field before persistence. The SQLite database contains no coordinates, routes, maps, raw responses, account IDs, or email addresses. Reconciliation and deletion happen in one transaction, and full reconciliations retain only the rolling 90-day window. The separate bounded activity-trends cache is derived from that normalized snapshot without another Garmin request and contains only calendar buckets, aggregate metrics, and contributor counts; it excludes activity identity, names, types, times, and locations.

`wellness refresh` verifies the account through the fixed social-profile request, then calls only the documented Steps, Body Battery, Sleep, HRV, resting-heart-rate, and Training Readiness methods from pinned `garminconnect==0.3.11`. A command has a 120-second Garmin deadline, at most 18 data calls, one verification call, and one retry of one transport or HTTP 5xx failure, with no more than 20 HTTP attempts. Authentication failures and HTTP 429 do not retry. The QML service runs activity and wellness commands sequentially under a 249-second combined deadline.

Project-owned boundary parsers reject malformed values, dates, ranges, duplicates, oversized lists, non-finite numbers, and unsafe text. They discard every unapproved field. The database retains only 30 dates of approved daily scalars. Body Battery samples and Training Readiness selection timestamps are transient and never reach persistence or presentation. Each source commits separately, so a failed or unsupported source cannot roll back another source's successful transaction.

The wellness endpoint allowlist is `/usersummary-service/usersummary/daily/{displayName}`, `/usersummary-service/stats/steps/daily/{start}/{end}`, `/wellness-service/wellness/bodyBattery/reports/daily`, `/sleep-service/stats/sleep/daily/{start}/{end}`, `/wellness-service/wellness/dailySleepData/{displayName}`, `/hrv-service/hrv/daily/{start}/{end}`, `/hrv-service/hrv/{date}`, `/userstats-service/wellness/daily/{displayName}` with metric ID 60, and `/metrics-service/metrics/trainingreadiness/{date}`. Account verification uses `/userprofile-service/socialProfile`. These requests go to the documented Garmin hosts listed in README.

`wellness collection --enable|--disable --confirm` changes private local state without contacting Garmin or deleting retained rows. A disabled state prevents account verification and every later wellness request. Logout retains the account-scoped wellness data; purge removes it. A different authenticated account is rejected before a wellness transaction.

The QML service does not read predictable display-cache paths through `FileView`. It runs the fixed `cache read` backend command, which applies the private-file checks above and the per-kind byte cap before returning a bounded envelope. QML applies a five-second deadline, validates the summary, activity-trends, or wellness contract, and preserves previous valid in-memory state when a read fails. Activity and wellness display state remain separate.

Activity drill-down reads SQLite locally in fixed pages of at most 20 and returns a separate bounded detail contract. These commands do not authenticate, refresh, or contact Garmin. They expose only allowlisted fields, never complete URLs or location data. The browser action accepts a validated decimal activity ID and constructs the fixed Garmin Connect HTTPS destination in QML.

## Current update boundary

Update checks are optional and enabled by default. They run only for the documented Git-managed install path, `main` branch, and exact public HTTPS origin. The service reads the local commit and runs a bounded `/usr/bin/git ls-remote` query against `https://github.com/paulpitchford/omarchy-garmin-insights.git` and `refs/heads/main`. Git configuration rewrites and interactive credential prompts are disabled for the query. No Garmin token, account data, activity data, analytics identifier, or telemetry is sent.

The private update cache stores only the last-attempt timestamp and validated public commit IDs. Automatic checks run at most once per 24 hours. Failures do not alter Garmin state or cached activities. The plugin never fetches, merges, or edits its checkout. **Review update** opens Omarchy's terminal update flow without `--yes`, so the user sees the diff and confirms the fast-forward update. A shell restart is required after an accepted update and any dependency sync.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| Earlier versions | No |

Security fixes are released from the default branch. Update through Omarchy's reviewed plugin update flow before reporting a problem that has already been fixed.
