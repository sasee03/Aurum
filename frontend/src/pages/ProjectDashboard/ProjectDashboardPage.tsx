import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { MetricCard } from '@/components/cards/MetricCard';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useReport } from '@/hooks/useReport';
import { formatBrl } from '@/utils/reportFormat';

export function ProjectDashboardPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useReport();

  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingSkeleton count={4} className="h-16" />
      </div>
    );
  }

  const report = data?.report;
  const source = data?.source ?? 'fixture';

  if (!report) {
    return (
      <div className="p-6">
        <p className="text-sm text-[#94a3b8]">
          Validation report is not available right now. Run validation from the execution dashboard
          when the service is back.
        </p>
      </div>
    );
  }

  const ls = report.layer_status;
  const impact = report.business_impact;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav />
      <PageAssistant page="dashboard" runId={report.run_id} />

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Validation Dashboard</h2>
          <DataSourceBadge source={source} />
          <Badge
            variant={
              report.final_verdict === 'TRUSTED'
                ? 'pass'
                : report.final_verdict === 'WARNING'
                  ? 'warning'
                  : 'failed'
            }
          >
            {report.final_verdict}
          </Badge>
        </div>
        <p className="text-sm text-[#6b7280]">
          Olist demo-ready report — {report.dataset}. Engine decides deterministically; Assistant explains only.
        </p>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Dataset" value={report.dataset} />
          <MetricCard label="Run ID" value={report.run_id} />
          <MetricCard label="Trust Score" value={`${report.trust_score}/100`} subValue="Deterministic" />
          <MetricCard
            label="Est. Loss"
            value={impact.estimated_loss != null ? formatBrl(impact.estimated_loss) : '—'}
          />
        </div>

        <div className="flex gap-2">
          <Badge variant={ls.bronze === 'PASS' ? 'pass' : 'failed'}>Bronze {ls.bronze}</Badge>
          <Badge variant={ls.silver === 'FAIL' ? 'failed' : ls.silver === 'PASS' ? 'pass' : 'warning'}>
            Silver {ls.silver}
          </Badge>
          <Badge variant={ls.gold === 'IMPACTED' ? 'failed' : ls.gold === 'PASS' ? 'pass' : 'warning'}>
            Gold {ls.gold}
          </Badge>
        </div>

        <p className="text-sm text-[#94a3b8]">{report.root_cause?.summary}</p>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex justify-between">
        <Button variant="ghost" onClick={() => navigate('/')}>
          Home
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() => navigate(`/projects/${id}/validate/execution`)}
        >
          Run / View Execution
        </Button>
      </div>
    </div>
  );
}
