import { useQuery } from '@tanstack/react-query';
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
import { getSilverAssessment } from '@/lib/aurumApi';
import { layerStatusPresentation } from '@/components/common/LayerStatusRing';
import { countChecksByDisplay } from '@/utils/reportFormat';

export function SilverValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { displayMode, backendReachable } = useAppMode();
  const { data, isLoading } = useReport();

  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const checks = report?.checks.silver ?? [];
  const { pass, warning, fail } = countChecksByDisplay(checks);
  const root = report?.root_cause;
  const failedEvidence = root?.evidence?.[0];
  const assessmentQuery = useQuery({
    queryKey: ['aurum', 'silver-assessment', activeRunId],
    queryFn: () => getSilverAssessment(activeRunId!),
    enabled: Boolean(activeRunId) && backendReachable,
    staleTime: 10_000,
  });
  const summary = assessmentQuery.data?.summary;
  const flaggedRows = assessmentQuery.data?.flagged_rows ?? [];
  const rowColumns = Object.keys(flaggedRows[0] ?? {}).filter(
    (column) => column !== 'is_valid' && column !== 'is_in_silver',
  );

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="silver" layer="silver" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Silver Validation</h2>
          <DataSourceBadge mode={displayMode} />
          {report && (
            <Badge variant={layerStatusPresentation(report.layer_status.silver).badge}>
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
              <div className="rounded-xl border border-[#252637] bg-[#0d0e14]">
                <div className="border-b border-[#252637] px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[#f1f5f9]">Row-Level Assessment</h3>
                      <p className="mt-1 text-xs text-[#6b7280]">
                        Real retained, invalid, and excluded Silver candidates for this run.
                      </p>
                    </div>
                    {summary && (
                      <div className="flex flex-wrap gap-2 text-xs">
                        <Badge variant="default">{summary.total} total</Badge>
                        <Badge variant="pass">{summary.retained} retained</Badge>
                        <Badge variant="warning">{summary.excluded} excluded</Badge>
                        <Badge variant="failed">{summary.invalid} invalid</Badge>
                      </div>
                    )}
                  </div>
                </div>

                {assessmentQuery.isLoading ? (
                  <div className="px-4 py-4">
                    <LoadingSkeleton count={4} className="h-12" />
                  </div>
                ) : assessmentQuery.isError ? (
                  <div className="px-4 py-4 text-sm text-[#f59e0b]">
                    Could not load the Silver row assessment for this run. The summary report is shown,
                    but the detailed retained/excluded rows are unavailable right now.
                  </div>
                ) : flaggedRows.length === 0 ? (
                  <div className="px-4 py-4 text-sm text-[#94a3b8]">
                    No flagged Silver rows were returned for this run.
                  </div>
                ) : (
                  <div className="overflow-x-auto max-h-[320px] scrollbar-thin scrollbar-thumb-[#6b7280]">
                    <table className="w-full text-left text-xs whitespace-nowrap">
                      <thead className="sticky top-0 bg-[#13141e] border-b border-[#252637] text-[#94a3b8]">
                        <tr>
                          {rowColumns.map((column) => (
                            <th key={column} className="px-3 py-2 font-medium">
                              {column}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#252637]">
                        {flaggedRows.map((row, index) => (
                          <tr key={`${row.row_status}-${index}`} className="hover:bg-[#252637]/30 transition-colors">
                            {rowColumns.map((column) => (
                              <td key={column} className="px-3 py-2 align-top text-[#e5e7eb]">
                                {String(row[column] ?? '—')}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
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
