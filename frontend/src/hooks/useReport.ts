import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  fetchLatestReport,
  fetchReportByRunId,
  runValidation,
  getMetadataHealth,
} from '@/lib/aurumApi';
import { useAppMode } from '@/context/AppModeContext';
import type { DataSourceMode } from '@/types/appMode';
import type { AurumReport } from '@/types/report';
import sampleReportJson from '@/fixtures/sample_report.json';

const sampleReport = sampleReportJson as AurumReport;

export type ReportSource = Exclude<DataSourceMode, 'loading' | 'planned'>;

export interface ReportPayload {
  report: AurumReport;
  source: ReportSource;
}

/** A run_id produced by a user CSV upload (POST /datasets/upload). */
export function isUploadRunId(runId: string): boolean {
  return runId.startsWith('upload_');
}

/** A run_id from live Postgres connector validation. */
export function isConnectorRunId(runId: string): boolean {
  return runId.startsWith('connector_');
}

/**
 * True when the run already has a persisted report from upload/connector —
 * do NOT call POST /runs (that always re-runs the Olist demo).
 */
export function isPersistedUserRunId(runId: string | undefined | null): boolean {
  if (!runId) return false;
  return isUploadRunId(runId) || isConnectorRunId(runId);
}

/** Append ?runId= when navigating within a specific run's validate/report flow. */
export function withRunIdQuery(path: string, runId: string | undefined | null): string {
  if (!runId) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}runId=${encodeURIComponent(runId)}`;
}

async function loadReportByRunId(
  runId: string,
  displayMode: DataSourceMode,
): Promise<ReportPayload> {
  // Deep-linked / uploaded report: fetch the SPECIFIC run by id. This reads
  // SQLite app-state on the backend (independent of metadata Postgres), so an
  // uploaded report is retrievable on reload. We deliberately do NOT fall back
  // to the demo snapshot here — showing demo data under an upload run_id would
  // be the wrong-data bug this path exists to prevent.
  const report = await fetchReportByRunId(runId);
  const source: ReportSource = isUploadRunId(runId) || isConnectorRunId(runId)
    ? 'user_upload'
    : displayMode === 'live'
      ? 'live'
      : 'verified_snapshot';
  return { report, source };
}

async function loadLatestReport(displayMode: DataSourceMode): Promise<ReportPayload> {
  const source: ReportSource =
    displayMode === 'live' ? 'live' : 'verified_snapshot';

  try {
    // Defensive DB probe: if metadata Postgres is not reachable, serve the
    // verified snapshot instead of pretending the fetched report is live.
    const health = await getMetadataHealth().catch(() => ({ status: 'error' }));
    if (health.status !== 'ok') {
      return { report: sampleReport, source: 'verified_snapshot' };
    }
    const report = await fetchLatestReport();
    return { report, source };
  } catch {
    return { report: sampleReport, source: 'verified_snapshot' };
  }
}

export function useReport() {
  const { displayMode, isResolved } = useAppMode();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  const query = useQuery({
    queryKey: ['aurum', 'report', runId ?? 'latest', displayMode],
    queryFn: () =>
      runId ? loadReportByRunId(runId, displayMode) : loadLatestReport(displayMode),
    enabled: isResolved,
    staleTime: 15_000,
  });

  // While app-mode is still resolving, the query is disabled (enabled: isResolved),
  // which leaves react-query's isLoading false and would flash an empty state on a
  // hard page load. Treat "not yet resolved" as loading so pages show a skeleton
  // until the snapshot/live decision and the report are both settled.
  return {
    ...query,
    isLoading: query.isLoading || !isResolved,
  };
}

export function useRunValidation() {
  const queryClient = useQueryClient();
  const { canRunValidation } = useAppMode();

  return async (runId = 'demo_run_001') => {
    if (!canRunValidation) {
      throw new Error('Live validation is unavailable in snapshot mode.');
    }
    const report = await runValidation(runId);
    const payload: ReportPayload = { report, source: 'live' };
    queryClient.setQueryData(['aurum', 'report', 'latest', 'live'], payload);
    return payload;
  };
}
