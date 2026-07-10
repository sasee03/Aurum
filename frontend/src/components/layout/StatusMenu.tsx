import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Activity, Database, History, Link2, ListChecks, Server } from 'lucide-react';
import { useAppMode } from '@/context/AppModeContext';
import { MODE_LABELS, type DataSourceMode } from '@/types/appMode';
import { OLIST_DEMO_PROJECT_ID } from '@/components/cards/ProjectCard';
import { cn } from '@/utils/cn';

function modeLabel(displayMode: DataSourceMode): string {
  if (displayMode === 'loading') return 'Checking…';
  return MODE_LABELS[displayMode];
}

export function StatusMenu() {
  const navigate = useNavigate();
  const { id: projectId } = useParams<{ id: string }>();
  const {
    backendReachable,
    databaseOk,
    displayMode,
    databaseTarget,
    reason,
    isResolved,
  } = useAppMode();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

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

  const connectorsProject = projectId ?? OLIST_DEMO_PROJECT_ID;

  function go(path: string) {
    setOpen(false);
    navigate(path);
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className={cn(
          'flex h-8 w-8 items-center justify-center rounded-lg border border-[#252637] bg-[#1a1b28] text-[#94a3b8] hover:text-[#f1f5f9] transition-colors focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
          open && 'text-[#f1f5f9] bg-[#252637]',
        )}
        aria-label="App status"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <Activity size={16} />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="App status"
          className="absolute right-0 top-full z-50 mt-2 w-80 rounded-xl border border-[#252637] bg-[#0d0e14] shadow-xl shadow-black/40"
        >
          <div className="border-b border-[#252637] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">Status</p>
            <p className="mt-1 text-sm text-[#f1f5f9]">
              {!isResolved
                ? 'Checking connection…'
                : backendReachable && databaseOk
                  ? 'Backend and database healthy'
                  : backendReachable
                    ? 'Backend up — database unreachable'
                    : 'Backend unreachable'}
            </p>
          </div>

          <div className="space-y-3 px-4 py-3 text-sm">
            <div className="flex items-start gap-2.5">
              <Server size={14} className="mt-0.5 shrink-0 text-[#6b7280]" />
              <div>
                <p className="text-[11px] uppercase tracking-wide text-[#6b7280]">Backend</p>
                <p className={backendReachable ? 'text-[#22c55e]' : 'text-[#f59e0b]'}>
                  {backendReachable ? 'Reachable' : 'Unreachable'}
                </p>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <Database size={14} className="mt-0.5 shrink-0 text-[#6b7280]" />
              <div>
                <p className="text-[11px] uppercase tracking-wide text-[#6b7280]">Database</p>
                <p className={databaseOk ? 'text-[#22c55e]' : 'text-[#f59e0b]'}>
                  {databaseOk ? 'Connected' : 'Unavailable'}
                </p>
                {databaseTarget ? (
                  <p className="mt-0.5 font-mono text-[11px] text-[#94a3b8]">
                    {databaseTarget.host}:{databaseTarget.port}/{databaseTarget.database}
                  </p>
                ) : (
                  <p className="mt-0.5 text-[11px] text-[#6b7280]">No target reported</p>
                )}
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <Activity size={14} className="mt-0.5 shrink-0 text-[#6b7280]" />
              <div>
                <p className="text-[11px] uppercase tracking-wide text-[#6b7280]">Mode</p>
                <p className="text-[#f1f5f9]">{modeLabel(displayMode)}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-[#6b7280]">{reason}</p>
              </div>
            </div>
          </div>

          <div className="border-t border-[#252637] px-2 py-2">
            <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-[#6b7280]">
              Quick links
            </p>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-[#94a3b8] hover:bg-[#1a1b28] hover:text-[#f1f5f9]"
              onClick={() => go('/history')}
            >
              <History size={14} />
              Run History
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-[#94a3b8] hover:bg-[#1a1b28] hover:text-[#f1f5f9]"
              onClick={() => go(`/projects/${connectorsProject}/connect`)}
            >
              <Link2 size={14} />
              Connectors
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-[#94a3b8] hover:bg-[#1a1b28] hover:text-[#f1f5f9]"
              onClick={() => go('/custom-checks')}
            >
              <ListChecks size={14} />
              Custom Checks
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
