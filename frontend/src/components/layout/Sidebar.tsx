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
import { cn } from '@/utils/cn';

interface NavItem {
  label: string;
  icon: React.ElementType;
  to: string;
}

const navItems: NavItem[] = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Projects', icon: FolderOpen, to: '/projects/new' },
  { label: 'History', icon: History, to: '/history' },
  { label: 'Custom Checks', icon: BarChart2, to: '/custom-checks' },
  { label: 'Audit', icon: Settings, to: '/settings/audit' },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-[#252637] bg-[#0d0e14] transition-all duration-300 ease-in-out',
        collapsed ? 'w-14' : 'w-52'
      )}
      aria-label="Main navigation"
    >
      {/* Logo */}
      <div
        className={cn(
          'flex h-14 items-center border-b border-[#252637] px-3 gap-2.5 overflow-hidden',
          collapsed && 'justify-center px-0'
        )}
      >
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[#6366f1]">
          <Zap size={16} className="text-white" />
        </div>
        {!collapsed && (
          <span className="text-sm font-bold tracking-wider text-[#f1f5f9] whitespace-nowrap">
            AURUM
          </span>
        )}
      </div>

      {/* Nav Items */}
      <nav className="flex flex-col gap-1 p-2 flex-1" aria-label="Site navigation">
        {navItems.map(({ label, icon: Icon, to }) => (
          <NavLink
            key={label}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6366f1]',
                isActive
                  ? 'bg-[#6366f1]/10 text-[#6366f1] shadow-[inset_2px_0_0_#6366f1]'
                  : 'text-[#6b7280] hover:bg-[#1a1b28] hover:text-[#94a3b8]',
                collapsed && 'justify-center px-0 w-10 mx-auto'
              )
            }
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : undefined}
          >
            <Icon size={18} className="flex-shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Activity indicator at bottom */}
      {!collapsed && (
        <div className="p-2 border-t border-[#252637]">
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg">
            <Activity size={14} className="text-[#22c55e] animate-pulse" />
            <span className="text-xs text-[#6b7280]">System Nominal</span>
          </div>
        </div>
      )}

      {/* Collapse Toggle */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="absolute -right-3 top-16 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-[#252637] bg-[#13141e] text-[#6b7280] hover:text-[#f1f5f9] hover:bg-[#1a1b28] transition-all focus:outline-none focus:ring-2 focus:ring-[#6366f1]"
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
