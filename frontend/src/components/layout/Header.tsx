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
  if (pathname.match(/^\/projects\/[^/]+\/bronze$/)) return 'Bronze Ingestion';
  if (pathname.match(/^\/projects\/[^/]+\/silver$/)) return 'Silver Refinement';
  if (pathname.match(/^\/projects\/[^/]+\/gold$/)) return 'Gold Data Product';
  return 'AURUM';
}

export function Header() {
  const { pathname } = useLocation();
  const title = getPageTitle(pathname);

  return (
    <header
      className="flex h-14 items-center justify-between border-b border-[#1e293b] bg-[#0b0f19] px-6 select-none"
      role="banner"
    >
      <h1 className="text-base font-semibold text-[#f8fafc] tracking-tight">{title}</h1>
      <div className="flex items-center gap-3">
        <RecentRunsMenu />
        <StatusMenu />
      </div>
    </header>
  );
}
