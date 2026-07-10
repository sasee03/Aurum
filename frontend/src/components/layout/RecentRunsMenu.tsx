import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Bell } from 'lucide-react';
import { useAppMode } from '@/context/AppModeContext';
import { fetchRuns, type ValidationRunSummary } from '@/lib/aurumApi';
import { cn } from '@/utils/cn';

const LAST_SEEN_KEY = 'aurum.notifications.lastSeen';
const MAX_RUNS = 8;

function runEventLabel(mode: string): string {
  switch (mode) {
    case 'upload':
      return 'Uploaded file validated';
    case 'connector':
      return 'Database table validated';
    case 'demo':
      return 'Sample dataset validated';
    case 'live':
      return 'Validation completed';
    default:
      return 'Validation completed';
  }
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return 'Unknown time';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const delta = Date.now() - ms;
  const sec = Math.round(delta / 1000);
  if (sec < 45) return 'Just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
  const day = Math.round(hr / 24);
  if (day < 14) return `${day} day${day === 1 ? '' : 's'} ago`;
  return new Date(ms).toLocaleDateString();
}

function runTimestamp(run: ValidationRunSummary): string {
  return run.finished_at || run.started_at;
}

function readLastSeen(): number {
  try {
    const raw = localStorage.getItem(LAST_SEEN_KEY);
    if (!raw) return 0;
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  } catch {
    return 0;
  }
}

function writeLastSeen(ms: number) {
  try {
    localStorage.setItem(LAST_SEEN_KEY, String(ms));
  } catch {
    // Ignore quota / private-mode failures — badge is optional.
  }
}

function unreadCount(runs: ValidationRunSummary[], lastSeen: number): number {
  return runs.filter((run) => {
    const t = Date.parse(runTimestamp(run));
    return Number.isFinite(t) && t > lastSeen;
  }).length;
}

export function RecentRunsMenu() {
  const navigate = useNavigate();
  const { backendReachable } = useAppMode();
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState(readLastSeen);
  const rootRef = useRef<HTMLDivElement>(null);

  const runsQuery = useQuery({
    queryKey: ['aurum', 'runs'],
    queryFn: fetchRuns,
    enabled: backendReachable,
    staleTime: 15_000,
    retry: false,
  });

  const runs = useMemo(
    () => (runsQuery.data?.runs ?? []).slice(0, MAX_RUNS),
    [runsQuery.data?.runs],
  );
  const badgeCount = backendReachable ? unreadCount(runs, lastSeen) : 0;

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  // Clear unread once the user opens the panel and runs are visible.
  useEffect(() => {
    if (!open || runs.length === 0) return;
    const newest = runs.reduce((max, run) => {
      const t = Date.parse(runTimestamp(run));
      return Number.isFinite(t) && t > max ? t : max;
    }, 0);
    if (newest <= lastSeen) return;
    writeLastSeen(newest);
    setLastSeen(newest);
  }, [open, runs, lastSeen]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && backendReachable) {
      void runsQuery.refetch();
    }
  }

  function openRun(run: ValidationRunSummary) {
    setOpen(false);
    const project = run.project_id || 'shared';
    navigate(
      `/projects/${encodeURIComponent(project)}/report/quality?runId=${encodeURIComponent(run.run_id)}`,
    );
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className={cn(
          'relative flex h-8 w-8 items-center justify-center rounded-lg text-[#6b7280] hover:bg-[#1a1b28] hover:text-[#f1f5f9] transition-colors focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
          open && 'bg-[#1a1b28] text-[#f1f5f9]',
        )}
        aria-label={
          badgeCount > 0 ? `Recent runs, ${badgeCount} unread` : 'Recent runs'
        }
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={toggle}
      >
        <Bell size={16} />
        {badgeCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#6366f1] px-1 text-[10px] font-bold text-white">
            {badgeCount > 9 ? '9+' : badgeCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Recent validation runs"
          className="absolute right-0 top-full z-50 mt-2 w-96 max-w-[calc(100vw-2rem)] rounded-xl border border-[#252637] bg-[#0d0e14] shadow-xl shadow-black/40"
        >
          <div className="flex items-center justify-between border-b border-[#252637] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">
              Recent runs
            </p>
            <button
              type="button"
              className="text-xs text-[#6366f1] hover:text-[#818cf8]"
              onClick={() => {
                setOpen(false);
                navigate('/history');
              }}
            >
              View all
            </button>
          </div>

          <div className="max-h-80 overflow-y-auto scrollbar-thin">
            {!backendReachable ? (
              <p className="px-4 py-6 text-sm text-[#94a3b8]">
                Run history needs the API. Start the backend to see recent validations.
              </p>
            ) : runsQuery.isLoading || runsQuery.isFetching ? (
              <p className="px-4 py-6 text-sm text-[#6b7280]">Loading recent runs…</p>
            ) : runsQuery.isError ? (
              <p className="px-4 py-6 text-sm text-[#f59e0b]">
                Could not load runs. Try again from Run History.
              </p>
            ) : runs.length === 0 ? (
              <p className="px-4 py-6 text-sm text-[#94a3b8]">
                No runs yet. Validate an upload, connect a table, or run the sample dataset.
              </p>
            ) : (
              <ul>
                {runs.map((run) => (
                  <li key={run.run_id}>
                    <button
                      type="button"
                      className="flex w-full flex-col gap-0.5 border-b border-[#1a1b28] px-4 py-3 text-left last:border-0 hover:bg-[#13141e]"
                      onClick={() => openRun(run)}
                    >
                      <span className="text-sm font-medium text-[#f1f5f9]">
                        {runEventLabel(run.mode)}
                      </span>
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[#94a3b8]">
                        <span>
                          {run.final_verdict ?? run.status}
                          {run.trust_score != null ? ` · ${run.trust_score}/100` : ''}
                        </span>
                        <span className="text-[#6b7280]">·</span>
                        <span>{relativeTime(runTimestamp(run))}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
