import { withRunIdQuery } from '@/hooks/useReport';

export interface FlowBackTarget {
  path: string;
  label: string;
}

/**
 * Linear project-flow previous step: Connect -> Bronze -> Silver -> Gold.
 * Paths include ?runId= when provided so going back preserves context.
 */
export function getFlowBackTarget(
  pathname: string,
  projectId: string | undefined,
  runId?: string | null,
): FlowBackTarget | null {
  if (!projectId) return null;
  const base = `/projects/${projectId}`;
  const withRun = (path: string) => withRunIdQuery(path, runId);

  if (pathname.includes('/gold')) {
    return { path: withRun(`${base}/silver`), label: 'Back to Silver' };
  }
  if (pathname.includes('/silver')) {
    return { path: withRun(`${base}/bronze`), label: 'Back to Bronze' };
  }
  if (pathname.includes('/bronze')) {
    return { path: withRun(`${base}/connect`), label: 'Back to Connect' };
  }
  if (pathname.includes('/validate/config')) {
    return { path: withRun(`${base}/connect`), label: 'Back to Connect' };
  }
  if (pathname.includes('/select') || pathname.includes('/metadata')) {
    return { path: withRun(`${base}/connect`), label: 'Back to Connect' };
  }
  if (pathname.includes('/connect')) {
    return { path: `${base}/dashboard`, label: 'Back to Dashboard' };
  }
  if (pathname.includes('/dashboard')) {
    return { path: '/', label: 'Back to Home' };
  }

  return null;
}
