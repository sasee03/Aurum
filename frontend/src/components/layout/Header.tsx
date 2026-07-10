import { useLocation } from 'react-router-dom';
import { RecentRunsMenu } from '@/components/layout/RecentRunsMenu';
import { StatusMenu } from '@/components/layout/StatusMenu';

const routeLabels: Record<string, string> = {
  '/': 'Dashboard',
  '/projects/new': 'New Project',
  '/projects': 'Projects',
  '/history': 'History',
  '/documentation': 'Documentation',
  '/reports': 'Reports',
  '/settings': 'Settings',
  '/custom-checks': 'Custom Checks',
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
        <RecentRunsMenu />
        <StatusMenu />
      </div>
    </header>
  );
}
