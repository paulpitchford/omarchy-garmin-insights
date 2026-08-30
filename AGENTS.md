# Repository guidelines

## Purpose

Build and maintain Garmin Insights for Omarchy, a public Quattro bar plugin that shows recent Garmin Connect activity summaries and, from 0.2, bounded daily wellness insights. The plugin must be useful to people with different activity types, devices, units, wellness support, and amounts of recorded data.

Keep this file current when architecture, security boundaries, development commands, or release rules change. Keep `README.md` accurate for users. Do not advertise incomplete behaviour as available.

## Project identity

- Repository: `paulpitchford/omarchy-garmin-insights`
- Permanent plugin ID: `io.github.paulpitchford.garmin-insights`
- Licence: MIT
- Garmin client: `python-garminconnect`, used as a pinned external dependency
- Omarchy namespace: never use the reserved `omarchy.*` prefix

## Hard boundaries

- This is an independent public project. Do not copy code, data, assumptions, credentials, or fixtures from any personal Garmin analysis or coaching repository.
- Never add real activity exports, FIT files, routes, coordinates, account details, tokens, passwords, MFA codes, health records, or personal API responses.
- Tests, demos, screenshots, and documentation examples must use fabricated identities and activity data.
- The plugin is read-only with respect to Garmin. Do not call upload, edit, scheduling, hydration, weigh-in, or deletion methods.
- Do not edit packaged files under `/usr/share/omarchy/`. Use the user plugin directory while testing.
- Do not launch a second Quickshell process from the plugin.
- Do not add telemetry, analytics, advertising, or remote services other than the documented Garmin requests, package sources, and fixed public Git update check.

## Architecture

Use these boundaries unless an approved design change updates this file:

1. `Service.qml` is the singleton owner of scheduling, process state, cached summaries, errors, and bounded suspend/connectivity recovery.
2. `BarWidget.qml` and its nested production `PanelShell.qml` render state from the singleton service. The activity-only `Panel.qml` remains tracked as a legacy migration reference but is not the bar-widget entry point. QML views do not authenticate, query Garmin, or aggregate activities.
3. The Python backend is a short-lived command. There is no persistent Python daemon or systemd service.
4. Python owns authentication, Garmin requests, validation, SQLite, aggregation, display JSON generation, and private update-cadence metadata.
5. QML reads bounded summary, activity-trends, activity-list, activity-detail, wellness, and update-check contracts. It never opens private cache files, tokens, raw Garmin responses, or SQLite directly. Summary, trend, and wellness cache loads go through a short-lived hardened backend command that enforces nonblocking no-follow opens, regular-file and ownership checks, strict byte limits, and a bounded response. The singleton service may run bounded `/usr/bin/git` commands only for the fixed public update check documented below.
6. Store canonical measurements in SI units. Convert units only at presentation boundaries.
7. The first release uses activity summary responses and does not download FIT files.
8. The QML service accepts `uv` only from `/usr/bin/uv`, `~/.local/bin/uv`, or `~/.local/share/mise/shims/uv`. Before invoking uv, `/usr/bin/python3` runs the stdlib-only tracked cache bootstrap to secure the application cache root as `0700`. Routine backend commands use `uv run --locked --no-sync`; dependency setup is an explicit visible-terminal `uv sync --locked --no-dev` action. Set `UV_PROJECT_ENVIRONMENT` to `$XDG_CACHE_HOME/omarchy-garmin-insights/uv-environment` so dependency symlinks never enter the plugin checkout.

The manifest kinds are `service` and `bar-widget`. The bar widget owns its nested details panel. Forward the panel lifecycle expected by Omarchy, including `opened`, `open()`, `close()`, `toggle()`, and `closeForPopoutSwitch()`.

The accepted 0.2 panel uses a preferred width of 600 style units. Overview targets approximately 600 style units high; deeper modes may use an 800-style-unit cap. Both dimensions must use the public `KeyboardPanel` fitting API and degrade to a single column when clamped. The production panel must anchor to the actual Garmin Insights bar widget rather than centring on the screen; use the public anchor positioning and clamping behavior without fixed screen coordinates. The four modes are Overview, Wellness, Activities, and Settings, opening on Overview. Overview contains three compact wellness signals—Body Battery, Sleep, and Steps—followed by a larger weekly activity chart and latest-activity row; Training Readiness stays in Wellness. Wellness Today is ordered as Training Readiness, Body Battery, full-width Sleep, Steps, then HRV and resting heart rate. Settings groups ordinary preferences and per-domain freshness compactly and puts logout and purge on a nested Account and Data page. Keep refresh in the header. Preserve nested Wellness and Activities selection during an open session, restore per-view scrolling, and unwind confirmation and nested pages before Escape closes the panel.

Match charts to metric semantics rather than rendering every series as bars. Allowed treatments include same-metric Body Battery daily ranges, an HRV line within Garmin's supplied baseline, stacked Sleep stages, Steps against Garmin's supplied goal, and activity charts selected by time, distance, elevation, or energy. Do not overlay unrelated wellness metrics, imply correlation, or reproduce a Stress/Body Battery chart without separately approved Stress and intraday contracts. Compact icon actions still require a tooltip, accessible name, keyboard cursor state, Unicode or text fallback, and a non-colour selected state. Collection changes, authentication, logout, purge, and other sensitive actions require explicit text and confirmation.

## Authentication and private storage

- Run first-time login in a visible terminal.
- Read the password with `getpass`; never echo it or put it in argv, environment variables, files, QML properties, or logs.
- Complete MFA in the same Python process as credential login.
- Persist only the token material written by `python-garminconnect`.
- Use a dedicated token store. Do not inspect or reuse `~/.garminconnect` automatically.
- Use owner-only XDG directories and files. Directories must be mode `0700`; private files must be mode `0600`.
- Keep runtime locks under `$XDG_RUNTIME_DIR`, never predictable shared `/tmp` paths.
- Treat a token file as configured but unverified until a Garmin request succeeds.
- Never merge data from two Garmin accounts. Detect an account change and require an explicit reset or separate data scope.
- Logout and purge are separate, explicit operations. Plugin removal must not silently delete user data.

Planned storage:

```text
$XDG_STATE_HOME/omarchy-garmin-insights/auth/garmin_tokens.json
$XDG_DATA_HOME/omarchy-garmin-insights/activities.sqlite3
$XDG_CACHE_HOME/omarchy-garmin-insights/summary.json
$XDG_CACHE_HOME/omarchy-garmin-insights/activity-trends.json
$XDG_CACHE_HOME/omarchy-garmin-insights/wellness.json
$XDG_CACHE_HOME/omarchy-garmin-insights/update-check.json
$XDG_RUNTIME_DIR/omarchy-garmin-insights/sync.lock
$XDG_RUNTIME_DIR/omarchy-garmin-insights/update-check.lock
```

Apply the usual XDG defaults when an environment variable is unset.

## Garmin data handling

Use `get_activities_by_date` without an activity filter so unfamiliar and mixed activity types remain visible. Normalise only explicitly allowed fields. Never persist complete responses.

Do not store:

- latitude, longitude, route points, map data, or location endpoints;
- email addresses or full profile responses;
- raw request or response bodies; or
- fields that have not been reviewed and documented.

Missing values remain `None` or JSON `null`. Do not turn missing values into zero. Preserve Garmin's original activity type key and apply a display grouping separately so new types degrade safely. Summary schema version 1 excludes activity names, identifiers, and start times. It carries overall and original-type aggregates with a contributor count for every metric. The separate activity-trends schema contains only calendar bucket boundaries, activity counts, duration, distance, elevation, energy, and contributor counts derived from the same normalized snapshot. Its 7- and 30-day periods use daily points; its 90-day period uses one six-day oldest bucket followed by twelve seven-day buckets. A calendar bucket without activities is zero, while a metric missing from recorded activities remains null. The separate local-only list contract returns at most 20 rows and the detail contract returns one activity or a stable not-found result. Average heart rate and power use duration weighting; average speed uses moving-duration weighting. Values without a positive matching weight do not contribute.

Use calendar periods based on the activity's local start date. Today includes today; 7, 30, and 90 days include today and the preceding 6, 29, or 89 local dates. Retain only the current rolling 90-day activity window. Incremental refreshes reconcile a seven-day overlap, and one full 90-day reconciliation runs per local calendar day.

The reviewed activity allowlist is Garmin activity ID, optional activity name, original type key, local start time and date, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, total sets, and total repetitions. Convert Garmin kilocalories to joules before persistence. Reject the complete refresh if a required field or any supplied allowlisted value is malformed, non-finite, out of range, or excessive. Ignore all fields outside the allowlist.

### Wellness requests and data

Version 0.2 may use only the existing fixed `/userprofile-service/socialProfile` account-verification request and these read-only methods and endpoint shapes from pinned `garminconnect==0.3.11`:

- `get_user_summary(date)` — `/usersummary-service/usersummary/daily/{displayName}`; admit only `calendarDate`, `totalSteps`, `dailyStepGoal`, and `restingHeartRate` for the requested current date.
- `get_daily_steps(start, end)` — `/usersummary-service/stats/steps/daily/{start}/{end}`; admit only `calendarDate` and `totalSteps`. The dependency's 28-day chunking counts toward the request ceiling.
- `get_body_battery(start, end)` — `/wellness-service/wellness/bodyBattery/reports/daily`; admit only `date`, `charged`, `drained`, and `bodyBatteryValuesArray`. The sample array is an ephemeral reduction input, never a stored field or presentation contract.
- `get_sleep_daily(start, end)` — `/sleep-service/stats/sleep/daily/{start}/{end}`; admit only `calendarDate` and `overallSleepScore`. Its 28-day chunking counts toward the ceiling.
- `get_sleep_data(date)` — `/wellness-service/wellness/dailySleepData/{displayName}`; within `dailySleepDTO`, admit only `calendarDate`, `sleepTimeSeconds`, `deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`, and `sleepScores.overall.value`.
- `get_hrv_data_range(start, end)` and `get_hrv_data(date)` — `/hrv-service/hrv/daily/{start}/{end}` and `/hrv-service/hrv/{date}`; admit only `hrvSummaries` or `hrvSummary` entries containing `calendarDate`, `weeklyAvg`, `lastNightAvg`, `status`, and `baseline.balancedLow`/`balancedUpper`.
- `get_rhr_daily(start, end)` — `/userstats-service/wellness/daily/{displayName}` with metric ID 60; admit only the wrapper's `calendarDate` and `value` rows.
- `get_training_readiness(date)` — `/metrics-service/metrics/trainingreadiness/{date}`; admit only `calendarDate`, `timestampLocal`, `inputContext`, `score`, and `level`. Timestamp and input context exist only to select a canonical snapshot and are never persisted.

Do not call Stress, Body Battery events, daily heart-rate samples, health snapshots, additional profile, device, location, menstrual, pregnancy, hydration, weight, blood-pressure, or mutation endpoints for wellness. Do not use the dependency's optional typed response models as the trust boundary: they intentionally allow extra fields and preserve raw data. Project-owned boundary models must reject malformed allowlisted fields and discard every extra field immediately.

A wellness date is Garmin's returned `calendarDate` or Body Battery `date`, which must fall inside the inclusive requested local-date range. Sleep belongs to Garmin's calendar date for the night ending on that date; do not derive another date from sleep timestamps. Today means the machine's local date. A missing date or metric remains null; only an explicit valid zero is zero. A 204/empty date is missing, while a source-level 404 is unsupported. Unsupported and missing sources do not invalidate another source or delete a previous valid value. For an overlapping date, a successfully validated current-day user summary overrides range Steps and resting heart rate, detailed Sleep overrides the sleep-range score, and single-day HRV overrides range HRV. A null never overwrites a retained non-null scalar.

Persist only these canonical daily scalars: date; steps and optional step goal; Body Battery charged, drained, lowest, highest, and latest level; Sleep score, total duration, deep, light, REM, and awake seconds; Training Readiness score and Garmin level; HRV weekly average, last-night average, Garmin status, and balanced baseline bounds; and resting heart rate. Bounds are: scores and Body Battery level/lowest/highest/latest values 0–100; Body Battery charged and drained totals 0–1,000; steps and goal 0–1,000,000; each Sleep field 0–86,400 seconds with deep + light + REM + awake no greater than 86,400; HRV 0–1,000 ms with balanced low no greater than balanced upper; resting heart rate 20–300 bpm; and status and level plain text no longer than 64 characters with no control characters. Numeric values must be finite and booleans are never numbers.

Range responses contain at most 31 uniquely dated rows, readiness contains at most 64 snapshots for one date, and singleton responses must be objects of the documented shape. Reject duplicate dates and out-of-range dates before persistence.

For each Body Battery date, accept at most 2,000 monotonically ordered `[timestamp, level]` samples and at most seven dates in one endpoint call. A sample must have exactly two items, an integer millisecond timestamp whose UTC value is within the requested local date's ±14-hour timezone envelope, and a null or integer level from 0 through 100. Derive lowest, highest, and latest from valid non-null levels, then discard every timestamp and the complete array before the domain boundary returns. Persist Garmin's daily `charged` and `drained` scalars separately. Never persist or display an intraday curve.

Training Readiness uses one stable morning snapshot per date. An admitted `timestampLocal` is an ISO-8601 local date-time string no longer than 40 characters whose date prefix equals the requested date; reject malformed supplied timestamps. Prefer entries with `inputContext == "AFTER_WAKEUP_RESET"`, choosing the earliest valid local timestamp if more than one exists. If every entry omits input context, choose the earliest valid timestamp; accept a timestamp-less fallback only when exactly one valid entry exists. If contexts are present without an after-wakeup entry, or multiple candidates cannot be ordered safely, the date is missing rather than guessed. Persist only score and Garmin level.

Retain the current 30 local dates of wellness data. Range-capable sources receive an initial 30-day reconciliation and a full 30-day reconciliation no more than once per seven local dates. On other local dates reconcile a seven-day overlap. Current Steps and Body Battery may refresh every 30 minutes; current Sleep and Training Readiness may refresh at most every four hours; historical range reconciliation runs at most once per local date. Per-date backfill is private and gradual: detailed Sleep backfill targets only the current seven dates, while Training Readiness score backfill targets all retained 30 dates. Fetch at most two dates per source and four single-date calls total per command, with a one-hour backfill cooldown. Manual refresh bypasses current-value cadence but not full-reconciliation or backfill cooldowns. Stopping collection prevents every future wellness request while retaining stored data.

One wellness command may plan at most one account-verification call and 18 data calls, including dependency-generated range chunks and bounded backfill, plus at most one explicit retry of one transport failure or HTTP 5xx response across the complete command: no more than 20 Garmin HTTP attempts total. The wellness adapter sets dependency retries to zero. Authentication failures and HTTP 429 never retry. Apply a 120-second overall wellness Garmin deadline and bounded response/list validation. Activity and wellness commands run sequentially under the same singleton no-overlap state and each acquires the same owner-only `sync.lock`; each has its own 120-second Garmin deadline, and the QML combined-operation deadline may be at most 250 seconds. A successful domain is committed and remains visible if the other domain fails.

Persist each successful wellness source transactionally and update only that source's freshness after commit. An invalid, unsupported, interrupted, or failed source keeps its last valid rows and freshness. Errors remain source-specific—authentication, rate limit, offline transport, remote service, invalid data, local storage, and unsupported—and presentation uses neutral styling for wellness values while reserving urgent styling for service failures. Wellness display schema version 1 contains exactly 30 ordered local-date points with fixed nullable groups for the approved scalars, fixed 7- and 30-day contributor counts for every scalar, the seven reviewed source states with freshness, latest-value date, and only a stable failure classification, collection state, and the fixed current-day partial markers for Steps and Body Battery. Missing dates are explicit all-null points and valid zero remains a contributor. The contract contains no account scope, request metadata, exception text, or remote extras, is capped at 64 KiB, and is atomically replaced as an optional presentation cache so failure preserves the previous valid file.

Collection stop, logout, purge, and account changes remain distinct. Collection state and request-cadence metadata are private Python-owned state. Disabling collection is idempotent and does not delete rows or caches; re-enabling resumes bounded current refresh and backfill. Logout removes tokens but retains account-scoped activity and wellness data. Purge removes authentication, the account database, all activity and wellness display caches, and private cadence metadata. A different authenticated account is rejected before any wellness transaction and requires explicit purge/reset. Interrupted refreshes may leave already committed source groups current, but never partially commit one source range.

## Python practice reference

Use the three skills from [`ludo-technologies/python-best-practices`](https://github.com/ludo-technologies/python-best-practices) as supplementary guidance when writing Python, configuring tooling, or adding tests:

- `coding-standards`
- `tooling`
- `testing`

The initially reviewed skill revision is `5202c854f211dff8f5255fa78691c193c8b26a4b`. Load the relevant skill and its linked rule before changing that area. This file remains authoritative when generic advice conflicts with the project's security, privacy, dependency, or Omarchy requirements.

## Python standards

- Support Python 3.12 and 3.13. Keep `requires-python`, `.python-version`, Ruff, mypy, CI, and user documentation aligned when that range changes.
- Use a standard `src/` package layout and a small CLI entry point.
- Add type hints to application code. Keep the type checker strict and narrow exceptions at untyped dependency boundaries.
- Prefer small modules with explicit responsibilities. Keep network, filesystem, clock, authentication, database, and presentation-contract boundaries injectable for tests.
- Use dataclasses, enums, protocols, and typed mappings where they clarify a contract. Avoid unstructured dictionaries beyond the remote-response boundary.
- Validate remote types, ranges, string lengths, list sizes, dates, identifiers, and numeric finiteness before persistence. Prefer explicit Pydantic boundary models when they make this contract safer and clearer; convert validated input into domain types before storage and aggregation.
- Use parameterised SQL and explicit schema migrations. Database updates and reconciliation must be transactional.
- Write private files atomically and preserve restrictive permissions.
- Use domain exceptions internally. Map them to stable CLI exit codes and bounded, non-sensitive JSON errors at the process boundary.
- Do not use broad `except Exception` blocks except at a top-level boundary that logs a safe classification and exits predictably.
- Do not use `shell=True`, dynamic evaluation, or command strings for ordinary subprocesses.
- Keep stdout machine-readable for commands used by QML. Send concise diagnostics to stderr and never include secrets or raw responses.
- Bound network retries. Each backend activity refresh uses at most one retry for transient network or server failures and a 120-second overall Garmin request deadline. Authentication errors and HTTP 429 responses fail without retry. After an offline result, the QML singleton may run at most two additional normal refresh commands at fixed delays; successful, authentication, rate-limit, and local-error results cancel that sequence.
- Make refresh, upsert, reconciliation, logout, and purge behaviour idempotent.

## Python tooling and dependencies

Use `uv` with committed `pyproject.toml` and `uv.lock` files. Production dependencies must be exact and reproducible through the lockfile.

Before adding or updating a dependency:

1. Confirm that it is necessary and maintained.
2. Review its source, release status, licence, and security implications.
3. Prefer a published package over a Git dependency.
4. Update the lockfile in the same change.
5. Record direct dependency attribution in `THIRD_PARTY_NOTICES.md` when applicable.
6. Run the full test, lint, type-check, and security-check suite.

Do not use `curl | sh`, unpinned Git execution, install hooks, vendored executable binaries, passwordless sudo rules, or background privilege escalation. The plugin must not require root privileges at runtime.

Use Ruff for formatting and linting, mypy in strict mode for static typing, pytest for tests, and pyscn for structural analysis. Structure tests around observable behaviour, mock external boundaries with faithful interfaces, keep fixtures narrowly scoped, and use readable parameter IDs. Maintain branch coverage of at least 90%. Security-sensitive modules require tests for failure paths, permissions, malformed input, symlinks, traversal, concurrency, redaction, and interrupted writes.

## QML and Omarchy standards

- Follow the installed Omarchy shell contract and built-in plugins as references. Do not depend on undocumented implementation details when a public component or method exists.
- Keep business logic and aggregation out of QML.
- Use one service instance to prevent duplicate Garmin requests on multi-monitor setups.
- Run background processes with direct argument arrays and fixed executable paths.
- Update awareness may query only `https://github.com/paulpitchford/omarchy-garmin-insights.git` and `refs/heads/main` with `/usr/bin/git`. It must validate the supported install path, branch, origin, local and remote commits, 24-hour cadence, output bounds, deadline, and no-overlap guard. It never updates the checkout itself.
- Apply process deadlines and bounded output collection. Prevent overlapping refreshes. Detect a suspend-length wall-clock timer gap in the singleton and delay the first recovery refresh briefly so network reconnection can settle; do not add a connectivity service or generic internet probe.
- Keep authentication in a terminal. Never build password or MFA controls inside the long-lived shell.
- Use Omarchy's `qs.Commons` and `qs.Ui` components, theme colours, spacing, typography, panel coordination, keyboard handling, and accessibility patterns.
- Support horizontal and vertical bars unless a documented limitation is approved.
- Treat all remote strings as display text. Never turn activity names or errors into commands, markup, paths, or URLs without strict validation.
- Keep panel switching, Escape handling, focus, hover, and keyboard navigation consistent with built-in panels.
- Test more than one monitor or emulate multiple widget instances before release.
- After a Git plugin update and any required dependency sync, restart the Omarchy shell. A plugin rescan or watched-file reload does not reliably replace loaded QML components and singleton services. Upgrade tests must verify the running shell was replaced and the new interface loaded, not only that the checkout moved.

Validate plugin changes with:

```bash
omarchy plugin validate "$PLUGIN_DIR"
qmllint -I "$OMARCHY_PATH/shell" \
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

Also test shell summon and hide, click behaviour, disable and enable, the required post-update shell restart, dependency absence, authentication expiry, offline startup, rate limiting, and removal.

## Documentation

- `README.md` is public-facing and describes only current or clearly labelled planned behaviour.
- `AGENTS.md` contains durable engineering and repository rules.
- `SECURITY.md` contains safe reporting instructions and security boundaries.
- `THIRD_PARTY_NOTICES.md` records redistributed or directly used third-party work as dependencies are added.
- `PLAN.md` is a local working plan and is intentionally ignored. Move settled public decisions into README or AGENTS instead of relying on the private plan.
- Public examples must be synthetic and must not resemble a real user's home, workplace, routine, or health history.

Document every executable command, network destination, external dependency, storage location, permission boundary, and cleanup step before release.

## Code review

Automated checks are necessary but do not replace code review. Every implementation batch after the initial bootstrap must use a branch and pull request, including changes authored by an AI agent.

Review the complete diff in a separate pass after implementation. The review must:

- list findings by severity with file and line references;
- check correctness, security, privacy, failure behaviour, concurrency, data migration, public contracts, tests, and documentation as applicable;
- compare the implementation with `AGENTS.md`, the local plan, and the relevant Python or Omarchy references;
- distinguish a real defect from an optional improvement;
- record why any security-sensitive warning or structural-analysis result is accepted; and
- rerun applicable checks after review fixes.

Do not merge with unresolved high- or medium-severity findings. Record the review in the pull request even when it finds no defects. Be explicit when the reviewer is the author performing a separate self-review rather than an independent reviewer.

## Repository governance

- Protect public `main` with separate quality and merger-allowlist rulesets. The quality gate has no bypass actor and requires a pull request, current successful Python 3.12 and 3.13 GitHub Actions checks, resolved conversations, and linear history. Direct pushes, force pushes, and deletion are blocked, including for the owner.
- Allow only squash merges. Keep merge commits and rebase merges disabled, and delete merged topic branches automatically.
- Merge authority is explicit and separate from repository access. Only `paulpitchford` and future users individually approved as merge maintainers may appear as specific `User` actors in the merger allowlist, with `pull_request` bypass mode. `Write`, `Maintain`, `Admin`, organization-owner, App, bot, deploy-key, and broad repository-role classes do not receive merge authority.
- Keep Actions permissions read-only and unable to approve pull requests. Do not add automation to a ruleset bypass list without a separately reviewed, owner-approved threat model.
- Protect `refs/tags/v*` with separate creation and immutability rules. Only the owner or an explicitly approved release maintainer may create a release tag. No actor may update, force-update, or delete a published release tag.
- Treat rulesets, branch settings, collaborators, deploy keys, Apps, webhooks, Actions permissions, secrets, environments, repository visibility, transfers, archival, and deletion as owner-approved security changes. Audit them before each release and at least quarterly.
- Do not weaken protection merely because GitHub or CI is unavailable. A genuine owner-led recovery must be time-bounded and documented, add no standing bypass, restore the exact protection immediately, and rerun API and synthetic pull-request verification.

## Change workflow

1. Run `git status --short --branch` before editing.
2. Create a focused branch. Do not implement directly on `main`.
3. Read the relevant source, tests, and nearby patterns.
4. Make the smallest coherent change.
5. Add or update tests with behaviour changes.
6. Run focused checks during development, then the full suite before commit:

   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src tests
   uv run pytest
   uv run pyscn check --max-complexity 12 --max-cycles 0 src
   ```

7. Run `git diff --check` and review the complete diff.
8. Confirm that no secret, private data, generated environment, local database, or ignored personal file is staged.
9. Use a concise imperative commit subject.
10. Push the branch, open a pull request, and perform the separate review described above.
11. Squash-merge only after CI passes, the branch is current, and review conversations and findings are resolved.
12. Do not publish a release, submit to a marketplace, or change repository visibility without the owner's explicit approval.

Do not rewrite unrelated code, weaken a test to make it pass, suppress a security finding without fixing its cause, or claim a check passed when it was not run.

## Definition of done

A change is complete when:

- behaviour and failure modes are covered by tests;
- formatting, linting, typing, tests, and applicable security checks pass;
- Omarchy validation and QML linting pass for plugin changes;
- private data and credentials cannot enter tracked files or process output;
- README, AGENTS, security documentation, and third-party notices remain accurate;
- installation, upgrade, offline, authentication-expiry, and removal behaviour remain safe; and
- the final diff contains only intentional changes.
