import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { PageAssistant } from '@/components/common/PageAssistant';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { Badge } from '@/components/ui/Badge';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { fetchRuns } from '@/lib/aurumApi';
import { getRunDisplayName } from '@/utils/runLabels';
import { cn } from '@/utils/cn';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function statusBadgeVariant(status: string): 'pass' | 'warning' | 'failed' | 'default' {
  const u = status.toUpperCase();
  if (u === 'COMPLETED' || u === 'PASS') return 'pass';
  if (u === 'FAILED' || u === 'FAIL') return 'failed';
  if (u === 'RUNNING' || u === 'WARN') return 'warning';
  return 'default';
}

function runModeDisplay(mode: string): { label: string; variant: 'pass' | 'warning' | 'failed' | 'default' | 'primary' | 'secondary' } {
  switch (mode) {
    case 'demo':
      return { label: 'Demo', variant: 'warning' };
    case 'upload':
      return { label: 'Upload', variant: 'primary' };
    case 'connector':
      return { label: 'Connector', variant: 'secondary' };
    case 'live':
      // Legacy rows persisted before the honesty fix; show without crashing.
      return { label: 'Live', variant: 'default' };
    default:
      return { label: mode, variant: 'default' };
  }
}

export function RunHistoryPage() {
  const navigate = useNavigate();
  const { displayMode, backendReachable } = useAppMode();
  const { data: reportData } = useReport();

  const runsQuery = useQuery({
    queryKey: ['aurum', 'runs'],
    queryFn: fetchRuns,
    enabled: backendReachable,
    staleTime: 15_000,
    retry: false,
  });

  const runs = runsQuery.data?.runs ?? [];
  const report = reportData?.report;

  return (
    <div className="min-h-full p-6 space-y-4 animate-fade-in relative">
      <PageAssistant page="history" runId={report?.run_id} />

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Run History</h2>
        <DataSourceBadge mode={displayMode} />
      </div>

      <p className="text-sm text-[#6b7280]">
        Recent validation runs from this workspace. Sparse data is expected until live runs are
        recorded.
      </p>

      {!backendReachable ? (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-sm text-[#94a3b8]">
          <p className="font-medium text-[#f1f5f9]">Run archive unavailable in snapshot mode</p>
          <p className="mt-1">
            GET /runs requires the API. With the backend off, no persisted run list is shown — this is
            intentional, not missing data.
          </p>
          {report && (
            <p className="mt-3 text-xs text-[#6b7280]">
              Current loaded report: <span className="font-mono">{report.run_id}</span> (
              {report.final_verdict})
            </p>
          )}
        </div>
      ) : runsQuery.isLoading ? (
        <LoadingSkeleton count={3} className="h-16" />
      ) : runsQuery.isError ? (
        <p className="text-sm text-[#94a3b8]">
          Could not load run history from GET /runs. The API may be degraded.
        </p>
      ) : runs.length === 0 ? (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-sm text-[#94a3b8]">
          <p className="font-medium text-[#f1f5f9]">No persisted runs yet</p>
          <p className="mt-1">
            validation_runs is empty. Trigger POST /runs when the database is live to record history.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[#252637]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#252637] bg-[#0d0e14] text-left text-xs uppercase tracking-widest text-[#6b7280]">
                <th className="px-4 py-2 font-semibold">Run</th>
                <th className="px-4 py-2 font-semibold">Mode</th>
                <th className="px-4 py-2 font-semibold">Status</th>
                <th className="px-4 py-2 font-semibold">Started</th>
                <th className="px-4 py-2 font-semibold">Finished</th>
                <th className="px-4 py-2 font-semibold">Trust score</th>
                <th className="px-4 py-2 font-semibold">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.run_id}
                  className="border-b border-[#252637] last:border-b-0 cursor-pointer hover:bg-[#1a1b28] transition-colors"
                  onClick={() => navigate(`/projects/shared/report/quality?runId=${encodeURIComponent(run.run_id)}`)}
                  title={`Open report for ${getRunDisplayName(run)}`}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-[#f1f5f9]">{getRunDisplayName(run)}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-[#6b7280]">{run.run_id}</div>
                  </td>
                  <td className="px-4 py-3">
                    {(() => {
                      const { label, variant } = runModeDisplay(run.mode);
                      return <Badge variant={variant}>{label}</Badge>;
                    })()}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[#94a3b8]">{formatTimestamp(run.started_at)}</td>
                  <td className="px-4 py-3 text-[#94a3b8]">{formatTimestamp(run.finished_at)}</td>
                  <td className="px-4 py-3 text-[#f1f5f9]">
                    {run.trust_score != null ? `${run.trust_score}/100` : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {run.final_verdict ? (
                      <Badge
                        variant={
                          run.final_verdict === 'TRUSTED'
                            ? 'pass'
                            : run.final_verdict === 'WARNING'
                              ? 'warning'
                              : 'failed'
                        }
                      >
                        {run.final_verdict}
                      </Badge>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report && backendReachable && runs.length > 0 && (
        <p
          className={cn(
            'text-xs text-[#6b7280]',
            !runs.some((r) => r.run_id === report.run_id) && 'text-[#f59e0b]',
          )}
        >
          Loaded report run_id: {report.run_id}
          {!runs.some((r) => r.run_id === report.run_id) &&
            ' — not yet in validation_runs (fixture or in-memory only).'}
        </p>
      )}
    </div>
  );
}
