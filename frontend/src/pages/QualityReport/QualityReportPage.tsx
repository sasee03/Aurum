import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { VerdictBadge } from '@/components/ui/Badge';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { REPORT_KEYS } from '@/types/report';
import { fetchReportByRunId } from '@/lib/aurumApi';
import { formatBrl } from '@/utils/reportFormat';
import { cn } from '@/utils/cn';

export function QualityReportPage() {
  const { id: _id } = useParams<{ id: string }>();
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();
  const [jsonOpen, setJsonOpen] = useState(false);
  const [byIdOpen, setByIdOpen] = useState(false);
  const [byIdLoaded, setByIdLoaded] = useState(false);
  const [byIdUnavailable, setByIdUnavailable] = useState(false);
  const report = data?.report;

  async function loadByRunId() {
    if (!report?.run_id) return;
    setByIdUnavailable(false);
    try {
      await fetchReportByRunId(report.run_id);
      setByIdLoaded(true);
      setByIdOpen(true);
    } catch {
      setByIdUnavailable(true);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={report?.run_id} />
      <PageAssistant page="validation" runId={report?.run_id} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Quality Report</h2>
        <DataSourceBadge mode={displayMode} />
        <span className="text-xs text-[#6b7280]">17 top-level keys — verbatim engine output</span>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {isLoading ? (
          <LoadingSkeleton count={2} className="h-32" />
        ) : report ? (
          <>
            <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5 space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Report summary</h3>
                <VerdictBadge verdict={report.final_verdict} />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard label="Severity" value={report.severity} />
                <MetricCard label="Trust score" value={`${report.trust_score}/100`} subValue="Deterministic" />
                <MetricCard label="Bronze" value={report.layer_status.bronze} />
                <MetricCard label="Silver" value={report.layer_status.silver} />
                <MetricCard label="Gold" value={report.layer_status.gold} />
                <MetricCard label="First failed layer" value={report.first_failed_layer ?? '—'} />
                <MetricCard
                  label="Estimated loss (BRL)"
                  value={formatBrl(report.business_impact?.estimated_loss)}
                />
              </div>
              <p className="text-sm text-[#94a3b8]">{report.root_cause?.summary}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              {REPORT_KEYS.map((key) => (
                <span
                  key={key}
                  className="rounded-md border border-[#252637] px-2 py-1 text-[10px] font-mono text-[#94a3b8]"
                >
                  {key}
                </span>
              ))}
            </div>

            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg border border-[#252637] bg-[#0d0e14] px-4 py-3 text-left text-sm font-medium text-[#f1f5f9] hover:bg-[#1a1b28]"
              onClick={() => setJsonOpen((o) => !o)}
            >
              {jsonOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              Full report JSON (17 keys)
            </button>
            {jsonOpen && (
              <pre className="rounded-lg border border-[#252637] bg-[#0d0e14] p-4 text-xs text-[#94a3b8] overflow-auto max-h-[60vh]">
                {JSON.stringify(report, null, 2)}
              </pre>
            )}

            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="text-xs text-[#6366f1] hover:underline text-left"
                onClick={loadByRunId}
              >
                Verify GET /reports/{'{run_id}'} for {report.run_id}
              </button>
              {byIdUnavailable && (
                <p className="text-sm text-[#94a3b8]">
                  Report by run ID is not available right now. The summary above still reflects the
                  latest loaded report.
                </p>
              )}
              {byIdLoaded && (
                <>
                  <button
                    type="button"
                    className={cn(
                      'flex items-center gap-2 text-xs text-[#94a3b8] hover:text-[#f1f5f9]',
                    )}
                    onClick={() => setByIdOpen((o) => !o)}
                  >
                    {byIdOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    GET /reports/{report.run_id} response
                  </button>
                  {byIdOpen && (
                    <p className="text-xs text-[#6b7280]">
                      Response matches the latest report when the run ID is current.
                    </p>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <p className="text-sm text-[#94a3b8]">
            Quality report is not available right now. Try running validation from the execution
            dashboard.
          </p>
        )}
      </div>
    </div>
  );
}
