# Aurum — Roadmap to Market-Ready

> **Status and supersession notice (2026-07-25):** This roadmap preserves useful
> historical product and demo context. Aurum's current engineering direction is
> the automated, schema-agnostic PostgreSQL Medallion ETL flow defined in the
> [AI-Assisted Engineering Standards](engineering/AI_ENGINEERING_STANDARDS.md):
> Connect → Dataset/Table Discovery → Bronze → Silver → Gold. Where historical
> Olist-, demo-, or fixed-schema guidance conflicts with that current direction,
> the canonical standards and the current approved batch govern. Historical
> content remains evidence of earlier decisions; it is not silently deleted or
> promoted into a production invariant.

**Purpose of this document:** a single source of truth any AI agent (Cursor, Codex, Antigravity, or a fresh model) can read cold and understand what Aurum is, the rules that must never be broken, where the platform stands today, and the exact phased plan to make it production-ready. If you are an AI being handed this: read Sections 1–3 before proposing or writing any code.

---

## 1. What Aurum is

Aurum is a **local-first, deterministic data-quality validation platform**. It checks whether a dataset can be trusted and produces a structured report ending in a clear verdict: **TRUSTED / WARNING / NOT TRUSTED**, with the root cause, the quantified business impact, and a plain-language narrative.

- **Backend:** FastAPI
- **Frontend:** React / TypeScript
- **Validated data source:** PostgreSQL (the data being *judged*)
- **App-state store:** SQLite (holds projects, runs, reports — separate from the Postgres being judged)
- **LLM:** Ollama (local), used only to *explain*, never to *decide*
- **Demo story:** Bronze passed → Silver failed → Gold was impacted → business loss is visible → output marked NOT TRUSTED.

---

## 2. Non-negotiable rules (the load-bearing constraints)

These are the rules that keep Aurum honest and correct. Breaking any of them is a defect, no matter how good the code looks.

1. **Decide/explain boundary.** The deterministic engine decides the verdict from layer statuses and check outcomes. The trust score drives the verdict and severity. The LLM (Ollama) only attaches a narrative *after* the report is fully built. The LLM never influences any decision. Any interactive control that could change the score/verdict from the UI is a violation.

2. **UI honesty.** Never show a fake number, and never show a button that lies. Every element on screen is one of: **real** (from actual data), **disabled with a reason**, or **clearly labelled Preview/Planned**. On a trust product, a fake element is a credibility wound.

3. **Never invent data to fill a design.** If a mockup shows a field the report doesn't contain (e.g. per-layer numeric scores, "confidence 97.4%", affected-customers), that field is labelled Preview or omitted — never synthesized. Show real *status* instead of fake *numbers*.

4. **Verify, never assert.** No agent's self-report is trusted as proof. Numbers, key names, JSON shapes, and env vars must be confirmed against real code or real output before they are relied on. Asserted values that turned out wrong have been the single biggest source of wasted cycles.

5. **Small, gated units.** Build one small unit at a time. Never "build five systems at once." Each unit is verified from a fresh angle before it is committed.

6. **Engine is frozen unless a phase explicitly changes it.** The validation engine, the 17-key report contract, and the trust-score logic are not touched casually. Changes to them are deliberate and verified with a golden-report diff.

---

## 3. Current ground truth (as of this document)

**What is real and verified:**
- 17-key report contract; `estimated_loss` nested under `business_impact`.
- Deterministic trust score. Weights: **FAIL −50, IMPACTED −10, WARN −5, PASS 0, SKIPPED 0, base 100.** Demo score = 40 (NOT TRUSTED, HIGH).
- SQLite app-state store exists (`projects`, `data_connections`, `validation_runs`, `validation_reports`). No passwords are persisted anywhere.
- `GET /runs` reads **only** `validation_runs` (+ joined `trust_score` / `final_verdict` from `validation_reports`). Never `historical_runs.csv` or `history_records.json`.
- `POST /runs` works but **`run_id` is only a label** — it does NOT select data. Every run secretly rebuilds the **Olist** demo dataset into an isolated Postgres schema and validates *that*. **The engine cannot yet validate a user-selected table.** This is the central gap between demo and product.
- Demo path (backend-off, fixture-first) renders end-to-end: Landing → Bronze → Silver → Gold → Impact → Trust → Quality → Run History (honest empty state when API is off).
- `L1-SIL-CONS-FK-CUST` is intentionally SKIPPED (the `customers` table isn't materialized) and is shown honestly, not hidden.

**Known environment facts:**
- Repo lives under OneDrive — a lock/conflict risk. Move to a non-synced path (e.g. `C:\dev\Aurum`) once work is clean; not mid-flight.
- DB env precedence: `DATABASE_URL` → `DB_*` → `AURUM_POSTGRES_*` → defaults. Office setup uses `DATABASE_URL` only. No new env families.
- Local Postgres runs via Docker for the current demo/runtime setup.

### Local Docker Postgres note

Postgres runs via Docker (container `aurum-postgres`, port `5433`). Docker Desktop must be running before the backend, tests, or any live `/runs` call will work. If `GET /health` returns degraded/503, check Docker Desktop first before assuming a config or code problem.

---

## 4. The agent operating model (how the fleet works)

Speed comes from many agents; safety comes from gates. Every unit follows this loop:

1. **Codex reads and reports the truth** (read-only) — what exists, exact keys, exact seams.
2. **Claude turns that into one small build prompt.**
3. **Cursor builds one unit** (in-repo, full context; builds, does not commit).
4. **Codex verifies the diff from a fresh angle** (sole commit gate; never trusts Cursor's self-report).
5. **Antigravity (ograv) tests on the office laptop** (runtime/compatibility only; never pushes/merges).
6. **Only then commit.** Main machine is the source of truth.

Roles: **Cursor** = builder. **Codex** = adversarial verifier + commit gate. **ograv** = office-laptop runtime checker. **Claude** = planner, risk-spotter, adversarial reviewer — never touches the codebase directly.

---

## 5. The three levels of "production-ready"

"Everything works" is a real target, but it has levels. Be honest about which one is in scope.

| Level | Meaning | Effort |
|---|---|---|
| **Level 1** | A demo that never breaks: real data, no fake buttons, flawless on one laptop | ~2 days |
| **Level 2** | A real product: a user connects their own DB, picks their own table, runs a real check, gets a real verdict | ~1–2 weeks |
| **Level 3** | Online for many users: logins, accounts, cloud, multi-tenancy, scaling | Months; requires cloud/containers |

"Market-ready, everything works" = **Level 2.** Level 3 is a separate, later project and is explicitly out of the current scope.

---

## 6. Phase plan

### Phase 1 — Bulletproof demo (Level 1) — COMPLETE

**Goal:** the demo runs flawlessly end-to-end, backend-off, every screen real, every button honest.

**Tasks**
- [x] Kill the orphaned supervisor that respawned the backend (you now control demo mode).
- [x] Fix the "No checks available" flash on hard load (unresolved app-mode → skeleton, not empty).
- [x] Quality Report screen — real 17-key data, verdict box, verbatim Suggested Action, real JSON export; PDF/Excel/Share labelled Preview; Affected-customers/Timestamp labelled Preview (not in contract).
- [x] Trust Scoring screen — one real overall `trust_score` gauge; per-layer **status-derived rings** (full ring + color + badge, dashed for SKIPPED — not fake percentages); **read-only** display of the real engine weights (FAIL −50 / IMPACTED −10 / WARN −5 / PASS·SKIPPED 0, base 100).
- [x] Wire Run History to the real SQLite `validation_runs` store via `GET /runs`. Read `validation_runs` ONLY — never `historical_runs.csv`. Sparse-but-real is correct; honest empty state when API is off.
- [x] Honest Preview/Planned labels on stub screens and extra connector tiles (Snowflake, BigQuery, Databricks, MySQL, Redshift, S3).

**Done when:** all demo-path screens render real data backend-off; nothing on screen lies; one clean end-to-end walk completes with the backend provably down.

---

### Phase 2 — The engine validates real tables (Level 2 core) — ~1–2 weeks

This is the heart of "production-ready." It is engine surgery, not button-wiring, and it starts with a decision, not a build.

#### Stage 1 — Decide the target (half a day, humans + Claude, NO code)

The single highest-leverage decision in the whole project. Answer: **what does Aurum check on a table it has never seen?**

- **Option A (recommended MVP):** the user brings an **Olist-shaped** dataset (same layer structure / column meaning). The engine works as-is; we only swap the data source from "rebuild Olist" to "read the user's tables." Small, achievable.
- **Option B (large):** the user brings **any** dataset. This requires a generic, config-driven check system that maps unknown schemas onto checks. Weeks more work; do not start here.

Ten agents building fast in the wrong direction just reach the wrong place faster. Lock this before any Stage 2 code.

#### Stage 2 — Point the engine at real data (~3 days)

- Codex reads exactly how the engine loads Olist today and reports the precise seam where "rebuild Olist" happens (in `DataLoader` / the run path).
- Cursor changes only that seam to load the user-connected schema/table instead of regenerating Olist.
- Codex verifies the demo still produces the identical golden report afterward (zero behavior change on the demo path).

**Done when:** the engine can validate an existing connected table, and the Olist demo still works unchanged.

#### Stage 3 — Real end-to-end user flow (~4 days)

Make **Connect → Test Connection → pick schema/table → Preview → Run Validation → Report** real and continuous.

- Postgres connect/test (safe errors: wrong password/port, offline, timeout, empty DB, permission denied; password never returned to UI; consider re-prompting per session rather than persisting).
- Schema/table/column listing and limited-row preview (never load a full table into memory).
- `POST /runs` produces a report about the *user's* data, persisted per `run_id`; reports reopenable from Run History.

**Done when:** a user picks their own table, runs it, and gets a real report — no Olist substitution.

#### Stage 4 — Harden against messy reality (~3 days)

Real tables are ugly. This is where rushed engine work fails live.

- Handle nulls, unexpected types, missing/extra columns, empty tables, permission errors — gracefully, with honest messages.
- Degraded-DB behavior stays safe (503 guard, no phantom runs, no false "Live").
- Test deliberately against deliberately-broken data.

**Done when:** ugly real-world input produces an honest result or an honest error — never a crash or a fake pass.

#### Stage 5 — Finish the honest shell (~2 days)

- Custom checks execute for real (start SELECT-only / read-only; no arbitrary DDL; defer SQL-condition checks if the read-only guarantee isn't solid).
- Human-review notes save to `human_reviews` and attach to a run **without changing the deterministic verdict** (approve-with-risk / exception / needs-rerun — never mutate the verdict).
- Every remaining "Preview" becomes real or is honestly cut.

**Done when:** every single button either does a real thing or is honestly labelled — nothing fake remains.

---

### Phase 3 — Operational polish (optional, post-Level-2) — ~3–4 days

- Real PDF/Excel export (build against a confirmed live report; export contains real data only, never Preview fields dressed as real).
- Observability: run logs, correlation IDs, readable errors, secrets never logged.
- Move repo off OneDrive to a non-synced path.
- Local setup docs (`docs/LOCAL_OFFICE_SETUP.md`) so a fresh machine can run it.

---

### Phase 4 — Multi-user / market scale (Level 3) — separate future project (months)

Out of current scope. Would require: authentication and accounts, multi-tenancy, cloud database, containers/hosting, security review, monitoring, and scaling. Do not attempt inside the Level-2 timeline.

---

## 7. Open decisions to resolve as they arise

- **Stage 1 target (A vs B)** — gates all of Phase 2. Decide first.
- **HITL boundary (Manjula):** recommendation is that humans add review status but never change the deterministic verdict. Needs her explicit sign-off before it's load-bearing.
- **Connection password:** prefer re-prompt-per-session over persistence for a local single-user pilot (nothing at rest to leak).
- **Custom SQL checks:** SELECT-only / read-only connection is a hard prerequisite, or the feature is cut from MVP.

---

## 8. The one-line summary for any agent picking this up

> Phase 1 (bulletproof demo) is complete. Phase 2 makes the engine validate real user tables — starting with the Stage 1 decision about what Aurum checks on unseen data, then surgical, gated, verified stages over ~2 weeks. Never fake a number, never let the UI change the verdict, never trust an unverified assertion, build one small unit at a time.

---

## Tracked prerequisite before production Gold — backup cleanup

Batch 4.5C overwrite promotion creates and retains an exact old-target backup
relation. Production-safe backup-artifact cleanup is required before Gold is
enabled for real users and must receive a separate implementation and
independent verification.

Cleanup authority must bind the exact persisted database identity, namespace
OID, relation OID, schema, relation name, and relation kind throughout the
destructive transaction. A backup name, prefix, run ID, or age is never
ownership proof. Active and ambiguous promotion artifacts must never be
automatically removed. See `docs/gold_promotion.md`.

## Batch 4.5C Silver containment boundary

Production Silver generation remains intentionally unavailable and returns
HTTP 503. Batch 4.5C does not enable a generator, frontend flow, or Batch 5.
Its contained execution seam accepts only reviews with explicit server-bound
project, connection, `silver-lineage-v2`, and exact six-field Bronze relation
authority.

The canonical lineage-v2 payload contains `version`, `project_id`,
`connection_id`, `database_name`, `bronze_schema`, `bronze_relation`,
`silver_schema`, and `silver_target_relation`. Every value is explicit and
non-empty; defaults never become authority. A future production generator must
bind this authority before enablement.

Destructive Silver candidate cleanup is eligible only for `FAILED`, and only
with strict persisted candidate identity plus locked live OID equality.
`PENDING`, `EXECUTING`, `PROMOTING`, `PROMOTED`,
`AMBIGUOUS_PROMOTION`, malformed, and unknown/future states preserve the
candidate.

Promotion distinguishes deterministic pre-commit failure, commit-in-progress
uncertainty, and acknowledged commit. Once PostgreSQL commit returns
successfully, later pool/context cleanup cannot downgrade the result to
FAILED or ambiguous. SQLite must then persist PROMOTED plus exact final
identity; failure of that persistence uses the existing post-commit
reconciliation path without rerunning PostgreSQL DDL.

`python -m src.db_config` is the sole executable deployment authority.
`scripts/setup_roles.sql` is pointer-only.
