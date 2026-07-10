import { PageAssistant } from '@/components/common/PageAssistant';
import { FlowBackButton } from '@/components/common/FlowBackButton';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { useParams, useSearchParams, useLocation } from 'react-router-dom';
import { getFlowBackTarget } from '@/utils/flowNavigation';

interface Props {
  title: string;
  detail: string;
  assistantPage?: 'validation' | 'history' | 'failure';
}

export function PlannedFeaturePage({
  title,
  detail,
  assistantPage = 'validation',
}: Props) {
  const { id } = useParams<{ id: string }>();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const back = getFlowBackTarget(pathname, id, runId);

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page={assistantPage} runId={runId} />

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <h2 className="text-xl font-bold text-[#f1f5f9]">{title}</h2>
        <p className="text-sm text-[#6b7280]">{detail}</p>
      </div>

      {back && (
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4">
          <FlowBackButton path={back.path} label={back.label} />
        </div>
      )}
    </div>
  );
}
