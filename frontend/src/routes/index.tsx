import { createBrowserRouter, RouterProvider } from 'react-router-dom';
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
// Removed pages: ImpactAnalysis, TrustScoring, QualityReport, Remediation, Audit, ValidationDashboard

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
      { path: 'projects/:id/dashboard', element: <ProjectDashboardPage /> },
      { path: 'projects/:id/connect', element: <ConnectorsPage /> },
      { path: 'projects/:id/select', element: <DatasetExplorerPage /> },
      { path: 'projects/:id/metadata', element: <MetadataDiscoveryPage /> },
      { path: 'projects/:id/validate/config', element: <PipelineConfigPage /> },
      { path: 'projects/:id/validate/bronze', element: <BronzeValidationPage /> },
      { path: 'projects/:id/validate/silver', element: <SilverValidationPage /> },
      { path: 'projects/:id/validate/gold', element: <GoldValidationPage /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
