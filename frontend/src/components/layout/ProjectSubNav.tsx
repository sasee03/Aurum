import { useNavigate, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { cn } from '@/utils/cn';
import { Badge } from '@/components/ui/Badge';
import { FlowBackButton } from '@/components/common/FlowBackButton';
import { isPersistedUserRunId, withRunIdQuery } from '@/hooks/useReport';
import { getFlowBackTarget } from '@/utils/flowNavigation';

interface ProjectSubNavProps {
  runId?: string;
  isRunning?: boolean;
}

export function ProjectSubNav({ runId, isRunning }: ProjectSubNavProps = {}) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();

  // Prefer explicit prop, then URL — keeps upload/connector context across tab clicks.
  const activeRunId = runId ?? searchParams.get('runId') ?? undefined;
  const keepRun = isPersistedUserRunId(activeRunId);

  const stepPath = (path: string) =>
    keepRun ? withRunIdQuery(path, activeRunId) : path;

  const steps = [
    { label: 'Connect', path: stepPath(`/projects/${id}/connect`) },
    { label: 'Bronze', path: stepPath(`/projects/${id}/bronze`) },
    { label: 'Silver', path: stepPath(`/projects/${id}/silver`) },
    { label: 'Gold', path: stepPath(`/projects/${id}/gold`) },
  ];

  let activeLabel = '';
  if (pathname.includes('/connect')) activeLabel = 'Connect';
  else if (pathname.includes('/bronze')) activeLabel = 'Bronze';
  else if (pathname.includes('/silver')) activeLabel = 'Silver';
  else if (pathname.includes('/gold')) activeLabel = 'Gold';

  const isExecuting = isRunning ?? false;
  const back = getFlowBackTarget(pathname, id, activeRunId);

  return (
    <div className="border-b border-[#252637] bg-[#0d0e14] px-5 flex items-end justify-between gap-3">
      <div className="flex items-end min-w-0">
        {back && (
          <div className="mr-2 border-r border-[#252637] pr-2 shrink-0">
            <FlowBackButton path={back.path} label={back.label} variant="nav" />
          </div>
        )}
        <nav className="flex gap-0 overflow-x-auto scrollbar-thin" aria-label="Project steps">
          {steps.map((step) => {
            const isActive = step.label === activeLabel;
            return (
              <button
                key={step.label}
                type="button"
                onClick={() => navigate(step.path)}
                className={cn(
                  'px-4 py-3 text-xs font-semibold border-b-2 transition-colors focus:outline-none whitespace-nowrap',
                  isActive
                    ? 'border-[#6366f1] text-[#6366f1]'
                    : 'border-transparent text-[#4b5563] hover:text-[#6b7280]',
                )}
              >
                {step.label}
              </button>
            );
          })}
        </nav>
      </div>
      {isExecuting && (
        <div className="py-2.5 shrink-0">
          <Badge variant="primary" className="gap-1 bg-transparent border-[#6366f1]/20">
            <span className="h-1.5 w-1.5 rounded-full bg-[#6366f1] animate-pulse" />
            Running…
          </Badge>
        </div>
      )}
    </div>
  );
}
