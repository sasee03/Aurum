# Aurum

Business Release Control for Gold Outputs.

## Quick Start

```powershell
python -m pip install -r requirements.txt
python generate_data.py
python run_demo.py
streamlit run streamlit_app.py
```

`run_demo.py` writes the frozen report contract to `reports/report.json`.

## Verification

Run the Integration & Reliability proof pass:

```powershell
python verify_demo.py
```

It validates the contract shape, source counts, learned tolerance, root-cause trace, evidence SQLs, verdict, and dashboard JSON wiring.

## Project Docs

- `docs/output_contract.md` contains the frozen backend-to-dashboard contract.
- `docs/integration_reliability.md` contains the third-track ownership, checklist, daily update format, and scalability Q&A notes.
