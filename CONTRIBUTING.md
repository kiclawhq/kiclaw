# Contributing to KiClaw

KiClaw changes should preserve the inspect → snapshot → guarded edit → native verify → report loop. The project favors small, reviewable changes with explicit evidence and honest capability boundaries.

## Local workflow

1. Create a focused branch from `main`.
2. Install the locked development environment:

   ```bash
   uv sync --locked --no-editable --extra dev
   ```

3. Run the fast checks before editing and the full suite before opening a change:

   ```bash
   # After adding/editing modules, reinstall so site-packages matches source:
   uv sync --locked --no-editable --extra dev

   export PYDANTIC_DISABLE_PLUGINS=1
   export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1   # required: without this, pytest can hang on plugin scan

   uv run --locked --no-editable kiclaw doctor
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --locked --no-editable pytest -q
   # or against the live source tree:
   PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
   ```

   Helper script with logging: `scripts/run_analysis_tests.sh` (writes `Documents/kiclaw-demo-results/pytest-deep-analysis.log`).

4. Update tests, documentation, and `CHANGELOG.md` together when a public behavior changes.
5. Review the diff for generated `.kiclaw/`, build, virtual-environment, and machine-specific files before committing.

## Commit conventions

Use short imperative Conventional Commit subjects, for example:

- `feat: add guarded schematic wire insertion`
- `fix: reject stale board hashes`
- `docs: describe review evidence contract`
- `test: cover native IPC fallback`

Keep each commit logically reversible. Do not combine a formatting sweep with a behavioral change. Pull requests should explain the user-visible outcome, verification performed, and any limitation that remains.

## Safety and review expectations

- Never claim a native DRC/ERC/export result when KiCad was unavailable.
- Preserve snapshots and transaction manifests for every file-backed mutation.
- Treat parsed board statistics as approximate.
- Add a regression test for every new guard, schema, backend policy, or failure mode.
- Do not commit proprietary boards, datasheets, API tokens, or `.kiclaw/` state.

## Release checklist

- Locked dependencies resolve with `uv lock --check`.
- CLI help and `doctor` succeed on the supported host.
- Full tests pass, including native KiCad fixtures when installed.
- README, changelog, and public tool descriptions match the implementation.
- A representative project review and compatibility report are archived outside the source tree.
