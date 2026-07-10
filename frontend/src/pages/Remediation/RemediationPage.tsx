import { useMemo } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge, VerdictBadge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { FlowBackButton } from '@/components/common/FlowBackButton';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { SQLViewer } from '@/components/common/SQLViewer';
import { useAppMode } from '@/context/AppModeContext';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import { layerStatusPresentation } from '@/components/common/LayerStatusRing';
import { getFlowBackTarget } from '@/utils/flowNavigation';
import type { CheckResult, CheckStatus } from '@/types/report';

const ISSUE_STATUSES: CheckStatus[] = ['FAIL', 'WARN', 'IMPACTED'];

function layerBadgeVariant(layer: string): 'warning' | 'secondary' | 'primary' | 'default' {
  const l = layer.toLowerCase();
  if (l.includes('bronze')) return 'warning';
  if (l.includes('silver')) return 'secondary';
  if (l.includes('gold')) return 'primary';
  return 'default';
}

function collectIssueChecks(checks: {
  bronze: CheckResult[];
  silver: CheckResult[];
  gold: CheckResult[];
  cross_layer: CheckResult[];
}): CheckResult[] {
  return [...checks.bronze, ...checks.silver, ...checks.gold, ...checks.cross_layer].filter(
    (c) => ISSUE_STATUSES.includes(c.status),
  );
}

export function RemediationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runIdParam = searchParams.get('runId') ?? undefined;
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();
  const report = data?.report;
  const activeRunId = runIdParam ?? report?.run_id;
  const back = getFlowBackTarget(`/projects/${id}/remediate`, id, activeRunId);

  const issues = useMemo(
    () => (report ? collectIssueChecks(report.checks) : []),
    [report],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="failure" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Remediation Center</h2>
        <DataSourceBadge mode={displayMode} />
        {report && <VerdictBadge verdict={report.final_verdict} />}
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-24" />
        ) : !report ? (
          <p className="text-sm text-[#94a3b8]">
            No validation report is loaded for this run. Run validation or open a report from
            History first.
          </p>
        ) : (
          <>
            {report.suggested_action && (
              <Card className="space-y-2 border-[#6366f1]/30 bg-[#6366f1]/5">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-[#818cf8]">
                  Suggested action
                </p>
                <p className="text-sm font-medium text-[#f1f5f9] leading-relaxed">
                  {report.suggested_action}
                </p>
                {report.root_cause?.summary && (
                  <p className="text-xs text-[#94a3b8] leading-relaxed pt-1 border-t border-[#252637]">
                    {report.root_cause.summary}
                  </p>
                )}
              </Card>
            )}

            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Issues to remediate</h3>
                <Badge variant="secondary">{issues.length} found</Badge>
              </div>

              {issues.length === 0 ? (
                <Card>
                  <p className="text-sm font-medium text-[#22c55e]">No issues found in this run</p>
                  <p className="mt-1 text-xs text-[#94a3b8]">
                    Every check in this report passed (or was skipped). Nothing to remediate.
                  </p>
                </Card>
              ) : (
                <div className="flex flex-col gap-4">
                  {issues.map((check) => (
                    <Card key={`${check.layer}-${check.check_id}`} className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-semibold text-[#f1f5f9]">
                          {check.check_name}
                        </h4>
                        <Badge variant={layerBadgeVariant(check.layer)}>{check.layer}</Badge>
                        <Badge variant={layerStatusPresentation(check.status).badge}>
                          {check.status}
                        </Badge>
                      </div>
                      <p className="text-sm text-[#94a3b8] leading-relaxed">{check.detail}</p>
                      {check.evidence_query && (
                        <div className="max-h-48 overflow-hidden rounded-lg">
                          <SQLViewer
                            title={`Evidence — ${check.check_id}`}
                            code={check.evidence_query}
                          />
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
              )}
            </div>

            <p className="text-xs text-[#6b7280] leading-relaxed max-w-3xl">
              Per-record quarantine and ticketing workflow — coming in a future release. Above:
              the specific checks that failed or warned, plus the engine&apos;s suggested fix,
              from this run&apos;s report.
            </p>
          </>
        )}
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        {back ? <FlowBackButton path={back.path} label={back.label} /> : <span />}
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/report/quality`, activeRunId))
          }
        >
          Open Quality Report
        </Button>
      </div>
    </div>
  );
}
