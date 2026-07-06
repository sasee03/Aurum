# Legacy Framework

The Python modules at the repository root are the superseded release-gatekeeping
prototype. They use `ALLOW PUBLISH`, `WARN`, and `BLOCK PUBLISH` verdicts with
**pre-Olist synthetic retail** numbers (100k/72k rows, INR/Rs/₹ currency,
`quantity > 20` planted bug).

The current product direction is the cross-layer framework under `src/`, with
`TRUSTED`, `WARNING`, and `NOT TRUSTED` verdicts on the **Olist Brazilian
E-Commerce** dataset (checkpoint commit `a94a2bb`).

## Report Paths

- Current framework: `python -m src.run_demo` → `reports/report.json`
- Legacy framework: `python run_demo.py` → `reports/legacy_report.json`
- Legacy verifier: `python verify_demo.py` validates `legacy_report.json`

## Archived artifacts

- `CONTRACT.md`, `docs/output_contract.md`, `docs/team_briefs.md` — frozen
  legacy ALLOW/BLOCK contract (pre-Olist).
- `reports/report_before.json` — **removed** (stale synthetic retail snapshot).
- `verify_demo.py` — legacy verifier only; do not use for the Olist demo.

Do not use the legacy contract documents as the current backend/dashboard pin.
See `docs/API_CONTRACT.md` and `README.md` for the active Olist demo.
