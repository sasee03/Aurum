import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { cn } from '@/utils/cn';
import { PlayCircle } from 'lucide-react';
import { Badge, StatusBadge } from '@/components/ui/Badge';

export function ProjectSubNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { id } = useParams<{ id: string }>();
  
  const steps = [
    { label: 'Connect', path: `/projects/${id}/connect` },
    { label: 'Select', path: `/projects/${id}/select` },
    { label: 'Validate', path: `/projects/${id}/validate/config` },
    { label: 'Report', path: `/projects/${id}/report` },
    { label: 'Remediate', path: `/projects/${id}/remediate` },
  ];

  // Determine active step based on URL path
  let activeLabel = '';
  if (pathname.includes('/connect')) activeLabel = 'Connect';
  else if (pathname.includes('/select') || pathname.includes('/metadata')) activeLabel = 'Select';
  else if (pathname.includes('/validate')) activeLabel = 'Validate';
  else if (pathname.includes('/report')) activeLabel = 'Report';
  else if (pathname.includes('/remediate')) activeLabel = 'Remediate';

  // For the validation dashboard, there is a specific header state "Run #4127 Running"
  // Let's just mock a run badge if we are in validate execution pages
  const isExecuting = pathname.includes('/validate/execution');

  return (
    <div className="border-b border-[#252637] bg-[#0d0e14] px-5 flex items-end justify-between">
      <nav className="flex gap-0" aria-label="Project steps">
        {steps.map((step) => {
          const isActive = step.label === activeLabel;
          return (
            <button
              key={step.label}
              onClick={() => navigate(step.path)}
              className={cn(
                'px-4 py-3 text-xs font-semibold border-b-2 transition-colors focus:outline-none',
                isActive
                  ? 'border-[#6366f1] text-[#6366f1]'
                  : 'border-transparent text-[#4b5563] hover:text-[#6b7280]'
              )}
            >
              {step.label}
            </button>
          );
        })}
      </nav>
      {isExecuting && (
        <div className="py-2.5">
           <Badge variant="primary" className="gap-1 bg-transparent border-[#6366f1]/20">
             <span className="h-1.5 w-1.5 rounded-full bg-[#6366f1] animate-pulse" />
             Run #4127 Running
           </Badge>
        </div>
      )}
    </div>
  );
}
