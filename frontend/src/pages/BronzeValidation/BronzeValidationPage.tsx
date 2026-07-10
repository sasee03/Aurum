import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { ReportCheckList } from '@/components/common/ReportCheckList';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import { countChecksByDisplay } from '@/utils/reportFormat';

export function BronzeValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();

  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const checks = report?.checks.bronze ?? [];
  const { pass, warning, fail } = countChecksByDisplay(checks);

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="bronze" layer="bronze" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Bronze Validation</h2>
          <DataSourceBadge mode={displayMode} />
          {report && (
            <Badge variant={report.layer_status.bronze === 'PASS' ? 'pass' : 'failed'}>
              Layer {report.layer_status.bronze}
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Raw ingestion quality checks on your dataset
        </p>
        <div className="flex gap-2 mt-4">
          <Badge variant="pass">{pass} PASS</Badge>
          <Badge variant="warning">{warning} WARNING</Badge>
          <Badge variant="failed">{fail} FAIL</Badge>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 flex flex-col gap-4 bg-[#090a10]">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-24" />
        ) : (
          <ReportCheckList checks={checks} />
        )}
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/validate/execution`, activeRunId))
          }
        >
          Back to Dashboard
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/validate/silver`, activeRunId))
          }
        >
          Proceed to Silver Validation
        </Button>
      </div>
    </div>
  );
}
