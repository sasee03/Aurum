import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { LandingPage } from '@/pages/Landing/LandingPage';
import { NewProjectPage } from '@/pages/NewProject/NewProjectPage';
import { ConnectorsPage } from '@/pages/Connectors/ConnectorsPage';
import { DatasetExplorerPage } from '@/pages/DatasetExplorer/DatasetExplorerPage';
import { MetadataDiscoveryPage } from '@/pages/MetadataDiscovery/MetadataDiscoveryPage';
import { PipelineConfigPage } from '@/pages/PipelineConfig/PipelineConfigPage';
import { ProjectDashboardPage } from '@/pages/ProjectDashboard/ProjectDashboardPage';
import { ValidationDashboardPage } from '@/pages/ValidationDashboard/ValidationDashboardPage';
import { BronzeValidationPage } from '@/pages/BronzeValidation/BronzeValidationPage';
import { SilverValidationPage } from '@/pages/SilverValidation/SilverValidationPage';
import { GoldValidationPage } from '@/pages/GoldValidation/GoldValidationPage';
import { ImpactAnalysisPage } from '@/pages/ImpactAnalysis/ImpactAnalysisPage';
import { TrustScoringPage } from '@/pages/TrustScoring/TrustScoringPage';
import { QualityReportPage } from '@/pages/QualityReport/QualityReportPage';
import { RunHistoryPage } from '@/pages/RunHistory/RunHistoryPage';
import { CustomChecksPage } from '@/pages/CustomChecks/CustomChecksPage';
import { DocumentationPage } from '@/pages/Documentation/DocumentationPage';
import { RemediationPage } from '@/pages/Remediation/RemediationPage';
import { AuditPage } from '@/pages/Audit/AuditPage';

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
      { path: 'projects/:id/validate/execution', element: <ValidationDashboardPage /> },
      { path: 'projects/:id/validate/bronze', element: <BronzeValidationPage /> },
      { path: 'projects/:id/validate/silver', element: <SilverValidationPage /> },
      { path: 'projects/:id/validate/gold', element: <GoldValidationPage /> },
      { path: 'projects/:id/report/impact', element: <ImpactAnalysisPage /> },
      { path: 'projects/:id/report/trust', element: <TrustScoringPage /> },
      { path: 'projects/:id/report/quality', element: <QualityReportPage /> },
      { path: 'projects/:id/remediate', element: <RemediationPage /> },
      { path: 'settings/audit', element: <AuditPage /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
