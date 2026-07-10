import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/Badge';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { PageAssistant } from '@/components/common/PageAssistant';
import { useAppMode } from '@/context/AppModeContext';
import { fetchRuns, type ValidationRunSummary } from '@/lib/aurumApi';
import { formatRelativeOrDate, getRunDisplayName, runSourceLabel } from '@/utils/runLabels';
import { cn } from '@/utils/cn';

function verdictVariant(verdict: string | null): 'pass' | 'warning' | 'failed' | 'secondary' {
  if (!verdict) return 'secondary';
  const u = verdict.toUpperCase();
  if (u === 'TRUSTED' || u === 'PASS') return 'pass';
  if (u === 'WARNING' || u === 'WARN') return 'warning';
  return 'failed';
}

function openReportPath(run: ValidationRunSummary): string {
  const project = run.project_id || 'shared';
  return `/projects/${encodeURIComponent(project)}/report/quality?runId=${encodeURIComponent(run.run_id)}`;
}

export function AuditPage() {
  const navigate = useNavigate();
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
    <div className="min-h-full p-6 space-y-4 animate-fade-in relative">
      <PageAssistant page="history" />

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Audit &amp; Governance</h2>
        <DataSourceBadge mode={displayMode} />
      </div>

      <p className="text-sm text-[#6b7280] max-w-3xl">
        Validation activity for this workspace. Actor identity is not tracked — Aurum has no
        user accounts yet.
      </p>

      {!backendReachable ? (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-sm text-[#94a3b8]">
          <p className="font-medium text-[#f1f5f9]">Audit log unavailable</p>
          <p className="mt-1">
            Run history requires the API. Start the backend to see validation activity.
          </p>
        </div>
      ) : runsQuery.isLoading ? (
        <LoadingSkeleton count={4} className="h-12" />
      ) : runsQuery.isError ? (
        <p className="text-sm text-[#f59e0b]">
          Could not load validation runs. Try again from Run History.
        </p>
      ) : runs.length === 0 ? (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-sm text-[#94a3b8]">
          <p className="font-medium text-[#f1f5f9]">No validation runs yet</p>
          <p className="mt-1">
            Validate an upload, connect a table, or run the sample dataset to populate this log.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#252637]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#252637] bg-[#0d0e14] text-left text-xs uppercase tracking-widest text-[#6b7280]">
                <th className="px-4 py-2 font-semibold">When</th>
                <th className="px-4 py-2 font-semibold">Run</th>
                <th className="px-4 py-2 font-semibold">Type</th>
                <th className="px-4 py-2 font-semibold">Verdict</th>
                <th className="px-4 py-2 font-semibold">Trust score</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.run_id}
                  className={cn(
                    'border-b border-[#252637] last:border-b-0 cursor-pointer hover:bg-[#1a1b28] transition-colors',
                  )}
                  onClick={() => navigate(openReportPath(run))}
                  title={`Open quality report for ${getRunDisplayName(run)}`}
                >
                  <td className="px-4 py-3 text-[#94a3b8]">
                    {formatRelativeOrDate(run.finished_at || run.started_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-[#f1f5f9]">{getRunDisplayName(run)}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-[#6b7280]">{run.run_id}</div>
                  </td>
                  <td className="px-4 py-3 text-[#94a3b8]">{runSourceLabel(run.mode)}</td>
                  <td className="px-4 py-3">
                    {run.final_verdict ? (
                      <Badge variant={verdictVariant(run.final_verdict)}>
                        {run.final_verdict}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">{run.status}</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-[#f1f5f9]">
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
