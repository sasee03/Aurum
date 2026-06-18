# Team Briefs — point at the real repo

> **LEGACY / SUPERSEDED:** These messages describe the old ALLOW/BLOCK iteration.
> Use `README.md` and `src/` for the current cross-layer framework.

Repo: https://github.com/sasee03/Aurum  ·  Contract: `CONTRACT.md` (frozen)
Modules at repo root · Dashboard: `streamlit_app.py` · Output: `reports/report.json`

---

## Message for Haasya

> Hey Haasya — the backend spine is built, working, and pushed to GitHub
> (github.com/sasee03/Aurum). It runs end-to-end and `verify_demo.py` passes:
> 100,000 → 72,000 → 28% drop → ₹0.48 Cr → BLOCK PUBLISH.
>
> **The output contract is now FROZEN** — it's in the repo as `CONTRACT.md`.
> That JSON is the single source of truth. Build everything to match it exactly,
> and we won't have to rework field names later.
>
> **Your tasks (Evidence & Product Experience):**
> 1. **Baseline + tolerance** (`baseline` block) — normal drop % and std dev,
>    computed from the 15 historical runs. Not hardcoded — this is what makes us
>    "autonomous."
> 2. **Business impact** (`impact` block) — expected vs actual revenue → ₹ impact
>    + risk level, read from the gold summary. Note: set `risk_level` from the
>    *size* of the impact, NOT from the verdict (keeps the data flowing one way).
> 3. **SQL evidence pack** (`evidence` array) — the queries that prove the verdict.
>    Each block needs `name`, `sql`, `result`, `meaning`. The `result` must come
>    from actually running the query, not typed in — it's our "re-run it live"
>    moment.
> 4. **The real dashboard** (`streamlit_app.py`) — reads every value from
>    `reports/report.json`. No demo numbers typed into the UI. If the JSON is
>    missing or won't parse, show an error — never silently show wrong values.
>
> **Hard rule:** no measured number hardcoded anywhere — counts, drop %, revenue,
> sigma, all computed or read from CSV. Same rule I'm holding on the backend.
>
> **One UI tip:** in the dashboard, lead with plain English ("today's 28% drop is
> far outside the normal 3.7–3.9% range"), keep the 755σ as a small supporting
> detail — it reads as too extreme on its own.
>
> Clone the repo, read `CONTRACT.md`, and shout if anything's unclear.

---

## Message for the Integration & Reliability Lead

> Hey — Aurum backend is built and pushed (github.com/sasee03/Aurum). The output
> contract is FROZEN in `CONTRACT.md`. You own the reliability layer now — making
> sure the whole thing runs end-to-end and the two halves talk correctly.
>
> **Important:** you're on the critical path now (not just backup). The seam
> between my backend output and Haasya's dashboard is the most likely place this
> breaks, and you own it. Daily presence matters.
>
> **What you own:**
> 1. **Contract conformance** — check the dashboard reads every field in
>    `CONTRACT.md`, names match exactly, no hardcoded UI values. Report mismatches;
>    don't rename fields yourself.
> 2. **Daily testing** — run `python run_demo.py`, `python verify_demo.py`, and
>    `streamlit run streamlit_app.py`. Confirm no runtime errors, broken imports,
>    or schema mismatch.
> 3. **Number validation** — verify these match in BOTH backend and dashboard:
>    Bronze 100,000 / correct Silver 96,000 / buggy Silver 72,000 / drop 28% /
>    normal ~3.8% / expected ₹10.18 Cr / actual ₹9.70 Cr / impact ₹0.48 Cr /
>    BLOCK PUBLISH.
> 4. **Evidence QA** — each evidence block has name + sql + result + meaning, the
>    result is computed (not typed), and it connects to BLOCK PUBLISH.
> 5. **Demo readiness** — screenshots, dashboard stability, 60-second clarity,
>    act as first-time user.
> 6. **Scalability / Q&A notes** — prep short answers: Airflow/dbt, Snowflake/
>    BigQuery/Databricks, why DuckDB is fine for MVP, YAML policy reuse, why
>    Kafka/K8s/API-gateway are roadmap.
>
> **Authority rule:** I own the contract definition; you own conformance to it.
> When something doesn't match, the question is "which side disagrees with
> `CONTRACT.md`?" — never "let's change the contract." If you find a wrong number,
> report it; don't fix it directly.
>
> **You do NOT own:** anomaly / root-cause / verdict / baseline / impact engines,
> the dashboard design, the demo narration, or product positioning.
>
> Start with the scalability/Q&A notes (zero dependency on our code), then move to
> daily testing as soon as the dashboard reads the contract.
