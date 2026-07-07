import { useLocation } from 'react-router-dom';
import { Bell, User } from 'lucide-react';

const routeLabels: Record<string, string> = {
  '/': 'Dashboard',
  '/projects/new': 'New Project',
  '/projects': 'Projects',
  '/history': 'History',
  '/reports': 'Reports',
  '/settings': 'Settings',
};

function getPageTitle(pathname: string): string {
  if (routeLabels[pathname]) return routeLabels[pathname];
  if (pathname.match(/^\/projects\/[^/]+\/connect$/)) return 'Data Connectors';
  if (pathname.match(/^\/projects\/[^/]+\/select$/)) return 'Dataset Explorer';
  return 'AURUM';
}

export function Header() {
  const { pathname } = useLocation();
  const title = getPageTitle(pathname);

  return (
    <header
      className="flex h-14 items-center justify-between border-b border-[#252637] bg-[#0d0e14] px-5"
      role="banner"
    >
      <h1 className="text-sm font-semibold text-[#f1f5f9]">{title}</h1>
      <div className="flex items-center gap-2">
        <button
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[#6b7280] hover:bg-[#1a1b28] hover:text-[#f1f5f9] transition-colors focus:outline-none focus:ring-2 focus:ring-[#6366f1]"
          aria-label="Notifications"
        >
          <Bell size={16} />
        </button>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#252637] bg-[#1a1b28] text-[#94a3b8] hover:text-[#f1f5f9] transition-colors focus:outline-none focus:ring-2 focus:ring-[#6366f1]"
          aria-label="User profile"
        >
          <User size={16} />
        </button>
      </div>
    </header>
  );
}
