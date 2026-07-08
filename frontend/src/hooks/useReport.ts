import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchLatestReport, runValidation } from '@/lib/aurumApi';
import { useAppMode } from '@/context/AppModeContext';
import type { DataSourceMode } from '@/types/appMode';
import type { AurumReport } from '@/types/report';
import sampleReportJson from '@/fixtures/sample_report.json';

const sampleReport = sampleReportJson as AurumReport;

export type ReportSource = Exclude<DataSourceMode, 'loading' | 'planned'>;

export interface ReportPayload {
  report: AurumReport;
  source: ReportSource;
}

async function loadReport(displayMode: DataSourceMode): Promise<ReportPayload> {
  const source: ReportSource =
    displayMode === 'live' ? 'live' : 'verified_snapshot';

  try {
    const report = await fetchLatestReport();
    return { report, source };
  } catch {
    return { report: sampleReport, source: 'verified_snapshot' };
  }
}

export function useReport() {
  const { displayMode, isResolved } = useAppMode();

  return useQuery({
    queryKey: ['aurum', 'report', 'latest', displayMode],
    queryFn: () => loadReport(displayMode),
    enabled: isResolved,
    staleTime: 15_000,
  });
}

export function useRunValidation() {
  const queryClient = useQueryClient();
  const { canRunValidation } = useAppMode();

  return async (runId = 'demo_run_001') => {
    if (!canRunValidation) {
      throw new Error('Live validation is unavailable in snapshot mode.');
    }
    const report = await runValidation(runId);
    const payload: ReportPayload = { report, source: 'live' };
    queryClient.setQueryData(['aurum', 'report', 'latest', 'live'], payload);
    return payload;
  };
}
