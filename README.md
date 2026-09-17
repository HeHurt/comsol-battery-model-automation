# COMSOL Battery Model Automation

A Codex skill for auditable COMSOL Multiphysics 6.4 battery-model workflows. It routes between direct `.mph` inspection, targeted Java editing, and reproducible `comsolcompile`/`comsolbatch` execution while keeping validation and source preservation explicit.

## Capabilities

- Audit existing `.mph` models with summary, targeted, or full scopes.
- Diagnose voltage, capacity, heat-balance, solver, and parameter-sweep problems.
- Apply supported patches through save-as, then unload, reload, and verify assertions.
- Run minimal smoke studies with explicit datasets, solution indices, and units.
- Analyze exported COMSOL Java without loading multi-megabyte files blindly.
- Compile, solve, collect metrics, and check acceptance criteria for autonomous Java workflows.

## Requirements

- Codex or another agent runtime that supports skills.
- Python 3.10 or newer.
- `uv` for the pinned `sim-cli` runtime used by direct `.mph` workflows.
- COMSOL Multiphysics 6.4 and a valid license for loading, compiling, or solving models.

This repository does not include COMSOL software, licenses, documentation PDFs, model files, or proprietary parameter sets.

## Install for Codex

Clone the repository into your Codex skills directory:

```powershell
git clone https://github.com/HeHurt/comsol-battery-model-automation.git `
  "$env:USERPROFILE\.codex\skills\comsol-battery-model-automation"
```

Restart or reload Codex so it discovers the skill. Invoke it explicitly with `$comsol-battery-model-automation`, or describe a matching COMSOL battery-model task.

## Validate

```powershell
$skillRoot = "$env:USERPROFILE\.codex\skills\comsol-battery-model-automation"
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" $skillRoot
python -m pytest "$skillRoot\tests" -q
```

The real-COMSOL integration test is skipped unless `COMSOL_MPH_TEST_MODEL` points to an available test model.

## Safety model

- Read-only diagnosis does not modify source models.
- Modifications are save-as operations; source `.mph` files are not overwritten.
- Saved models are reloaded and checked before a patch is accepted.
- Minimal smoke success is not reported as completion of a full production sweep.
- Unknown COMSOL processes and sessions are not terminated automatically.

## License and trademarks

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).

COMSOL and COMSOL Multiphysics are trademarks or registered trademarks of COMSOL AB. This community project is independent and is not affiliated with or endorsed by COMSOL AB or OpenAI.
