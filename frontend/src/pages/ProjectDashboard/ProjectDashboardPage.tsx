import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { MetricCard } from '@/components/cards/MetricCard';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { layerStatusPresentation } from '@/components/common/LayerStatusRing';
import { getProject } from '@/lib/aurumApi';
import { formatBrl } from '@/utils/reportFormat';
import { useQuery } from '@tanstack/react-query';

function friendlyDatasetLabel(dataset: string): string {
  if (/olist/i.test(dataset)) return 'Sample e-commerce dataset';
  return dataset;
}

export function ProjectDashboardPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { displayMode, isResolved } = useAppMode();

  // Fetch the project to get its last_run_id, then load that specific report
  const projectQuery = useQuery({
    queryKey: ['aurum', 'project', id],
    queryFn: () => getProject(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  });

  const lastRunId = projectQuery.data?.last_run_id ?? undefined;

  // Navigate with the run_id in the URL so useReport() picks it up correctly
  // For the dashboard itself, we pass it directly to useReport via searchParams trick —
  // instead we use the runId override pattern by navigating to quality report
  const { data, isLoading } = useReport();

  if (!isResolved || isLoading || projectQuery.isLoading) {
    return (
      <div className="p-6">
        <LoadingSkeleton count={4} className="h-16" />
      </div>
    );
  }

  const report = data?.report;

  // If the project has a last_run_id and we're not already showing that report,
  // redirect straight to the quality report page which handles ?runId= correctly.
  if (lastRunId && report?.run_id !== lastRunId) {
    navigate(`/projects/${id}/report/quality?runId=${encodeURIComponent(lastRunId)}`, { replace: true });
    return null;
  }

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
          <DataSourceBadge mode={displayMode} />
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
          Validation report ready — {friendlyDatasetLabel(report.dataset)}. Results are
          deterministic; the Assistant explains findings only.
        </p>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <MetricCard label="Dataset" value={friendlyDatasetLabel(report.dataset)} />
          <MetricCard label="Trust Score" value={`${report.trust_score}/100`} subValue="Deterministic" />
          <MetricCard
            label="Est. Loss"
            value={impact.estimated_loss != null ? formatBrl(impact.estimated_loss) : '—'}
          />
        </div>

        <div className="flex gap-2">
          <Badge variant={layerStatusPresentation(ls.bronze).badge}>Bronze {ls.bronze}</Badge>
          <Badge variant={layerStatusPresentation(ls.silver).badge}>Silver {ls.silver}</Badge>
          <Badge variant={layerStatusPresentation(ls.gold).badge}>Gold {ls.gold}</Badge>
        </div>

        <p className="text-sm text-[#94a3b8]">{report.root_cause?.summary}</p>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex justify-between">
        <Button variant="ghost" onClick={() => navigate('/')}>
          Home
        </Button>
        {lastRunId ? (
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            onClick={() => navigate(`/projects/${id}/report/quality?runId=${encodeURIComponent(lastRunId)}`)}
          >
            View Last Report
          </Button>
        ) : (
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            onClick={() => navigate(`/projects/${id}/validate/execution`)}
          >
            Run / View Execution
          </Button>
        )}
      </div>
    </div>
  );
}
