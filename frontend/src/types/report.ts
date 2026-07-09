/** Aurum report contract — 17 top-level keys (docs/API_CONTRACT.md). */

export type CheckStatus = 'PASS' | 'WARN' | 'FAIL' | 'IMPACTED' | 'SKIPPED';

export interface CheckResult {
  check_id: string;
  check_name: string;
  layer: string;
  status: CheckStatus;
  observed: unknown;
  expected: unknown;
  detail: string;
  evidence_query?: string;
  extra?: Record<string, unknown>;
}

export interface RootCauseEvidence {
  check_id: string;
  detail: string;
  evidence_query: string;
}

export interface RootCause {
  summary: string;
  failed_check_ids?: string[];
  suspected_filter?: string;
  evidence?: RootCauseEvidence[];
}

export interface BusinessImpact {
  expected_revenue?: number;
  actual_revenue?: number;
  estimated_loss?: number;
  loss_percent?: number;
  detail?: string;
  status?: 'NOT_AVAILABLE';
}

export interface Coverage {
  total_checks: number;
  passed: number;
  warned: number;
  failed: number;
  impacted: number;
  skipped: number;
  skipped_details?: { check_id: string; reason: string }[];
  full_coverage: boolean;
  verdict_caveat?: string;
}

export interface LayerStatus {
  bronze: string;
  silver: string;
  gold: string;
}

export interface AurumReport {
  project: string;
  description: string;
  pipeline: string;
  dataset: string;
  run_id: string;
  layer_status: LayerStatus;
  final_verdict: string;
  severity: string;
  first_failed_layer: string | null;
  root_cause: RootCause;
  business_impact: BusinessImpact;
  suggested_action: string;
  trust_score: number;
  trust_narrative: string;
  coverage: Coverage;
  detection_layers: {
    layer_1_rules: CheckResult[];
    layer_2_reconciliation: CheckResult[];
    layer_3_robust_anomaly: CheckResult[];
  };
  checks: {
    bronze: CheckResult[];
    silver: CheckResult[];
    gold: CheckResult[];
    cross_layer: CheckResult[];
  };
}

export const REPORT_KEYS = [
  'project',
  'description',
  'pipeline',
  'dataset',
  'run_id',
  'layer_status',
  'final_verdict',
  'severity',
  'first_failed_layer',
  'root_cause',
  'business_impact',
  'suggested_action',
  'trust_score',
  'trust_narrative',
  'coverage',
  'detection_layers',
  'checks',
] as const;
