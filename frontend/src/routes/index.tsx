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
import { PlannedFeaturePage } from '@/pages/Planned/PlannedFeaturePage';

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'projects/new', element: <NewProjectPage /> },
      { path: 'history', element: <RunHistoryPage /> },
      { path: 'custom-checks', element: <CustomChecksPage /> },
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
      {
        path: 'projects/:id/report/transform',
        element: (
          <PlannedFeaturePage
            title="Transformation Verification"
            detail="Transformation evidence is available in the quality report today. A dedicated comparison view is planned for a future release."
          />
        ),
      },
      {
        path: 'projects/:id/report/contracts',
        element: (
          <PlannedFeaturePage
            title="Business Contract Engine"
            detail="Business rules run inside the validation engine today and appear in the quality report. A standalone contract editor is planned."
          />
        ),
      },
      {
        path: 'projects/:id/lineage',
        element: (
          <PlannedFeaturePage
            title="Lineage Explorer"
            detail="Lineage visualization is planned. The current report includes first_failed_layer and evidence SQL for the Olist demo."
          />
        ),
      },
      {
        path: 'projects/:id/remediate',
        element: (
          <PlannedFeaturePage
            title="Remediation Center"
            detail="Remediation guidance comes from suggested_action in the quality report today. Workflow and ticketing integration are planned."
            assistantPage="failure"
          />
        ),
      },
      {
        path: 'settings/audit',
        element: (
          <PlannedFeaturePage
            title="Audit & Governance"
            detail="Audit and governance views are planned. Validation history is partially available through Aurum Assistant and the latest report."
          />
        ),
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
