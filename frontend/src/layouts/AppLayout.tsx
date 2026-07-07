import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { Outlet } from 'react-router-dom';

export function AppLayout() {
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main
          className="flex-1 overflow-y-auto scrollbar-thin"
          id="main-content"
          tabIndex={-1}
          aria-label="Main content"
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
