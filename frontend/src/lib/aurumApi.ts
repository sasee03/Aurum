/**
 * Central Aurum API client — live backend first, Vite proxy in dev.
 * Base URL: VITE_API_BASE_URL or empty string (same-origin / proxy).
 */

import type { AurumReport } from '@/types/report';
import type { DatabaseTarget } from '@/types/appMode';
import { ApiError, API_UNAVAILABLE } from '@/utils/apiErrors';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
const FETCH_TIMEOUT_MS = 8_000;

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
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      signal: controller.signal,
      ...init,
    });
  } finally {
    window.clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithTimeout(path, init);
  if (!res.ok) {
    throw new ApiError(API_UNAVAILABLE);
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
  throw new ApiError(API_UNAVAILABLE);
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
    throw new ApiError(API_UNAVAILABLE);
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

export interface ChatRequest {
  page: AssistantPage;
  run_id: string;
  layer?: AssistantLayer | null;
  question: string;
  context: ChatContext;
}

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

export interface AssistantResponse {
  intent: string;
  answer: string;
  data: AssistantResponseData;
  confidence: 'high' | 'medium' | 'low';
}

export async function askAurumAssistant(payload: ChatRequest): Promise<AssistantResponse> {
  return request<AssistantResponse>('/aurum-assistant/chat', {
    method: 'POST',
    body: JSON.stringify(payload),
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

export async function runCustomCheck(checkId: string): Promise<CustomCheckRunResult> {
  return request('/custom-checks/run', {
    method: 'POST',
    body: JSON.stringify({ check_id: checkId }),
  });
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
