/** Shared friendly labels for validation run modes — keep UI copy consistent. */

import type { ValidationRunSummary } from '@/lib/aurumApi';

export function runSourceLabel(mode: string): string {
  switch (mode) {
    case 'upload':
      return 'Uploaded file';
    case 'connector':
      return 'Database connection';
    case 'demo':
      return 'Sample dataset';
    case 'live':
      return 'Live validation';
    default:
      return 'Validation';
  }
}

export function getRunDisplayName(run: Pick<
  ValidationRunSummary,
  'mode' | 'display_name' | 'source_schema' | 'source_table' | 'started_at'
>): string {
  const stored = run.display_name?.trim();
  if (stored) return stored;

  if (run.mode === 'demo') return 'Sample dataset';

  if (run.mode === 'connector') {
    const schema = run.source_schema?.trim();
    const table = run.source_table?.trim();
    if (schema && table) return `${schema}.${table}`;
    const date = run.started_at?.slice(0, 10) ?? 'unknown date';
    return `Database connection (${date})`;
  }

  if (run.mode === 'upload') {
    const date = run.started_at?.slice(0, 10) ?? 'unknown date';
    return `Uploaded file (${date})`;
  }

  const date = run.started_at?.slice(0, 10) ?? 'unknown date';
  return `Validation (${date})`;
}

/** Dropdown / list label — name plus optional trust score. */
export function formatRunOptionLabel(
  run: Pick<ValidationRunSummary, 'mode' | 'display_name' | 'source_schema' | 'source_table' | 'started_at' | 'trust_score'>,
): string {
  const name = getRunDisplayName(run);
  const score = run.trust_score != null ? ` (score ${run.trust_score})` : '';
  return `${name}${score}`;
}

export function formatRelativeOrDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const delta = Date.now() - ms;
  const sec = Math.round(delta / 1000);
  if (sec < 45) return 'Just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
  const day = Math.round(hr / 24);
  if (day < 14) return `${day} day${day === 1 ? '' : 's'} ago`;
  return new Date(ms).toLocaleString();
}
