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
      {
        path: 'projects/:id/report/transform',
        element: (
          <PlannedFeaturePage
            title="Transformation Verification"
            detail="Inspect and verify the transformation logic applied at each medallion layer. Evidence for the current run is available in the quality report."
          />
        ),
      },
      {
        path: 'projects/:id/report/contracts',
        element: (
          <PlannedFeaturePage
            title="Business Contract Engine"
            detail="Define and enforce business rules across your data pipeline. Rule outcomes for the current run are included in the quality report."
          />
        ),
      },
      {
        path: 'projects/:id/lineage',
        element: (
          <PlannedFeaturePage
            title="Lineage Explorer"
            detail="Trace any number in the report back to its origin across pipeline layers. The current report includes first_failed_layer and evidence SQL."
          />
        ),
      },
      {
        path: 'projects/:id/remediate',
        element: (
          <PlannedFeaturePage
            title="Remediation Center"
            detail="Review quarantined records and apply fixes. Suggested remediation actions for the current run are available in the quality report."
            assistantPage="failure"
          />
        ),
      },
      {
        path: 'settings/audit',
        element: (
          <PlannedFeaturePage
            title="Audit & Governance"
            detail="Review who ran what and when. Validation history is available through Run History and the Aurum Assistant."
          />
        ),
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
