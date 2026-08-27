# Repository guidelines

## Purpose

Build and maintain Garmin Insights for Omarchy, a public Quattro bar plugin that shows recent Garmin Connect activity summaries. The plugin must be useful to people with different activity types, devices, units, and amounts of recorded data.

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
2. `BarWidget.qml` and its nested `Panel.qml` render state from the singleton service. They do not authenticate, query Garmin, or aggregate activities.
3. The Python backend is a short-lived command. There is no persistent Python daemon or systemd service.
4. Python owns authentication, Garmin requests, validation, SQLite, aggregation, display JSON generation, and private update-cadence metadata.
5. QML reads bounded summary, activity-list, activity-detail, and update-check contracts. It never reads tokens, raw Garmin responses, or SQLite. The singleton service may run bounded `/usr/bin/git` commands only for the fixed public update check documented below.
6. Store canonical measurements in SI units. Convert units only at presentation boundaries.
7. The first release uses activity summary responses and does not download FIT files.
8. The QML service accepts `uv` only from `/usr/bin/uv`, `~/.local/bin/uv`, or `~/.local/share/mise/shims/uv`. Before invoking uv, `/usr/bin/python3` runs the stdlib-only tracked cache bootstrap to secure the application cache root as `0700`. Routine backend commands use `uv run --locked --no-sync`; dependency setup is an explicit visible-terminal `uv sync --locked --no-dev` action. Set `UV_PROJECT_ENVIRONMENT` to `$XDG_CACHE_HOME/omarchy-garmin-insights/uv-environment` so dependency symlinks never enter the plugin checkout.

The manifest kinds are `service` and `bar-widget`. The bar widget owns its nested details panel. Forward the panel lifecycle expected by Omarchy, including `opened`, `open()`, `close()`, `toggle()`, and `closeForPopoutSwitch()`.

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

Missing values remain `None` or JSON `null`. Do not turn missing values into zero. Preserve Garmin's original activity type key and apply a display grouping separately so new types degrade safely. Summary schema version 1 excludes activity names, identifiers, and start times. It carries overall and original-type aggregates with a contributor count for every metric. The separate local-only list contract returns at most 20 rows and the detail contract returns one activity or a stable not-found result. Average heart rate and power use duration weighting; average speed uses moving-duration weighting. Values without a positive matching weight do not contribute.

Use calendar periods based on the activity's local start date. Today includes today; 7, 30, and 90 days include today and the preceding 6, 29, or 89 local dates. Retain only the current rolling 90-day activity window. Incremental refreshes reconcile a seven-day overlap, and one full 90-day reconciliation runs per local calendar day.

The reviewed activity allowlist is Garmin activity ID, optional activity name, original type key, local start time and date, duration, moving duration, distance, elevation gain, energy, average and maximum heart rate, average speed, average power, total sets, and total repetitions. Convert Garmin kilocalories to joules before persistence. Reject the complete refresh if a required field or any supplied allowlisted value is malformed, non-finite, out of range, or excessive. Ignore all fields outside the allowlist.

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
