# Legacy Framework

The Python modules at the repository root are the superseded release-gatekeeping
prototype. They use `ALLOW PUBLISH`, `WARN`, and `BLOCK PUBLISH` verdicts.

The current product direction is the cross-layer framework under `src/`, with
`TRUSTED`, `WARNING`, and `NOT TRUSTED` verdicts.

## Report Paths

- Current framework: `python src/run_demo.py` -> `reports/report.json`
- Legacy framework: `python run_demo.py` -> `reports/legacy_report.json`
- Legacy verifier: `python verify_demo.py` validates `legacy_report.json`

Do not use `CONTRACT.md`, `docs/output_contract.md`, or `docs/team_briefs.md` as
the current backend/dashboard contract. They are retained only for history and
must not be deleted until the team approves removal.
