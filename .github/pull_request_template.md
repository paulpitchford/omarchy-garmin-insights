## What changed

<!-- Describe the behaviour and why it is needed. -->

## Security and privacy

<!-- Describe affected trust boundaries, private data, permissions, commands, or network access. Write "No change" when none apply. -->

## Verification

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy src tests`
- [ ] `uv run pytest`
- [ ] `uv run pyscn check --max-complexity 12 --max-cycles 0 src`
- [ ] Applicable Omarchy and QML checks
- [ ] Complete diff reviewed for secrets and personal data

## Code review

Reviewer type: <!-- Independent reviewer or separate author self-review -->

### Findings

<!-- List findings by severity with file and line references. Write "No findings" only after reviewing the complete diff. -->

### Accepted warnings

<!-- Explain accepted security, lint, type, coverage, or structural-analysis warnings. Write "None" when all output is clean. -->
