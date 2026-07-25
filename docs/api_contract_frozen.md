# AURUM BACKEND API CONTRACT (FROZEN)

**Version:** 2.0-Frozen  
**Base Revision:** `827f0efc002a7f79cc361e44627f952885cd60d5`  
**Target Audience:** Frontend Team (Sasee) / Integration Engineers  
**Traceability:** Every entry is mapped directly to actual backend source implementation files (`api/*.py`).

---

## 1. Executive Summary & System Behavior

This document freezes the complete backend HTTP API contract for Aurum. All endpoints return standard JSON responses unless noted otherwise.

### Standard HTTP Status Codes
* **200 OK / 201 Created**: Request succeeded.
* **400 Bad Request**: Malformed payload, invalid identifiers, or missing required fields.
* **401 Unauthorized**: Authentication failure when connecting to external user databases.
* **404 Not Found**: Resource, table, run_id, or project_id does not exist.
* **409 Conflict**: State conflict (e.g. non-pending run, stale review revision, target collision).
* **422 Unprocessable Entity**: Malformed security state, rule parse failure, schema mismatch, or unprocessable data.
* **500 Internal Server Error**: Unexpected backend exception (sanitized in production).
* **503 Service Unavailable**: Database unreachable, pool timeout, or un-trusted LLM generator containment.

---

## 2. Core Liveness & Validation Endpoints (`api/main.py`)

### 2.1 GET `/health`
* **File & Line:** `api/main.py:121`
* **Description:** Liveness check and fast Postgres reachability probe.
* **Request:** None.
* **Response Body:**
  ```json
  {
    "status": "ok",          // "ok" or "degraded"
    "database": "ok",        // "ok" or "unreachable"
    "database_target": {
      "host": "localhost",
      "port": 5432,
      "database": "aurum_db",
      "user": "aurum_user"
    }
  }
  ```
* **Status Codes:**
  * `200 OK`: Database probe succeeded.
  * `503 Service Unavailable`: Database probe failed (`status: degraded`, `database: unreachable`).

### 2.2 GET `/runs`
* **File & Line:** `api/main.py:145`
* **Description:** List validation runs from SQLite app state store.
* **Response Body:** `{"runs": [...]}`
* **Status Codes:** `200 OK`, `422 Unprocessable Entity`.

### 2.3 POST `/runs`
* **File & Line:** `api/main.py:158`
* **Description:** Synchronously run engine demo validation (~5s) and return full 17-key report.
* **Request Body (Optional):** `{"run_id": "demo_run_001"}`
* **Response Body:** 17-key Aurum report dict.
* **Status Codes:**
  * `200 OK`: Validation completed.
  * `503 Service Unavailable`: Postgres unreachable (guaranteed by server-side DB probe).

### 2.4 GET `/runs/{run_id}/silver-assessment`
* **File & Line:** `api/main.py:195`
* **Description:** Query retained session schema for Silver row exclusion/invalidation reasons.
* **Status Codes:** `200 OK`, `404 Not Found` (run missing or view not found), `422 Unprocessable Entity` (no session schema retained).

### 2.5 GET `/reports/latest` & GET `/reports/{run_id}`
* **File & Line:** `api/main.py:291` & `api/main.py:310`
* **Description:** Fetch validation report by ID or get the latest.
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`.

---

## 3. P1 Source Ingestion & Bronze Endpoints (`api/source_ingest_router.py`)

### 3.1 POST `/api/v1/source/connect`
* **File & Line:** `api/source_ingest_router.py:23`
* **Request Body:**
  ```json
  {
    "host": "string",
    "port": 5432,
    "database": "string",
    "user": "string",
    "password": "string"
  }
  ```
* **Response Body:** `{"connected": true, "message": "Connection successful."}`
* **Status Codes:** `200 OK`, `401 Unauthorized`, `404 Not Found`, `503 Service Unavailable`, `500 Internal Server Error`.

### 3.2 GET `/api/v1/source/tables`
* **File & Line:** `api/source_ingest_router.py:59`
* **Query Params:** `schema` (optional string, defaults to configured `schemas.source`)
* **Response Body:** `{"schema": "public", "tables": [...]}`
* **Status Codes:** `200 OK`, `500 Internal Server Error`.

### 3.3 POST `/api/v1/source/ingest-to-bronze`
* **File & Line:** `api/source_ingest_router.py:75`
* **Request Body:** `{"tables": ["orders", "order_items"]}`
* **Response Body:** `{"results": [{"table": "orders", "status": "success", "message": "..."}]}`
* **Status Codes:** `200 OK`, `400 Bad Request`, `500 Internal Server Error`.

### 3.4 POST `/api/v1/source/verify-bronze`
* **File & Line:** `api/source_ingest_router.py:135`
* **Request Body:** `{"tables": ["orders"]}`
* **Response Body:** `{"results": [{"table": "orders", "status": "success", "source_row_count": 100, "bronze_row_count": 100, "match": true, "preview_sample": [...]}]}`
* **Status Codes:** `200 OK`, `400 Bad Request`, `500 Internal Server Error`.

---

## 4. P2 Bronze-to-Silver Transformation Pipeline (`api/bronze_silver_router.py`)

### 4.1 POST `/api/v1/silver/generate-rules`
* **File & Line:** `api/bronze_silver_router.py:133`
* **Request Body:** `{"bronze_table_name": "string", "user_instructions": "string"}`
* **Response Body:** `{"run_id": "string", "rules": [...], "review_revision": "64-char-hex", ...}`
* **Status Codes:** `200 OK`, `400 Bad Request`, `503 Service Unavailable` (503 if generator contained/disabled).

### 4.2 POST `/api/v1/silver/rules/materialize`
* **File & Line:** `api/bronze_silver_router.py:221`
* **Description:** Deterministic server-side rule materialization.
* **Request Body:** `{"source_table": "string", "rules": [...]}`
* **Response Body:** `{"rule_revision": "64-char-hex", "rules": [...]}`
* **Status Codes:** `200 OK`, `400 Bad Request`.

### 4.3 POST `/api/v1/silver/rules/claim`
* **File & Line:** `api/bronze_silver_router.py:246`
* **Request Body:** `{"source_table": "string", "rule_revision": "64-char-hex", "rules": [...]}`
* **Response Body:** `{"run_id": "string", "review_revision": "64-char-hex", "status": "PENDING"}`
* **Status Codes:** `200 OK`, `400 Bad Request`, `409 Conflict`.

### 4.4 GET `/api/v1/silver/review/{run_id}`
* **File & Line:** `api/bronze_silver_router.py:339`
* **Response Body:** `{"run_id": "string", "bronze_table": "string", "sql_text": "string", "review_revision": "string", ...}`
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`.

### 4.5 POST `/api/v1/silver/approve/{run_id}`
* **File & Line:** `api/bronze_silver_router.py:421`
* **Request Body:** `{"review_revision": "64-char-hex", "overwrite": false}`
* **Response Body:** `{"status": "approved", "run_id": "string", "approved_revision": "64-char-hex", ...}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

### 4.6 POST `/api/v1/silver/execute/{run_id}`
* **File & Line:** `api/bronze_silver_router.py:633`
* **Request Body:** `{"overwrite": false}`
* **Response Body:** `{"status": "PROMOTING", "run_id": "string", "execution_claim_id": "string", "candidate": {...}}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

### 4.7 POST `/api/v1/silver/promote/{run_id}`
* **File & Line:** `api/bronze_silver_router.py:863`
* **Request Body:** `{"overwrite": false}`
* **Response Body:** `{"status": "PROMOTED", "run_id": "string", "target_table": "string"}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

---

## 5. P3 Silver-to-Gold Transformation Pipeline (`api/silver_gold_router.py`)

### 5.1 GET `/api/v1/gold/check-name`
* **File & Line:** `api/silver_gold_router.py:123`
* **Query Params:** `name` (proposed table name)
* **Response Body:** `{"name": "string", "is_valid_identifier": true, "is_available": true, "status": "available", ...}`
* **Status Codes:** `200 OK`, `500 Internal Server Error`.

### 5.2 GET `/api/v1/gold/silver-tables`
* **File & Line:** `api/silver_gold_router.py:191`
* **Response Body:** `{"tables": [{"name": "orders"}, {"name": "order_items"}]}`
* **Status Codes:** `200 OK`, `503 Service Unavailable`, `500 Internal Server Error`.

### 5.3 POST `/api/v1/gold/generate`
* **File & Line:** `api/silver_gold_router.py:233`
* **Request Body:**
  ```json
  {
    "target_table_name": "customer_spend",
    "silver_table_names": ["orders"],
    "business_requirement": "Calculate total spend per customer"
  }
  ```
* **Response Body:** `{"run_id": "string", "table_name": "string", "sql_text": "string", "status": "PENDING", "review_revision": "64-char-hex"}`
* **Status Codes:** `200 OK`, `400 Bad Request`, `503 Service Unavailable` (when LLM untrusted), `500 Internal Server Error`.

### 5.4 GET `/api/v1/gold/review/{run_id}`
* **File & Line:** `api/silver_gold_router.py:324`
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`, `503 Service Unavailable`.

### 5.5 POST `/api/v1/gold/approve/{run_id}`
* **File & Line:** `api/silver_gold_router.py:414`
* **Request Body:** `{"review_revision": "64-char-hex", "overwrite": false}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

### 5.6 POST `/api/v1/gold/execute/{run_id}`
* **File & Line:** `api/silver_gold_router.py:610`
* **Request Body:** `{"overwrite": false}`
* **Response Body:** `{"status": "PROMOTING", "run_id": "string", "execution_claim_id": "string", "candidate": {...}}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

### 5.7 POST `/api/v1/gold/promote/{run_id}`
* **File & Line:** `api/silver_gold_router.py:836`
* **Request Body:** `{"overwrite": false}`
* **Response Body:** `{"status": "PROMOTED", "run_id": "string", "target_table": "string"}`
* **Status Codes:** `200 OK`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `503 Service Unavailable`.

---

## 6. Admin & Maintenance Endpoints (`api/admin_router.py`)

### 6.1 POST `/api/v1/admin/candidate-cleanup`
* **File & Line:** `api/admin_router.py:11`
* **Query Params:**
  * `confirm` (bool, required `true` for execution)
  * `age_threshold_seconds` (int, default `3600`)
* **Response Body:** Cleanup summary dict.
* **Status Codes:** `200 OK`, `400 Bad Request` (when `confirm=false`), `500 Internal Server Error`.

---

## 7. Connectors & Datasets Endpoints (`api/connectors_router.py`, `api/datasets_router.py`)

### 7.1 POST `/connectors/postgres/test`
* **File & Line:** `api/connectors_router.py:107`
* **Status Codes:** `200 OK` (returns `{"connected": false, "error": "..."}` on test failure without throwing 500).

### 7.2 GET `/connectors/postgres/schemas` & GET `/connectors/postgres/tables`
* **File & Line:** `api/connectors_router.py:159` & `api/connectors_router.py:184`
* **Status Codes:** `200 OK`, `404 Not Found` (session expired), `422 Unprocessable Entity`.

### 7.3 GET `/connectors/postgres/tables/{table}/preview`
* **File & Line:** `api/connectors_router.py:212`
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`.

### 7.4 POST `/connectors/postgres/validate`
* **File & Line:** `api/connectors_router.py:262`
* **Request Body:** `{"connection_id": "string", "schema": "public", "table": "orders", "project_id": null}`
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`, `503 Service Unavailable`, `500 Internal Server Error`.

### 7.5 POST `/datasets/upload`
* **File & Line:** `api/datasets_router.py:72`
* **Request Form:** `file` (multipart CSV), `project_id` (string)
* **Status Codes:** `200 OK`, `404 Not Found`, `422 Unprocessable Entity`, `503 Service Unavailable`, `500 Internal Server Error`.

---

## 8. Projects & Custom Checks / Assistant Endpoints

### 8.1 POST `/projects`, GET `/projects`, GET `/projects/{project_id}`
* **File & Line:** `api/projects_router.py:29-44`
* **Status Codes:** `201 Created`, `200 OK`, `404 Not Found`.

### 8.2 POST `/aurum-assistant/chat` (Alias: `POST /assistant/chat`)
* **File & Line:** `api/aurum_assistant/router.py:154` & `api/aurum_assistant/router.py:171`
* **Status Codes:** `200 OK`, `422 Unprocessable Entity`.

### 8.3 GET `/custom-checks`, POST `/custom-checks`, POST `/custom-checks/run`, POST `/custom-checks/run-with-file`
* **File & Line:** `api/aurum_assistant/router.py:176-385`
* **Status Codes:** `200 OK`, `422 Unprocessable Entity`.

---

## 9. Explicit "NOT IMPLEMENTED" List

The following endpoints referenced in early specification notes or initial draft discussions **do NOT exist** in the implemented code base and MUST NOT be called by the frontend:

1. `DELETE /api/v1/silver/rules/{rule_id}` — **NOT IMPLEMENTED** (rules are materialized as immutable sets via `POST /api/v1/silver/rules/materialize`).
2. `PUT /api/v1/gold/draft` — **NOT IMPLEMENTED** (Gold SQL generation produces immutable pending review runs directly).
3. `POST /api/v1/source/reset` — **NOT IMPLEMENTED** (source-to-bronze uses atomic `DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT`).
4. `GET /api/v1/admin/logs` — **NOT IMPLEMENTED** (backend logs via Python standard logging).
