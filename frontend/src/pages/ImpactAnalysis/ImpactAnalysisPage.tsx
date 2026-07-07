import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useReport } from '@/hooks/useReport';
import { formatBrl } from '@/utils/reportFormat';

export function ImpactAnalysisPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useReport();
  const report = data?.report;
  const impact = report?.business_impact;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={report?.run_id} />
      <PageAssistant page="validation" runId={report?.run_id} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Impact Analysis</h2>
        {data && <DataSourceBadge source={data.source} />}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-20" />
        ) : impact?.status === 'NOT_AVAILABLE' ? (
          <p className="text-[#94a3b8]">{impact.detail}</p>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <MetricCard label="Expected Revenue (BRL)" value={formatBrl(impact?.expected_revenue)} />
              <MetricCard label="Actual Revenue (BRL)" value={formatBrl(impact?.actual_revenue)} />
              <MetricCard
                label="Estimated Loss (BRL)"
                value={formatBrl(impact?.estimated_loss)}
                subValue={impact?.loss_percent != null ? `${impact.loss_percent}% gap` : undefined}
              />
            </div>
            <p className="text-sm text-[#94a3b8]">{impact?.detail}</p>
            <p className="text-xs text-[#6b7280]">
              Values from business_impact.estimated_loss (nested) — not a top-level report key.
            </p>
          </>
        )}
      </div>

      <div className="border-t border-[#252637] px-6 py-4 flex justify-end">
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() => navigate(`/projects/${id}/report/trust`)}
        >
          Trust Scoring
        </Button>
      </div>
    </div>
  );
}
