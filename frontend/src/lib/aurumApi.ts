/**
 * Central Aurum API client — live backend first, Vite proxy in dev.
 * Base URL: VITE_API_BASE_URL or empty string (same-origin / proxy).
 */

import type { AurumReport } from '@/types/report';
import type { DatabaseTarget } from '@/types/appMode';
import type { DeterministicSilverRule } from '@/utils/silverRules';
import { ApiError, API_UNAVAILABLE } from '@/utils/apiErrors';

export function normalizeApiUrl(rawBase: string, path: string): string {
  let base = (rawBase || '').trim().replace(/\/+$/, '');
  const cleanPath = path.startsWith('/') ? path : `/${path}`;

  if (!base) {
    return cleanPath;
  }

  if (base.endsWith('/api/v1') && cleanPath.startsWith('/api/v1/')) {
    base = base.slice(0, -7);
  } else if (base.endsWith('/api/v1') && cleanPath.startsWith('/v1/')) {
    base = base.slice(0, -3);
  } else if (base.endsWith('/api') && cleanPath.startsWith('/api/')) {
    base = base.slice(0, -4);
  }

  return base ? `${base}${cleanPath}` : cleanPath;
}

export function buildUrl(path: string): string {
  const rawBase = import.meta.env.VITE_API_BASE_URL ?? '';
  return normalizeApiUrl(rawBase, path);
}

const FETCH_TIMEOUT_MS = 8_000;
const CONNECTOR_VALIDATION_TIMEOUT_MS = 5 * 60_000;

export async function parseApiError(res: Response, parsedBody?: any): Promise<ApiError> {
  let body = parsedBody;
  if (body === undefined) {
    try {
      body = await res.json();
    } catch {
      body = null;
    }
  }

  const status = res.status;
  if (body && typeof body === 'object') {
    const errorCode = typeof body.error === 'string'
      ? body.error
      : (body.detail && typeof body.detail === 'object' && typeof body.detail.error === 'string' ? body.detail.error : undefined);
    let message = '';

    if (typeof body.message === 'string') {
      message = body.message;
    } else if (body.detail && typeof body.detail === 'object' && typeof body.detail.message === 'string') {
      message = body.detail.message;
    } else if (typeof body.detail === 'string') {
      message = body.detail;
    } else if (typeof body.error === 'string') {
      message = body.error;
    }

    if (message) {
      return new ApiError(message, status, errorCode);
    }
  }

  return new ApiError(`Request failed (HTTP ${status})`, status);
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  database: 'ok' | 'unreachable';
  database_target?: DatabaseTarget;
}

async function fetchWithTimeout(
  path: string,
  init?: RequestInit,
  timeoutMs = FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  try {
    return await fetch(buildUrl(path), {
      ...init,
      headers: isFormData
        ? { ...init?.headers }
        : { 'Content-Type': 'application/json', ...init?.headers },
      signal: controller.signal,
    });
  } catch {
    throw new ApiError(API_UNAVAILABLE);
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithTimeout(path, init);
  if (!res.ok) {
    throw await parseApiError(res);
  }
  return res.json() as Promise<T>;
}

/** Health probe — treats HTTP 503 degraded as a valid response (not an error). */
export async function healthCheck(): Promise<HealthResponse> {
  const res = await fetchWithTimeout('/health', undefined, 5_000);
  const body = (await res.json()) as HealthResponse;
  if (res.ok) {
    return body;
  }
  if (res.status === 503 && body.status === 'degraded') {
    return body;
  }
  throw await parseApiError(res, body);
}

export async function runValidation(runId = 'demo_run_001'): Promise<AurumReport> {
  return request<AurumReport>('/runs', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId }),
  });
}

export async function fetchLatestReport(): Promise<AurumReport> {
  return request<AurumReport>('/reports/latest');
}

export async function fetchReportByRunId(runId: string): Promise<AurumReport> {
  return request<AurumReport>(`/reports/${encodeURIComponent(runId)}`);
}

export interface ValidationRunSummary {
  run_id: string;
  project_id: string | null;
  connection_id: string | null;
  status: string;
  mode: string;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
  trust_score: number | null;
  final_verdict: string | null;
  source_schema: string | null;
  source_table: string | null;
  /** Human-readable name — filename, schema.table, or resolved fallback. */
  display_name: string | null;
}

export async function fetchRuns(): Promise<{ runs: ValidationRunSummary[] }> {
  return request<{ runs: ValidationRunSummary[] }>('/runs');
}

export interface ApiProject {
  id: string;
  name: string;
  description: string;
  environment: string;
  created_at: string;
  updated_at: string;
  last_run_id: string | null;
  status: string;
}

export interface CreateProjectPayload {
  name: string;
  description?: string;
  environment: 'Development' | 'QA' | 'Production';
}

export async function createProject(payload: CreateProjectPayload): Promise<ApiProject> {
  const res = await fetchWithTimeout('/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await parseApiError(res);
  }
  return res.json() as Promise<ApiProject>;
}

export async function listProjects(): Promise<{ projects: ApiProject[] }> {
  return request<{ projects: ApiProject[] }>('/projects');
}

export async function getProject(projectId: string): Promise<ApiProject> {
  return request<ApiProject>(`/projects/${encodeURIComponent(projectId)}`);
}

export type AssistantPage =
  | 'dashboard'
  | 'validation'
  | 'history'
  | 'query'
  | 'custom_checks'
  | 'failure'
  | 'bronze'
  | 'silver'
  | 'gold';

export type AssistantLayer = 'bronze' | 'silver' | 'gold';

export interface ChatContext {
  selected_check_id?: string;
  selected_table?: string;
}

export interface AssistantChatRequest {
  message: string;
  run_id?: string;
}

export type ChatRequest = AssistantChatRequest;

export interface EmailDraft {
  subject: string;
  body: string;
  summary: string;
  copy_text: string;
}

export interface AssistantResponseData {
  sql?: string;
  table?: Record<string, unknown>[];
  email_draft?: EmailDraft;
  suggested_actions?: string[];
  custom_check?: Record<string, unknown>;
}

export interface AssistantFact {
  path: string;
  value: unknown;
}

export interface AssistantContextIndicators {
  run_id?: string | null;
  source?: { schema?: string | null; relation?: string | null };
  gold_status?: string | null;
}

export interface AssistantResponse {
  answer: string;
  grounded: boolean;
  status: 'answered' | 'insufficient_information' | 'read_only_refusal';
  evidence?: AssistantFact[];
  context?: AssistantContextIndicators;
  intent?: string;
  data?: AssistantResponseData;
  confidence?: 'high' | 'medium' | 'low';
}

export async function askAurumAssistant(payload: AssistantChatRequest): Promise<AssistantResponse> {
  const body: Record<string, unknown> = {
    message: payload.message,
  };
  if (payload.run_id) {
    body.run_id = payload.run_id;
  }
  return request<AssistantResponse>('/api/v1/assistant/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface CustomCheck {
  check_id?: string;
  layer: AssistantLayer;
  check_name: string;
  rule_type: string;
  column: string;
  operator: string;
  value: string;
  severity: string;
  description: string;
}

export interface CustomCheckRunResult {
  check_id: string;
  status: string;
  message: string;
  observed_value: unknown;
  expected_condition: string;
  data_source?: string;
  scope_note?: string;
}

export async function listCustomChecks(): Promise<{ checks: CustomCheck[] }> {
  return request('/custom-checks');
}

export async function createCustomCheck(
  check: Omit<CustomCheck, 'check_id'>,
): Promise<{ status: string; check_id: string }> {
  return request('/custom-checks', {
    method: 'POST',
    body: JSON.stringify(check),
  });
}

export async function runCustomCheck(
  checkId: string,
  opts?: { runId?: string; connectionId?: string },
): Promise<CustomCheckRunResult> {
  return request('/custom-checks/run', {
    method: 'POST',
    body: JSON.stringify({
      check_id: checkId,
      ...(opts?.runId ? { run_id: opts.runId } : {}),
      ...(opts?.connectionId ? { connection_id: opts.connectionId } : {}),
    }),
  });
}

export async function runCustomCheckWithFile(
  checkId: string,
  runId: string,
  file: File,
): Promise<CustomCheckRunResult> {
  const form = new FormData();
  form.append('check_id', checkId);
  form.append('run_id', runId);
  form.append('file', file);
  const res = await fetchWithTimeout(
    '/custom-checks/run-with-file',
    { method: 'POST', body: form },
    60_000,
  );
  if (!res.ok) {
    throw await parseApiError(res);
  }
  return res.json() as Promise<CustomCheckRunResult>;
}

export async function getMetadataHealth(): Promise<{ status: string; detail?: string }> {
  return request('/metadata/health');
}

export async function getMetadataTables(schema?: string): Promise<any> {
  const query = schema ? `?schema=${encodeURIComponent(schema)}` : '';
  return request(`/metadata/tables${query}`);
}

export async function getMetadataTable(tableName: string, schema?: string): Promise<any> {
  const query = schema ? `?schema=${encodeURIComponent(schema)}` : '';
  return request(`/metadata/tables/${encodeURIComponent(tableName)}${query}`);
}

export interface CsvUploadMismatch {
  schema_match: false;
  error: string;
  expected_columns: string[];
  missing_columns: string[];
}

export class CsvUploadError extends Error {
  constructor(public readonly mismatch: CsvUploadMismatch) {
    super(mismatch.error);
    this.name = 'CsvUploadError';
  }
}

export interface PreviewData {
  connection_id: string;
  schema: string;
  table: string;
  metadata: {
    row_count: number;
    column_count: number;
    columns: {
      name: string;
      data_type: string;
      nullable: boolean;
    }[];
  };
  data: any[];
}

export interface LiveTablePreview {
  schema: string;
  table: string;
  row_count: number;
  column_count: number;
  columns: {
    name: string;
    data_type: string;
    nullable: boolean;
  }[];
  rows: Record<string, unknown>[];
}

export async function previewPostgresTable(
  connection_id: string,
  schema: string,
  table: string
): Promise<PreviewData> {
  const params = new URLSearchParams({
    connection_id,
  });
  if (schema) {
    params.set('schema', schema);
  }
  return request(`/connectors/postgres/tables/${encodeURIComponent(table)}/preview?${params.toString()}`);
}

export async function getLiveTablePreview(
  tableName: string,
  schema: string,
  limit = 10,
): Promise<LiveTablePreview> {
  const params = new URLSearchParams({
    schema,
    limit: String(limit),
  });
  return request<LiveTablePreview>(
    `/metadata/tables/${encodeURIComponent(tableName)}/preview?${params.toString()}`,
  );
}

export async function uploadDatasetCsv(file: File, projectId?: string): Promise<AurumReport> {
  const form = new FormData();
  form.append('file', file);
  if (projectId) {
    form.append('project_id', projectId);
  }
  const res = await fetchWithTimeout('/datasets/upload', {
    method: 'POST',
    body: form,
  }, 60_000);

  let body = null;
  try {
    body = await res.json();
  } catch {
    // Body is empty or not JSON
  }

  if (res.status === 422 && body?.schema_match === false) {
    throw new CsvUploadError(body as CsvUploadMismatch);
  }
  if (!res.ok) {
    throw await parseApiError(res, body);
  }
  return body as AurumReport;
}

export interface PostgresTestPayload {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  project_id?: string;
  name?: string;
}

export interface PostgresTestSuccess {
  connected: true;
  connection_id: string;
  host: string;
  port: number;
  database: string;
  username: string;
  name: string;
}

export interface PostgresTestFailure {
  connected: false;
  error: string;
  host?: string;
  port?: number;
  database?: string;
  username?: string;
}

export type PostgresTestResult = PostgresTestSuccess | PostgresTestFailure;

export async function testPostgresConnection(
  payload: PostgresTestPayload,
): Promise<PostgresTestResult> {
  const res = await fetchWithTimeout('/connectors/postgres/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, 15_000);
  const body = (await res.json()) as PostgresTestResult;
  if (!res.ok && !('connected' in body)) {
    throw await parseApiError(res, body);
  }
  return body;
}

export async function listPostgresSchemas(
  connectionId: string,
): Promise<{ connection_id: string; schemas: string[] }> {
  return request(`/connectors/postgres/schemas?connection_id=${encodeURIComponent(connectionId)}`);
}

export interface PostgresTableEntry {
  schema: string;
  table: string;
  layer: string;
}

export async function listPostgresTables(
  connectionId: string,
  schema?: string,
): Promise<{ connection_id: string; schema: string | null; tables: PostgresTableEntry[] }> {
  const params = new URLSearchParams({ connection_id: connectionId });
  if (schema) params.set('schema', schema);
  return request(`/connectors/postgres/tables?${params.toString()}`);
}

export async function validatePostgresTable(payload: {
  connection_id: string;
  schema: string;
  table: string;
  project_id?: string;
}): Promise<AurumReport> {
  const res = await fetchWithTimeout('/connectors/postgres/validate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, CONNECTOR_VALIDATION_TIMEOUT_MS);

  let body = null;
  try {
    body = await res.json();
  } catch {
    // Body is empty or not JSON
  }

  if (res.status === 422 && body?.schema_match === false) {
    throw new CsvUploadError(body as CsvUploadMismatch);
  }
  if (!res.ok) {
    throw await parseApiError(res, body);
  }
  return body as AurumReport;
}

export interface SilverAssessmentRow {
  row_status: 'RETAINED' | 'EXCLUDED' | 'INVALID';
  reason: string;
  [key: string]: any;
}

export interface SilverAssessment {
  summary: {
    total: number;
    retained: number;
    invalid: number;
    excluded: number;
  };
  flagged_rows: SilverAssessmentRow[];
}

export async function getSilverAssessment(runId: string): Promise<SilverAssessment> {
  return request<SilverAssessment>(`/runs/${encodeURIComponent(runId)}/silver-assessment`);
}

// ────────────────────────────────────────────
// P1 Source Ingestion API Client Functions
// ────────────────────────────────────────────

export interface SourceConnectRequest {
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
}

export interface SourceConnectResponse {
  connected: boolean;
  message: string;
}

export interface SourceColumnInfo {
  name: string;
  data_type: string;
  nullable?: boolean;
  primary_key?: boolean;
  [key: string]: any;
}

export interface SourceTableEntry {
  table: string;
  schema: string;
  row_count?: number | null;
  column_count?: number | null;
  columns?: SourceColumnInfo[];
  [key: string]: any;
}

export interface SourceTablesResponse {
  schema: string;
  tables: SourceTableEntry[];
  source?: string;
  [key: string]: any;
}

export interface IngestToBronzeItemResult {
  table: string;
  status: 'success' | 'error';
  message?: string;
  error?: string;
}

export interface IngestToBronzeResponse {
  results: IngestToBronzeItemResult[];
}

export interface VerifyBronzeItemResult {
  table: string;
  status: 'success' | 'error';
  source_row_count?: number;
  bronze_row_count?: number;
  match?: boolean;
  preview_sample?: Record<string, any>[];
  error?: string;
}

export interface VerifyBronzeResponse {
  results: VerifyBronzeItemResult[];
}

/** P1.1: Test connection to PostgreSQL source database */
export async function sourceConnect(req: SourceConnectRequest): Promise<SourceConnectResponse> {
  return request<SourceConnectResponse>('/api/v1/source/connect', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** P1.2 & P1.3: Discover available tables from the source schema */
export async function fetchSourceTables(schema?: string): Promise<SourceTablesResponse> {
  const query = schema ? `?schema=${encodeURIComponent(schema)}` : '';
  return request<SourceTablesResponse>(`/api/v1/source/tables${query}`);
}

/** P1.4: Ingest selected source tables 1:1 into Bronze layer */
export async function ingestToBronze(tables: string[]): Promise<IngestToBronzeResponse> {
  return request<IngestToBronzeResponse>('/api/v1/source/ingest-to-bronze', {
    method: 'POST',
    body: JSON.stringify({ tables }),
  });
}

/** P1.5: Verify ingested Bronze tables and fetch preview sample */
export async function verifyBronze(tables: string[]): Promise<VerifyBronzeResponse> {
  return request<VerifyBronzeResponse>('/api/v1/source/verify-bronze', {
    method: 'POST',
    body: JSON.stringify({ tables }),
  });
}

export interface ConnectorRelationPayload {
  schema: string;
  table: string;
}

export interface ConnectorBronzeItemResult {
  connection_id: string;
  ingest_id?: string;
  status: 'success' | 'error';
  source: ConnectorRelationPayload;
  bronze: ConnectorRelationPayload;
  source_row_count?: number;
  bronze_row_count?: number;
  row_count?: number | null;
  match?: boolean;
  error?: string;
}

export interface ConnectorBronzeResponse {
  connection_id: string;
  results: ConnectorBronzeItemResult[];
}

export async function ingestConnectorRelationsToBronze(
  connectionId: string,
  relations: ConnectorRelationPayload[],
): Promise<ConnectorBronzeResponse> {
  return request<ConnectorBronzeResponse>('/connectors/postgres/bronze/ingest', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, relations }),
  });
}

export async function verifyConnectorRelationsInBronze(
  connectionId: string,
  relations: ConnectorRelationPayload[],
): Promise<ConnectorBronzeResponse> {
  return request<ConnectorBronzeResponse>('/connectors/postgres/bronze/verify', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, relations }),
  });
}

// ────────────────────────────────────────────
// P2 Silver Transformation API Client Functions
// ────────────────────────────────────────────

export interface TransformSaveRulesRequest {
  table_name: string;
  rules: DeterministicSilverRule[];
}

export interface TransformSaveRulesResponse {
  status: string;
  message: string;
  rule_revision?: string;
}

export interface TransformGetRulesResponse {
  table_name: string;
  rules: unknown[];
  rule_revision?: string;
}

export interface TransformGenerateRequest {
  table_name: string;
  connection_id?: string;
  source?: ConnectorRelationPayload;
}

export interface TransformGenerateResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface TransformPlannedChanges {
  summary?: string;
  rules: unknown[];
  cte_steps_detected?: number;
  attribution_safe?: boolean;
}

export interface TransformReviewResponse {
  run_id: string;
  table_name: string;
  planned_changes: TransformPlannedChanges;
  sql_text: string;
  executed: boolean;
  executable: boolean;
  status: string;
  generator_provenance: string | null;
  rule_revision?: string | null;
  message: string;
}

export interface TransformExecuteResponse {
  status: string;
  run_id: string;
  table_name: string;
  target: {
    schema: string;
    relation_name: string;
    [key: string]: unknown;
  };
  attribution_log: string[] | null;
  attribution_available: boolean;
  message: string;
}

/** P2.1: Save free-text rules for a Bronze table */
export async function transformSaveRules(
  tableName: string,
  rules: DeterministicSilverRule[],
): Promise<TransformSaveRulesResponse> {
  return request<TransformSaveRulesResponse>('/api/v1/transform/rules', {
    method: 'POST',
    body: JSON.stringify({ table_name: tableName, rules }),
  });
}

/** P2.1: Fetch saved rules for a table */
export async function transformGetRules(tableName: string): Promise<TransformGetRulesResponse> {
  return request<TransformGetRulesResponse>(`/api/v1/transform/rules/${encodeURIComponent(tableName)}`);
}

/** P2.2 & P2.3: Generate SQL via LLM for requested table */
export async function transformGenerate(
  tableName: string,
  connectorContext?: { connectionId: string; source: ConnectorRelationPayload },
): Promise<TransformGenerateResponse> {
  return request<TransformGenerateResponse>('/api/v1/transform/generate', {
    method: 'POST',
    body: JSON.stringify({
      table_name: tableName,
      ...(connectorContext
        ? {
            connection_id: connectorContext.connectionId,
            source: connectorContext.source,
          }
        : {}),
    }),
  });
}

/** P2.5: Review generated SQL */
export async function transformReview(runId: string): Promise<TransformReviewResponse> {
  return request<TransformReviewResponse>(`/api/v1/transform/review/${encodeURIComponent(runId)}`);
}

/** P2-B: Execute generated SQL and promote to Silver */
export async function transformExecute(runId: string): Promise<TransformExecuteResponse> {
  return request<TransformExecuteResponse>(`/api/v1/transform/execute/${encodeURIComponent(runId)}`, {
    method: 'POST',
  });
}

// ────────────────────────────────────────────
// Gold Layer API Client Functions (Controlled non-LLM)
// ────────────────────────────────────────────

export interface GoldTableItem {
  name: string;
  schema?: string;
}

export interface GoldTablesResponse {
  tables: GoldTableItem[];
}

export interface CheckGoldNameResponse {
  name: string;
  is_valid_identifier: boolean;
  is_available: boolean;
  status: 'invalid' | 'taken' | 'available';
  resolution_options: Array<{
    action: 'overwrite' | 'rename';
    description: string;
  }>;
  message: string;
}

export interface GenerateGoldPayload {
  source: ConnectorRelationPayload;
  target_table_name: string;
  business_requirement: string;
}

export interface GenerateGoldResponse {
  run_id: string;
  table_name: string;
  sql_text: string;
  planned_changes: Record<string, any>;
  status: string;
  review_revision: string;
  generator_provenance: string;
  ai_interpretation?: Record<string, any>;
  generator_family?: string;
  generator_model?: string | null;
  verdict?: string;
}

export interface ReviewGoldResponse {
  run_id: string;
  table_name: string;
  planned_changes: Record<string, any>;
  sql_text: string;
  review_revision: string;
  approved_revision: string | null;
  executed: boolean;
  executable: boolean;
  status: string;
  generator_provenance: string;
  message: string;
  generator_family?: string;
  generator_model?: string | null;
}

export interface ApproveGoldPayload {
  review_revision: string;
  overwrite: boolean;
}

export interface ApproveGoldResponse {
  status: string;
  run_id: string;
  review_revision: string;
  approved_revision: string;
  approved_at: string;
  overwrite_authorized: boolean;
}

export interface ExecuteGoldPayload {
  overwrite: boolean;
}

export interface ExecuteGoldResponse {
  status: string;
  run_id: string;
  execution_claim_id: string;
  candidate: Record<string, any>;
}

export interface PromoteGoldResponse {
  status: string;
  run_id: string;
  promotion_claim_id: string;
  promotion_committed_at: string;
  target: Record<string, any>;
  backup?: Record<string, any>;
}

export interface MetadataTableDetailResponse {
  tables: Array<{
    schema: string;
    table: string;
    layer: string;
    row_count: number;
    column_count: number;
    columns: Array<{
      name: string;
      data_type: string;
      nullable: boolean;
      sample_values?: any[];
    }>;
  }>;
}

/** Fetch tables in the Silver schema for Gold source selection */
export async function listSilverTables(): Promise<GoldTablesResponse> {
  return request<GoldTablesResponse>('/api/v1/gold/silver-tables');
}

/** Check if proposed Gold table name is valid */
export async function checkGoldName(name: string): Promise<CheckGoldNameResponse> {
  return request<CheckGoldNameResponse>(`/api/v1/gold/check-name?name=${encodeURIComponent(name)}`);
}

/** Generate structured Gold SQL proposal through the bounded AI interpretation route. */
export async function generateGoldSql(payload: GenerateGoldPayload): Promise<GenerateGoldResponse> {
  return request<GenerateGoldResponse>('/api/v1/gold/ai/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Review Gold SQL proposal */
export async function reviewGoldSql(runId: string): Promise<ReviewGoldResponse> {
  return request<ReviewGoldResponse>(`/api/v1/gold/review/${encodeURIComponent(runId)}`);
}

/** Approve Gold SQL proposal */
export async function approveGoldSql(runId: string, payload: ApproveGoldPayload): Promise<ApproveGoldResponse> {
  return request<ApproveGoldResponse>(`/api/v1/gold/approve/${encodeURIComponent(runId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Execute Gold candidate creation */
export async function executeGoldSql(runId: string, payload: ExecuteGoldPayload): Promise<ExecuteGoldResponse> {
  return request<ExecuteGoldResponse>(`/api/v1/gold/execute/${encodeURIComponent(runId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Promote Gold candidate table to Gold layer */
export async function promoteGoldSql(runId: string): Promise<PromoteGoldResponse> {
  return request<PromoteGoldResponse>(`/api/v1/gold/promote/${encodeURIComponent(runId)}`, {
    method: 'POST',
  });
}

/** Fetch tables in the Gold schema */
export async function listGoldTables(): Promise<GoldTablesResponse> {
  return request<GoldTablesResponse>('/api/v1/gold/gold-tables');
}
