import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { LandingPage } from '@/pages/Landing/LandingPage';
import { NewProjectPage } from '@/pages/NewProject/NewProjectPage';
import { ConnectorsPage } from '@/pages/Connectors/ConnectorsPage';
import { DatasetExplorerPage } from '@/pages/DatasetExplorer/DatasetExplorerPage';
import { MetadataDiscoveryPage } from '@/pages/MetadataDiscovery/MetadataDiscoveryPage';
import { PipelineConfigPage } from '@/pages/PipelineConfig/PipelineConfigPage';
import { ValidationDashboardPage } from '@/pages/ValidationDashboard/ValidationDashboardPage';
import { BronzeValidationPage } from '@/pages/BronzeValidation/BronzeValidationPage';
import { SilverValidationPage } from '@/pages/SilverValidation/SilverValidationPage';

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'projects/new', element: <NewProjectPage /> },
      { path: 'projects/:id/connect', element: <ConnectorsPage /> },
      { path: 'projects/:id/select', element: <DatasetExplorerPage /> },
      { path: 'projects/:id/metadata', element: <MetadataDiscoveryPage /> },
      { path: 'projects/:id/validate/config', element: <PipelineConfigPage /> },
      { path: 'projects/:id/validate/execution', element: <ValidationDashboardPage /> },
      { path: 'projects/:id/validate/bronze', element: <BronzeValidationPage /> },
      { path: 'projects/:id/validate/silver', element: <SilverValidationPage /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
