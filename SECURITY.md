# Security policy

## Reporting a vulnerability

Do not report credentials, personal activity data, account identifiers, precise locations, or exploit details in a public issue.

Report security problems through [GitHub private vulnerability reporting](https://github.com/paulpitchford/omarchy-garmin-activities/security/advisories/new). Include the affected version or commit, what you observed, and reproduction details that do not expose private Garmin data.

General bugs that contain no sensitive information may use the public issue tracker.

## Security boundaries

This plugin will run unsandboxed inside `omarchy-shell` with the current user's permissions. Its Python backend will also run as the current user. The project therefore treats every command, dependency, file path, and remote response as a security boundary.

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

The first release will not download FIT files and will not upload, edit, or delete Garmin account data.

## Supported versions

The project is not yet released. A supported-version policy will be published with the first release.
