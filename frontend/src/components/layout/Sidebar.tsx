import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderOpen,
  History,
  BarChart2,
  Settings,
  Activity,
  ChevronRight,
  Zap,
} from 'lucide-react';
import { useAppMode } from '@/context/AppModeContext';
import { cn } from '@/utils/cn';

interface NavItem {
  label: string;
  icon: React.ElementType;
  to: string;
}

const navItems: (NavItem & { planned?: boolean })[] = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Projects', icon: FolderOpen, to: '/projects/new' },
  { label: 'History', icon: History, to: '/history' },
  { label: 'Custom Checks', icon: BarChart2, to: '/custom-checks' },
  { label: 'Audit', icon: Settings, to: '/settings/audit' },
];

function systemStatusLabel(mode: ReturnType<typeof useAppMode>['mode'], databaseOk: boolean) {
  if (mode === 'loading') return 'Checking…';
  if (mode === 'live' && databaseOk) return 'System Nominal';
  if (mode === 'verified_snapshot') return 'Snapshot Mode';
  return 'Preview';
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const { mode, databaseOk } = useAppMode();
  const statusLabel = systemStatusLabel(mode, databaseOk);
  const statusHealthy = mode === 'live' && databaseOk;

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-[#1e293b] bg-[#0b0f19] transition-all duration-300 ease-in-out select-none',
        collapsed ? 'w-14' : 'w-52'
      )}
      aria-label="Main navigation"
    >
      <div
        className={cn(
          'flex h-14 items-center border-b border-[#1e293b] px-3.5 gap-2.5 overflow-hidden',
          collapsed && 'justify-center px-0'
        )}
      >
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[#2563eb] to-[#06b6d4] shadow-[0_0_12px_rgba(37,99,235,0.4)]">
          <Zap size={16} className="text-white" />
        </div>
        {!collapsed && (
          <span className="text-sm font-bold tracking-wider text-[#f8fafc] whitespace-nowrap">
            AURUM
          </span>
        )}
      </div>

      <nav className="flex flex-col gap-1 p-2 flex-1" aria-label="Site navigation">
        {navItems.map(({ label, icon: Icon, to, planned }) => (
          <NavLink
            key={label}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3b82f6]',
                isActive
                  ? 'bg-[#2563eb]/15 text-[#3b82f6] font-semibold border-l-2 border-[#3b82f6]'
                  : 'text-[#94a3b8] hover:bg-[#131a29] hover:text-[#f8fafc]',
                collapsed && 'justify-center px-0 w-10 mx-auto border-l-0',
                planned && !isActive && 'opacity-70',
              )
            }
            aria-label={collapsed ? (planned ? `${label} (coming soon)` : label) : undefined}
            title={collapsed ? (planned ? `${label} — coming soon` : label) : planned ? 'Coming soon' : undefined}
          >
            <Icon size={18} className="flex-shrink-0" />
            {!collapsed && (
              <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                <span className="truncate">{label}</span>
                {planned && (
                  <span className="shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[#64748b] bg-[#131a29] border border-[#273549]">
                    Soon
                  </span>
                )}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {!collapsed && (
        <div className="p-2 border-t border-[#1e293b]">
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-[#111827]/60 border border-[#1e293b]">
            <Activity
              size={14}
              className={cn(
                statusHealthy ? 'text-[#10b981] animate-pulse' : 'text-[#f59e0b]',
              )}
            />
            <span className="text-xs text-[#94a3b8] font-medium">{statusLabel}</span>
          </div>
        </div>
      )}

      <button
        onClick={() => setCollapsed((c) => !c)}
        className="absolute -right-3 top-16 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-[#273549] bg-[#111827] text-[#94a3b8] hover:text-[#f8fafc] hover:bg-[#1f293d] transition-all focus:outline-none focus:ring-2 focus:ring-[#3b82f6] cursor-pointer shadow-md"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <ChevronRight
          size={12}
          className={cn('transition-transform duration-300', !collapsed && 'rotate-180')}
        />
      </button>
    </aside>
  );
}
