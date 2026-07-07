import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useReport } from '@/hooks/useReport';

export function TrustScoringPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useReport();
  const report = data?.report;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={report?.run_id} />
      <PageAssistant page="dashboard" runId={report?.run_id} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Trust Scoring</h2>
        {data && <DataSourceBadge source={data.source} />}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {isLoading ? (
          <LoadingSkeleton count={2} className="h-24" />
        ) : report ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <MetricCard
                label="Trust Score"
                value={`${report.trust_score}/100`}
                subValue="Deterministic — engine computed"
              />
              <MetricCard label="Final Verdict" value={report.final_verdict} />
              <MetricCard label="Severity" value={report.severity} />
            </div>
            <Badge variant="secondary">Narrative is explanation only — does not decide verdict</Badge>
            <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-2">Trust Narrative (Ollama)</h3>
              <p className="text-sm text-[#94a3b8] whitespace-pre-wrap">
                {report.trust_narrative || 'No narrative available.'}
              </p>
            </div>
          </>
        ) : null}
      </div>

      <div className="border-t border-[#252637] px-6 py-4 flex justify-end">
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() => navigate(`/projects/${id}/report/quality`)}
        >
          Quality Report
        </Button>
      </div>
    </div>
  );
}
