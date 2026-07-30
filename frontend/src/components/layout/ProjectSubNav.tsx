import { useNavigate, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { cn } from '@/utils/cn';
import { Badge } from '@/components/ui/Badge';
import { FlowBackButton } from '@/components/common/FlowBackButton';
import { isPersistedUserRunId, withRunIdQuery } from '@/hooks/useReport';
import { getFlowBackTarget } from '@/utils/flowNavigation';
import { withConnectorFlowQuery } from '@/utils/connectorFlow';

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
    withConnectorFlowQuery(keepRun ? withRunIdQuery(path, activeRunId) : path, searchParams);

  const steps = [
    { num: '1', label: 'Connect', path: stepPath(`/projects/${id}/connect`), key: '/connect' },
    { num: '2', label: 'Discover', path: stepPath(`/projects/${id}/select`), key: '/select' },
    { num: '3', label: 'Bronze', path: stepPath(`/projects/${id}/bronze`), key: '/bronze' },
    { num: '4', label: 'Silver', path: stepPath(`/projects/${id}/silver`), key: '/silver' },
    { num: '5', label: 'Gold', path: stepPath(`/projects/${id}/gold`), key: '/gold' },
  ];

  let activeKey = '';
  if (pathname.includes('/connect')) activeKey = '/connect';
  else if (pathname.includes('/select') || pathname.includes('/metadata')) activeKey = '/select';
  else if (pathname.includes('/bronze')) activeKey = '/bronze';
  else if (pathname.includes('/silver')) activeKey = '/silver';
  else if (pathname.includes('/gold')) activeKey = '/gold';

  const isExecuting = isRunning ?? false;
  const back = getFlowBackTarget(pathname, id, activeRunId);
  const backPath = back ? withConnectorFlowQuery(back.path, searchParams) : null;

  return (
    <div className="border-b border-[#1e293b] bg-[#0b0f19] px-6 flex items-center justify-between gap-4 h-12 select-none">
      <div className="flex items-center min-w-0">
        {back && (
          <div className="mr-3 border-r border-[#1e293b] pr-3 shrink-0">
            <FlowBackButton path={backPath ?? back.path} label={back.label} variant="nav" />
          </div>
        )}
        <nav className="flex items-center gap-1.5 overflow-x-auto scrollbar-thin" aria-label="Project steps">
          {steps.map((step) => {
            const isActive = step.key === activeKey;
            return (
              <button
                key={step.label}
                type="button"
                onClick={() => navigate(step.path)}
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md transition-all duration-150 focus:outline-none whitespace-nowrap cursor-pointer',
                  isActive
                    ? 'bg-[#2563eb]/20 text-[#3b82f6] border border-[#3b82f6]/40 shadow-[0_0_12px_rgba(37,99,235,0.25)]'
                    : 'text-[#94a3b8] hover:text-[#f8fafc] hover:bg-[#131a29]',
                )}
              >
                <span
                  className={cn(
                    'flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold',
                    isActive ? 'bg-[#3b82f6] text-white' : 'bg-[#1e293b] text-[#64748b]',
                  )}
                >
                  {step.num}
                </span>
                {step.label}
              </button>
            );
          })}
        </nav>
      </div>
      {isExecuting && (
        <div className="shrink-0">
          <Badge variant="primary" className="gap-1.5 bg-[#2563eb]/10 border-[#3b82f6]/30">
            <span className="h-1.5 w-1.5 rounded-full bg-[#3b82f6] animate-pulse" />
            Processing…
          </Badge>
        </div>
      )}
    </div>
  );
}
