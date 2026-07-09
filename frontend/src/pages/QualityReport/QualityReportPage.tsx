import { useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  FileSpreadsheet,
  Share2,
  CheckCircle2,
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { VerdictBadge } from '@/components/ui/Badge';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { REPORT_KEYS, type AurumReport } from '@/types/report';
import { fetchReportByRunId } from '@/lib/aurumApi';
import { formatBrl } from '@/utils/reportFormat';
import { cn } from '@/utils/cn';

/** Colour a verdict/status string consistently with the rest of the app. */
function statusColor(value: string | null | undefined): string {
  const u = (value ?? '').toUpperCase();
  if (u === 'PASS' || u === 'TRUSTED') return 'text-[#22c55e]';
  if (u === 'FAIL' || u === 'NOT TRUSTED') return 'text-[#ef4444]';
  if (u === 'IMPACTED' || u === 'WARNING' || u === 'WARN') return 'text-[#f59e0b]';
  return 'text-[#f1f5f9]';
}

/**
 * Affected orders = unexplained valid-row loss from the reconciliation layer.
 * Real value drawn verbatim from detection_layers.layer_2_reconciliation → L2-REC-COUNT.
 */
function getAffectedOrders(report: AurumReport): number | null {
  const recon = report.detection_layers?.layer_2_reconciliation ?? [];
  const countCheck = recon.find((c) => c.check_id === 'L2-REC-COUNT');
  const observed = countCheck?.observed as Record<string, unknown> | undefined;
  const value = observed?.missing_valid ?? observed?.unexplained_loss;
  return typeof value === 'number' ? value : null;
}

function downloadReportJson(report: AurumReport) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `aurum_report_${report.run_id}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

interface RowProps {
  label: string;
  children: React.ReactNode;
}

function ReportRow({ label, children }: RowProps) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[#1c1d2a] px-4 py-3 last:border-b-0">
      <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
        {label}
      </span>
      <span className="max-w-[60%] text-right text-sm font-medium">{children}</span>
    </div>
  );
}

export function QualityReportPage() {
  const { id: _id } = useParams<{ id: string }>();
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();
  const [jsonOpen, setJsonOpen] = useState(false);
  const [byIdOpen, setByIdOpen] = useState(false);
  const [byIdLoaded, setByIdLoaded] = useState(false);
  const [byIdUnavailable, setByIdUnavailable] = useState(false);
  const report = data?.report;
  const reportBadgeMode = data?.source === 'user_upload' ? 'user_upload' : displayMode;

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

  function previewExport(kind: string) {
    toast(`${kind} export is planned — use JSON export for now.`, { icon: 'ℹ️' });
  }

  const affectedOrders = report ? getAffectedOrders(report) : null;
  // suggested_action is a single deterministic string; split on newlines only
  // (do not fabricate multiple steps that the engine did not emit).
  const suggestedActions = report?.suggested_action
    ? report.suggested_action.split('\n').map((s) => s.trim()).filter(Boolean)
    : [];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={report?.run_id} />
      <PageAssistant page="validation" runId={report?.run_id} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Quality Report</h2>
        <DataSourceBadge mode={reportBadgeMode} />
        <span className="text-xs text-[#6b7280]">17 top-level keys — verbatim engine output</span>

        {report && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => downloadReportJson(report)}
              className="flex items-center gap-1.5 rounded-lg bg-[#6366f1] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#5457e5]"
            >
              <Download size={14} /> JSON
            </button>
            <button
              type="button"
              onClick={() => previewExport('PDF')}
              className="flex items-center gap-1.5 rounded-lg border border-[#252637] bg-[#13141e] px-3 py-1.5 text-xs font-semibold text-[#94a3b8] hover:bg-[#1a1b28]"
            >
              <FileText size={14} /> PDF
            </button>
            <button
              type="button"
              onClick={() => previewExport('Excel')}
              className="flex items-center gap-1.5 rounded-lg border border-[#252637] bg-[#13141e] px-3 py-1.5 text-xs font-semibold text-[#94a3b8] hover:bg-[#1a1b28]"
            >
              <FileSpreadsheet size={14} /> Excel
            </button>
            <button
              type="button"
              onClick={() => previewExport('Share')}
              className="flex items-center gap-1.5 rounded-lg border border-[#252637] bg-[#13141e] px-3 py-1.5 text-xs font-semibold text-[#94a3b8] hover:bg-[#1a1b28]"
            >
              <Share2 size={14} /> Share
            </button>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-32" />
        ) : report ? (
          <>
            {/* Formatted report table — real values from the 17-key contract */}
            <div className="rounded-xl border border-[#252637] bg-[#13141e]">
              <div className="flex items-center gap-3 border-b border-[#252637] px-4 py-3">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Report summary</h3>
                <VerdictBadge verdict={report.final_verdict} />
              </div>
              <ReportRow label="Run ID">
                <span className="font-mono text-[#f1f5f9]">{report.run_id}</span>
              </ReportRow>
              <ReportRow label="Timestamp">
                <span className="text-[#6b7280]">Not in report contract</span>
              </ReportRow>
              <ReportRow label="Bronze quality">
                <span className={statusColor(report.layer_status.bronze)}>
                  {report.layer_status.bronze}
                </span>
              </ReportRow>
              <ReportRow label="Silver quality">
                <span className={statusColor(report.layer_status.silver)}>
                  {report.layer_status.silver}
                </span>
              </ReportRow>
              <ReportRow label="Gold quality">
                <span className={statusColor(report.layer_status.gold)}>
                  {report.layer_status.gold}
                </span>
              </ReportRow>
              <ReportRow label="Failed layer">
                <span className={statusColor('FAIL')}>{report.first_failed_layer ?? '—'}</span>
              </ReportRow>
              <ReportRow label="Code issue">
                <span className="font-mono text-[#ef4444]">
                  {report.root_cause?.suspected_filter ?? '—'}
                </span>
              </ReportRow>
              <ReportRow label="Data issue">
                <span className="text-[#f59e0b]">{report.root_cause?.summary ?? '—'}</span>
              </ReportRow>
              <ReportRow label="Revenue impact">
                <span className="text-[#ef4444]">
                  {formatBrl(report.business_impact?.estimated_loss)}
                </span>
              </ReportRow>
              <ReportRow label="Affected orders">
                <span className="text-[#f1f5f9]">
                  {affectedOrders !== null ? affectedOrders.toLocaleString('en-US') : '—'}
                </span>
              </ReportRow>
              <ReportRow label="Affected customers">
                <span className="text-[#6b7280]">Not in report contract</span>
              </ReportRow>
              <ReportRow label="Overall trust score">
                <span className={statusColor(report.final_verdict)}>
                  {report.trust_score} / 100 — {report.severity}
                </span>
              </ReportRow>
            </div>

            {/* Final verdict box */}
            <div
              className={cn(
                'rounded-xl border p-5 text-center',
                statusColor(report.final_verdict) === 'text-[#ef4444]'
                  ? 'border-[#7f1d1d] bg-[#450a0a]/40'
                  : statusColor(report.final_verdict) === 'text-[#f59e0b]'
                    ? 'border-[#78350f] bg-[#451a03]/40'
                    : 'border-[#14532d] bg-[#052e16]/40',
              )}
            >
              <p className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                Final verdict
              </p>
              <p className={cn('mt-1 text-2xl font-bold', statusColor(report.final_verdict))}>
                {report.final_verdict}
              </p>
            </div>

            {/* Suggested actions — verbatim from suggested_action */}
            {suggestedActions.length > 0 && (
              <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                  Suggested actions
                </h3>
                <ul className="space-y-2">
                  {suggestedActions.map((action, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-[#94a3b8]">
                      <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0 text-[#6366f1]" />
                      <span>{action}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Report key chips */}
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

            {/* Full JSON */}
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
