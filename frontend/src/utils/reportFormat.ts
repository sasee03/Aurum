import type { CheckResult, CheckStatus } from '@/types/report';

/** Map engine status to ValidationCard display status. */
export function toDisplayStatus(
  status: string,
): 'PASS' | 'WARNING' | 'FAIL' {
  if (status === 'FAIL' || status === 'IMPACTED') return 'FAIL';
  if (status === 'WARN') return 'WARNING';
  if (status === 'SKIPPED') return 'WARNING';
  return 'PASS';
}

export function formatBrl(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1_000_000) {
    return `BRL ${(n / 1_000_000).toFixed(2)} M`;
  }
  return `BRL ${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatObserved(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function formatExpected(value: unknown): string {
  return formatObserved(value);
}

export function layerStageStatus(layerStatus: string): 'SUCCESS' | 'FAILED' | 'QUEUED' {
  if (layerStatus === 'PASS') return 'SUCCESS';
  if (layerStatus === 'FAIL' || layerStatus === 'IMPACTED') return 'FAILED';
  if (layerStatus === 'WARN') return 'SUCCESS';
  return 'QUEUED';
}

export function countChecksByDisplay(checks: CheckResult[]) {
  let pass = 0;
  let warning = 0;
  let fail = 0;
  for (const c of checks) {
    const d = toDisplayStatus(c.status);
    if (d === 'PASS') pass += 1;
    else if (d === 'WARNING') warning += 1;
    else fail += 1;
  }
  return { pass, warning, fail };
}

export function failedChecks(checks: CheckResult[]): CheckResult[] {
  return checks.filter((c) => c.status === 'FAIL' || c.status === 'IMPACTED' || c.status === 'WARN');
}
