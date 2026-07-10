import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { ReportCheckList } from '@/components/common/ReportCheckList';
import { SQLViewer } from '@/components/common/SQLViewer';
import { RootCauseCard } from '@/components/cards/RootCauseCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import { countChecksByDisplay } from '@/utils/reportFormat';

export function SilverValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();

  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const checks = report?.checks.silver ?? [];
  const { pass, warning, fail } = countChecksByDisplay(checks);
  const root = report?.root_cause;
  const failedEvidence = root?.evidence?.[0];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="silver" layer="silver" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Silver Validation</h2>
          <DataSourceBadge mode={displayMode} />
          {report && (
            <Badge variant={report.layer_status.silver === 'FAIL' ? 'failed' : 'pass'}>
              Layer {report.layer_status.silver}
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Transformation and enrichment checks on your dataset
        </p>
        <div className="flex gap-2 mt-4">
          <Badge variant="pass">{pass} PASS</Badge>
          <Badge variant="warning">{warning} WARNING</Badge>
          <Badge variant="failed">{fail} FAIL</Badge>
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-6 gap-6 bg-[#090a10] grid grid-cols-1 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4 overflow-y-auto scrollbar-thin">
          {isLoading ? (
            <LoadingSkeleton count={3} className="h-24" />
          ) : (
            <>
              {root && (
                <RootCauseCard
                  explanation={root.summary}
                  affectedRecords={root.suspected_filter ?? report?.first_failed_layer ?? '—'}
                  suggestedFix={report?.suggested_action ?? '—'}
                />
              )}
              <ReportCheckList checks={checks} showSql />
            </>
          )}
        </div>

        <div className="h-full flex flex-col">
          {failedEvidence?.evidence_query ? (
            <SQLViewer
              title={`EVIDENCE — ${failedEvidence.check_id}`}
              code={failedEvidence.evidence_query}
            />
          ) : (
            <p className="text-sm text-[#6b7280]">No evidence SQL in report.</p>
          )}
        </div>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/validate/bronze`, activeRunId))
          }
        >
          Back to Bronze
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/validate/gold`, activeRunId))
          }
        >
          Proceed to Gold Validation
        </Button>
      </div>
    </div>
  );
}
