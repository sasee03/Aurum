import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { ReportCheckList } from '@/components/common/ReportCheckList';
import { MetricCard } from '@/components/cards/MetricCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import { countChecksByDisplay, formatBrl } from '@/utils/reportFormat';

export function GoldValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();

  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const checks = report?.checks.gold ?? [];
  const { pass, warning, fail } = countChecksByDisplay(checks);
  const impact = report?.business_impact;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="gold" layer="gold" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Gold Validation</h2>
          <DataSourceBadge mode={displayMode} />
          {report && (
            <Badge variant={report.layer_status.gold === 'IMPACTED' ? 'failed' : 'pass'}>
              Layer {report.layer_status.gold}
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Gold business metrics — impacted when Silver fails upstream.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6 bg-[#090a10]">
        {impact && impact.status !== 'NOT_AVAILABLE' && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <MetricCard label="Expected Revenue" value={formatBrl(impact.expected_revenue)} />
            <MetricCard label="Actual Revenue" value={formatBrl(impact.actual_revenue)} />
            <MetricCard label="Estimated Loss" value={formatBrl(impact.estimated_loss)} />
          </div>
        )}
        <div className="flex gap-2">
          <Badge variant="pass">{pass} PASS</Badge>
          <Badge variant="warning">{warning} WARNING</Badge>
          <Badge variant="failed">{fail} FAIL</Badge>
        </div>
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-24" />
        ) : (
          <ReportCheckList checks={checks} showSql />
        )}
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex justify-between">
        <Button
          variant="ghost"
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/validate/silver`, activeRunId))
          }
        >
          Back to Silver
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/report/impact`, activeRunId))
          }
        >
          View Impact Analysis
        </Button>
      </div>
    </div>
  );
}
