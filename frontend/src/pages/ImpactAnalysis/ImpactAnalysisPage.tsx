import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Target, Wrench } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { FlowBackButton } from '@/components/common/FlowBackButton';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import { formatBrl } from '@/utils/reportFormat';
import { getFlowBackTarget } from '@/utils/flowNavigation';
import { cn } from '@/utils/cn';

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '0.00%';
  return `${value.toFixed(2)}%`;
}

function positiveNumber(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(value, 0) : 0;
}

interface RevenueComparisonProps {
  expected: number;
  actual: number;
}

function RevenueComparison({ expected, actual }: RevenueComparisonProps) {
  const max = Math.max(expected, actual, 1);
  const rows = [
    { label: 'Expected', value: expected, color: 'bg-[#22c55e]' },
    { label: 'Actual', value: actual, color: 'bg-[#f97316]' },
  ];

  return (
    <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[#f1f5f9]">Revenue comparison</h3>
          <p className="mt-1 text-xs text-[#6b7280]">
            Expected valid Bronze revenue vs current Gold revenue.
          </p>
        </div>
      </div>
      <div className="space-y-4">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[72px_1fr_auto] items-center gap-3">
            <span className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
              {row.label}
            </span>
            <div className="h-4 overflow-hidden rounded-full bg-[#1a1b28]">
              <div
                className={cn('h-full rounded-full transition-all duration-700', row.color)}
                style={{ width: `${Math.max((row.value / max) * 100, row.value > 0 ? 2 : 0)}%` }}
              />
            </div>
            <span className="min-w-[112px] text-right font-mono text-xs text-[#f1f5f9]">
              {formatBrl(row.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ImpactAnalysisPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();
  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const impact = report?.business_impact;
  const rootCause = report?.root_cause;
  const suggestedAction = report?.suggested_action;
  const back = getFlowBackTarget(`/projects/${id}/report/impact`, id, activeRunId);
  const expectedRevenue = positiveNumber(impact?.expected_revenue);
  const actualRevenue = positiveNumber(impact?.actual_revenue);
  const estimatedLoss = positiveNumber(impact?.estimated_loss);
  const lossPercent = positiveNumber(impact?.loss_percent);
  const hasLoss = estimatedLoss > 0 || lossPercent > 0;
  const failedCheckId = rootCause?.failed_check_ids?.[0] ?? rootCause?.evidence?.[0]?.check_id;
  const rootCauseTarget = failedCheckId
    ? `${withRunIdQuery(`/projects/${id}/validate/silver`, activeRunId)}#${encodeURIComponent(failedCheckId)}`
    : withRunIdQuery(`/projects/${id}/validate/silver`, activeRunId);
  const rootCauseLabel =
    rootCause?.summary || rootCause?.suspected_filter || 'No failed transformation cause reported.';

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} />
      <PageAssistant page="validation" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Impact Analysis</h2>
        <DataSourceBadge mode={displayMode} />
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-20" />
        ) : impact?.status === 'NOT_AVAILABLE' ? (
          <p className="text-[#94a3b8]">{impact.detail}</p>
        ) : (
          <>
            <div
              className={cn(
                'rounded-xl border p-6',
                hasLoss
                  ? 'border-[#7f1d1d] bg-[#450a0a]/35'
                  : 'border-[#14532d] bg-[#052e16]/35',
              )}
            >
              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-[#6b7280]">
                    Revenue gap
                  </p>
                  <div
                    className={cn(
                      'mt-2 text-5xl font-black tracking-tight md:text-6xl',
                      hasLoss ? 'text-[#ef4444]' : 'text-[#22c55e]',
                    )}
                  >
                    {formatPercent(lossPercent)}
                  </div>
                  <p className="mt-2 text-sm text-[#94a3b8]">
                    {hasLoss
                      ? `${formatBrl(estimatedLoss)} estimated revenue loss`
                      : 'No detected revenue loss in this run'}
                  </p>
                </div>
                <div className="max-w-xl rounded-lg border border-[#252637] bg-[#0d0e14]/70 p-4">
                  <p className="text-sm leading-relaxed text-[#94a3b8]">{impact?.detail}</p>
                </div>
              </div>
            </div>

            <RevenueComparison expected={expectedRevenue} actual={actualRevenue} />

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <MetricCard label="Expected Revenue (BRL)" value={formatBrl(impact?.expected_revenue)} />
              <MetricCard label="Actual Revenue (BRL)" value={formatBrl(impact?.actual_revenue)} />
              <MetricCard
                label={hasLoss ? 'Estimated Loss (BRL)' : 'Estimated Loss'}
                value={formatBrl(impact?.estimated_loss)}
                subValue={hasLoss ? `${formatPercent(lossPercent)} gap` : 'No loss detected'}
                valueClass={hasLoss ? 'text-[#ef4444]' : 'text-[#22c55e]'}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5">
                <div className="mb-3 flex items-center gap-2">
                  <Target size={16} className="text-[#f97316]" />
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">Where it came from</h3>
                </div>
                <p className="text-sm leading-relaxed text-[#94a3b8]">
                  {hasLoss ? 'This loss traces to:' : 'Current validation trace:'}{' '}
                  <span className="font-medium text-[#f1f5f9]">
                    {rootCauseLabel}
                  </span>
                </p>
                {rootCause?.suspected_filter && rootCause.summary !== rootCause.suspected_filter && (
                  <p className="mt-2 font-mono text-xs text-[#f59e0b]">
                    {rootCause.suspected_filter}
                  </p>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-4"
                  onClick={() => navigate(rootCauseTarget)}
                >
                  {hasLoss ? 'Open failed Silver check' : 'Open Silver validation'}
                </Button>
              </div>

              <div
                className={cn(
                  'rounded-xl border p-5',
                  hasLoss
                    ? 'border-[#78350f] bg-[#451a03]/35'
                    : 'border-[#14532d] bg-[#052e16]/35',
                )}
              >
                <div className="mb-3 flex items-center gap-2">
                  {hasLoss ? (
                    <Wrench size={16} className="text-[#f59e0b]" />
                  ) : (
                    <CheckCircle2 size={16} className="text-[#22c55e]" />
                  )}
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">
                    {hasLoss ? 'Suggested fix' : 'Current action'}
                  </h3>
                </div>
                <p className="text-sm leading-relaxed text-[#f1f5f9]">
                  {suggestedAction || 'No remediation action is required for this run.'}
                </p>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="border-t border-[#252637] px-6 py-4 flex items-center justify-between">
        {back ? <FlowBackButton path={back.path} label={back.label} /> : <span />}
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() =>
            navigate(withRunIdQuery(`/projects/${id}/report/trust`, activeRunId))
          }
        >
          Trust Scoring
        </Button>
      </div>
    </div>
  );
}
