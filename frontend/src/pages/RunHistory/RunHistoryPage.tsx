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

function runModeDisplay(mode: string): { label: string; variant: 'pass' | 'warning' | 'failed' | 'default' | 'primary' | 'secondary' | 'accent' } {
  switch (mode) {
    case 'demo':
      return { label: 'Demo', variant: 'warning' };
    case 'upload':
      return { label: 'Upload', variant: 'primary' };
    case 'connector':
      return { label: 'Connector', variant: 'accent' };
    case 'live':
      return { label: 'Live', variant: 'pass' };
    default:
      return { label: mode, variant: 'default' };
  }
}

export function RunHistoryPage() {
  const _navigate = useNavigate();
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
    <div className="min-h-full p-6 space-y-5 animate-fade-in relative bg-[#0b0f19]">
      <PageAssistant page="history" runId={report?.run_id} />

      <div className="border-b border-[#1e293b] pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Run History</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="mt-1 text-sm text-[#94a3b8]">
          Recent validation and transformation runs recorded in this workspace.
        </p>
      </div>

      {!backendReachable ? (
        <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-5 text-xs text-[#94a3b8] space-y-2">
          <p className="font-semibold text-[#f8fafc] text-sm">Run Archive Unavailable (Offline Mode)</p>
          <p>
            GET /runs requires an active backend API server connection.
          </p>
          {report && (
            <p className="mt-2 text-xs text-[#64748b] font-mono">
              Current report context: {report.run_id} ({report.final_verdict})
            </p>
          )}
        </div>
      ) : runsQuery.isLoading ? (
        <LoadingSkeleton count={3} className="h-16" />
      ) : runsQuery.isError ? (
        <p className="text-sm text-[#94a3b8]">
          Could not load run history from backend API.
        </p>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 text-center text-xs text-[#94a3b8]">
          <p className="font-semibold text-[#f8fafc] text-sm">No Recorded Runs</p>
          <p className="mt-1">validation_runs table is empty. Trigger runs in Bronze, Silver, or Gold to populate history.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[#1e293b] bg-[#111827] shadow-sm">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#1e293b] bg-[#131a29] text-left uppercase tracking-wider text-[#94a3b8]">
                <th className="px-4 py-3 font-semibold">Run ID / Name</th>
                <th className="px-4 py-3 font-semibold">Mode</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Started</th>
                <th className="px-4 py-3 font-semibold">Finished</th>
                <th className="px-4 py-3 font-semibold">Trust Score</th>
                <th className="px-4 py-3 font-semibold">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1e293b]">
              {runs.map((run) => (
                <tr
                  key={run.run_id}
                  className="hover:bg-[#131a29] transition-colors"
                >
                  <td className="px-4 py-3.5">
                    <div className="font-semibold text-[#f8fafc]">{getRunDisplayName(run)}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-[#06b6d4]">{run.run_id}</div>
                  </td>
                  <td className="px-4 py-3.5">
                    {(() => {
                      const { label, variant } = runModeDisplay(run.mode);
                      return <Badge variant={variant}>{label}</Badge>;
                    })()}
                  </td>
                  <td className="px-4 py-3.5">
                    <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge>
                  </td>
                  <td className="px-4 py-3.5 text-[#94a3b8] font-mono">{formatTimestamp(run.started_at)}</td>
                  <td className="px-4 py-3.5 text-[#94a3b8] font-mono">{formatTimestamp(run.finished_at)}</td>
                  <td className="px-4 py-3.5 font-mono font-semibold text-[#f8fafc]">
                    {run.trust_score != null ? `${run.trust_score}/100` : '—'}
                  </td>
                  <td className="px-4 py-3.5">
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
            'text-xs text-[#64748b]',
            !runs.some((r) => r.run_id === report.run_id) && 'text-[#f59e0b]',
          )}
        >
          Active report context: <span className="font-mono text-[#f8fafc]">{report.run_id}</span>
          {!runs.some((r) => r.run_id === report.run_id) &&
            ' (in-memory or fixture run).'}
        </p>
      )}
    </div>
  );
}
