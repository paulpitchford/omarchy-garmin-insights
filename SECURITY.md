# Security policy

## Reporting a vulnerability

Do not report credentials, personal activity data, account identifiers, precise locations, or exploit details in a public issue.

Report security problems through [GitHub private vulnerability reporting](https://github.com/paulpitchford/omarchy-garmin-insights/security/advisories/new). Include the affected version or commit, what you observed, and reproduction details that do not expose private Garmin data.

General bugs that contain no sensitive information may use the public issue tracker.

## Security boundaries

This plugin runs unsandboxed inside `omarchy-shell` with the current user's permissions. Its Python backend also runs as the current user. The project treats every command, dependency, file path, and remote response as a security boundary.

The implementation must:

- use only the Garmin operations needed to read activity summaries;
- collect credentials in a visible terminal with hidden password input;
- store tokens and activity data in owner-only XDG directories;
- avoid passing secrets in command arguments, environment variables, logs, notifications, or QML properties;
- normalise an allowlist of Garmin fields instead of persisting raw responses;
- exclude coordinates and route data from persistent storage;
- use direct process argument arrays for background commands;
- bound subprocess runtime and output;
- use an owner-only runtime directory for locks;
- pin Python dependencies in a reviewed lockfile; and
- require explicit confirmation before logout or local data deletion.

The plugin does not download FIT files and does not upload, edit, or delete Garmin account data.

## Current authentication boundary

Authentication uses the PyPI release of `python-garminconnect` pinned in `pyproject.toml` and `uv.lock`. Login runs in a visible terminal and contacts only the documented Garmin hosts: `sso.garmin.com`, `connect.garmin.com`, `connectapi.garmin.com`, `diauth.garmin.com`, and `mobile.integration.garmin.com`. Password and MFA input is hidden, remains in the login process, and is never written to command output or local storage.

Tokens are stored at `$XDG_STATE_HOME/omarchy-garmin-insights/auth/garmin_tokens.json`. The application directories use mode `0700`, and private files use mode `0600`. Reads and removals reject symlinks, non-regular files, unexpected owners, and oversized content. The backend stores a pseudonymous account fingerprint separately so tokens for another account cannot be used with existing local activity data.

`auth logout --confirm` removes only the token file. `auth purge --confirm` removes the token, account scope, and all other allowlisted plugin data files. Neither command makes a Garmin request or revokes server-side tokens. Login, logout, and purge use the activity lock when a private runtime directory is available, so they cannot race a refresh.

## Current synchronization boundary

`refresh` restores only the plugin's dedicated tokens and calls `get_activities_by_date` without an activity-type filter. It uses at most one transient retry and has a 120-second overall Garmin request deadline. Authentication failures and rate limits fail immediately. An owner-only lock at `$XDG_RUNTIME_DIR/omarchy-garmin-insights/sync.lock` prevents overlapping refreshes.

The backend validates a maximum of 20,000 activities per refresh. It keeps only reviewed summary fields and drops every other response field before persistence. The SQLite database contains no coordinates, routes, maps, raw responses, account IDs, or email addresses. Reconciliation and deletion happen in one transaction, and full reconciliations retain only the rolling 90-day window.

Activity drill-down reads SQLite locally in fixed pages of at most 20 and returns a separate bounded detail contract. These commands do not authenticate, refresh, or contact Garmin. They expose only allowlisted fields, never complete URLs or location data. The browser action accepts a validated decimal activity ID and constructs the fixed Garmin Connect HTTPS destination in QML.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| Earlier versions | No |

Security fixes are released from the default branch. Update through Omarchy's reviewed plugin update flow before reporting a problem that has already been fixed.
