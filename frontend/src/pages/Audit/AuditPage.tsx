import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/Badge';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { PageAssistant } from '@/components/common/PageAssistant';
import { useAppMode } from '@/context/AppModeContext';
import { fetchRuns, type ValidationRunSummary } from '@/lib/aurumApi';
import { formatRelativeOrDate, getRunDisplayName, runSourceLabel } from '@/utils/runLabels';

function verdictVariant(verdict: string | null): 'pass' | 'warning' | 'failed' | 'secondary' {
  if (!verdict) return 'secondary';
  const u = verdict.toUpperCase();
  if (u === 'TRUSTED' || u === 'PASS') return 'pass';
  if (u === 'WARNING' || u === 'WARN') return 'warning';
  return 'failed';
}

export function AuditPage() {
  const { displayMode, backendReachable } = useAppMode();

  const runsQuery = useQuery({
    queryKey: ['aurum', 'runs'],
    queryFn: fetchRuns,
    enabled: backendReachable,
    staleTime: 15_000,
    retry: false,
  });

  const runs = runsQuery.data?.runs ?? [];

  return (
    <div className="min-h-full p-6 space-y-5 animate-fade-in relative bg-[#0b0f19]">
      <PageAssistant page="history" />

      <div className="border-b border-[#1e293b] pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Audit &amp; Governance</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="mt-1 text-sm text-[#94a3b8]">
          System activity, execution claims, and validation audit log.
        </p>
      </div>

      {!backendReachable ? (
        <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-5 text-xs text-[#94a3b8]">
          <p className="font-semibold text-[#f8fafc] text-sm">Audit Log Unavailable (Offline Mode)</p>
          <p className="mt-1">
            Run history requires active backend API connection.
          </p>
        </div>
      ) : runsQuery.isLoading ? (
        <LoadingSkeleton count={4} className="h-12" />
      ) : runsQuery.isError ? (
        <p className="text-xs text-[#f59e0b]">
          Could not load validation runs from backend API.
        </p>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 text-center text-xs text-[#94a3b8]">
          <p className="font-semibold text-[#f8fafc] text-sm">No Recorded Audit Logs</p>
          <p className="mt-1">
            Validate source tables or run transformations to populate governance records.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#1e293b] bg-[#111827] shadow-sm">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#1e293b] bg-[#131a29] text-left uppercase tracking-wider text-[#94a3b8]">
                <th className="px-4 py-3 font-semibold">Timestamp</th>
                <th className="px-4 py-3 font-semibold">Run ID / Name</th>
                <th className="px-4 py-3 font-semibold">Type</th>
                <th className="px-4 py-3 font-semibold">Verdict</th>
                <th className="px-4 py-3 font-semibold">Trust Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1e293b]">
              {runs.map((run: ValidationRunSummary) => (
                <tr
                  key={run.run_id}
                  className="hover:bg-[#131a29] transition-colors"
                >
                  <td className="px-4 py-3.5 text-[#94a3b8] font-mono">
                    {formatRelativeOrDate(run.finished_at || run.started_at)}
                  </td>
                  <td className="px-4 py-3.5">
                    <div className="font-semibold text-[#f8fafc]">{getRunDisplayName(run)}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-[#06b6d4]">{run.run_id}</div>
                  </td>
                  <td className="px-4 py-3.5 text-[#94a3b8] font-mono">{runSourceLabel(run.mode)}</td>
                  <td className="px-4 py-3.5">
                    {run.final_verdict ? (
                      <Badge variant={verdictVariant(run.final_verdict)}>
                        {run.final_verdict}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">{run.status}</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3.5 text-[#f8fafc] font-mono font-semibold">
                    {run.trust_score != null ? `${run.trust_score}/100` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
