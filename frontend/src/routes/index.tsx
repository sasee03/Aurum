import { createBrowserRouter, RouterProvider, Navigate, useParams, useLocation } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { LandingPage } from '@/pages/Landing/LandingPage';
import { NewProjectPage } from '@/pages/NewProject/NewProjectPage';
import { ConnectorsPage } from '@/pages/Connectors/ConnectorsPage';
import { DatasetExplorerPage } from '@/pages/DatasetExplorer/DatasetExplorerPage';
import { MetadataDiscoveryPage } from '@/pages/MetadataDiscovery/MetadataDiscoveryPage';
import { PipelineConfigPage } from '@/pages/PipelineConfig/PipelineConfigPage';
import { ProjectDashboardPage } from '@/pages/ProjectDashboard/ProjectDashboardPage';
import { BronzeValidationPage } from '@/pages/BronzeValidation/BronzeValidationPage';
import { SilverValidationPage } from '@/pages/SilverValidation/SilverValidationPage';
import { GoldValidationPage } from '@/pages/GoldValidation/GoldValidationPage';
import { RunHistoryPage } from '@/pages/RunHistory/RunHistoryPage';
import { CustomChecksPage } from '@/pages/CustomChecks/CustomChecksPage';
import { DocumentationPage } from '@/pages/Documentation/DocumentationPage';
import { AuditPage } from '@/pages/Audit/AuditPage';

function LegacyProjectRedirect({ target }: { target: string }) {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  return <Navigate to={`/projects/${encodeURIComponent(id || 'demo')}/${target}${location.search}`} replace />;
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'projects/new', element: <NewProjectPage /> },
      { path: 'history', element: <RunHistoryPage /> },
      { path: 'custom-checks', element: <CustomChecksPage /> },
      { path: 'documentation', element: <DocumentationPage /> },
      { path: 'settings/audit', element: <AuditPage /> },
      { path: 'projects/:id/dashboard', element: <ProjectDashboardPage /> },
      { path: 'projects/:id/connect', element: <ConnectorsPage /> },
      { path: 'projects/:id/bronze', element: <BronzeValidationPage /> },
      { path: 'projects/:id/silver', element: <SilverValidationPage /> },
      { path: 'projects/:id/gold', element: <GoldValidationPage /> },
      { path: 'projects/:id/select', element: <DatasetExplorerPage /> },
      { path: 'projects/:id/metadata', element: <MetadataDiscoveryPage /> },
      { path: 'projects/:id/validate/config', element: <PipelineConfigPage /> },
      // Compatibility redirects from legacy URLs
      { path: 'projects/:id/validate/bronze', element: <LegacyProjectRedirect target="bronze" /> },
      { path: 'projects/:id/validate/silver', element: <LegacyProjectRedirect target="silver" /> },
      { path: 'projects/:id/validate/gold', element: <LegacyProjectRedirect target="gold" /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
