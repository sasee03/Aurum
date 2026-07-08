import { PageAssistant } from '@/components/common/PageAssistant';
import { PlannedBanner } from '@/components/common/PlannedBanner';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';

export function RunHistoryPage() {
  const { displayMode } = useAppMode();
  const { data } = useReport();
  const report = data?.report;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative p-6 space-y-4">
      <PageAssistant page="history" runId={report?.run_id} />

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Run History</h2>
        <DataSourceBadge mode={displayMode} />
      </div>

      <PlannedBanner
        detail="Per-run archive is planned (Ring 5). Today you can review the latest report and ask Aurum Assistant to compare against engine history."
      />

      {report && (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-sm">
          <p>
            <strong className="text-[#f1f5f9]">Current run:</strong> {report.run_id}
          </p>
          <p className="text-[#94a3b8] mt-1">Verdict: {report.final_verdict}</p>
          <p className="text-[#6b7280] mt-2 text-xs">
            Ask: &quot;Compare this run with history&quot; or &quot;Is this drop normal?&quot;
          </p>
        </div>
      )}
    </div>
  );
}
