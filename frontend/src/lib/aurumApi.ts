/**
 * Central Aurum API client — live backend first, Vite proxy in dev.
 * Base URL: VITE_API_BASE_URL or empty string (same-origin / proxy).
 */

import type { AurumReport } from '@/types/report';
import { ApiError, API_UNAVAILABLE } from '@/utils/apiErrors';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(API_UNAVAILABLE);
  }
  return res.json() as Promise<T>;
}

export async function healthCheck(): Promise<{ status: string; database?: string }> {
  return request('/health');
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
