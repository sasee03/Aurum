import { withRunIdQuery } from '@/hooks/useReport';

export interface FlowBackTarget {
  path: string;
  label: string;
}

/**
 * Linear project-flow previous step. Paths include ?runId= when provided
 * so going back never silently drops an upload/connector run.
 */
export function getFlowBackTarget(
  pathname: string,
  projectId: string | undefined,
  runId?: string | null,
): FlowBackTarget | null {
  if (!projectId) return null;
  const base = `/projects/${projectId}`;
  const withRun = (path: string) => withRunIdQuery(path, runId);

  if (pathname.includes('/remediate')) {
    return { path: withRun(`${base}/report/quality`), label: 'Back to Report' };
  }
  if (pathname.includes('/report/quality')) {
    return { path: withRun(`${base}/report/trust`), label: 'Back to Trust Scoring' };
  }
  if (pathname.includes('/report/trust')) {
    return { path: withRun(`${base}/report/impact`), label: 'Back to Impact' };
  }
  if (pathname.includes('/report/impact') || pathname.includes('/impact')) {
    return { path: withRun(`${base}/validate/gold`), label: 'Back to Gold' };
  }
  if (pathname.includes('/validate/gold')) {
    return { path: withRun(`${base}/validate/silver`), label: 'Back to Silver' };
  }
  if (pathname.includes('/validate/silver')) {
    return { path: withRun(`${base}/validate/bronze`), label: 'Back to Bronze' };
  }
  if (pathname.includes('/validate/bronze')) {
    return { path: withRun(`${base}/validate/execution`), label: 'Back to Execution' };
  }
  if (pathname.includes('/validate/execution')) {
    return { path: withRun(`${base}/validate/config`), label: 'Back to Pipeline Config' };
  }
  if (pathname.includes('/validate/config')) {
    return { path: withRun(`${base}/select`), label: 'Back to Explore Datasets' };
  }
  if (pathname.includes('/metadata')) {
    return { path: withRun(`${base}/select`), label: 'Back to Explore Datasets' };
  }
  if (pathname.includes('/select')) {
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
