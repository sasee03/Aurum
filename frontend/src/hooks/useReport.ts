import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchLatestReport, runValidation, getMetadataHealth } from '@/lib/aurumApi';
import type { AurumReport } from '@/types/report';
import sampleReportJson from '@/fixtures/sample_report.json';

const sampleReport = sampleReportJson as AurumReport;

export type ReportSource = 'live' | 'fixture';

export interface ReportPayload {
  report: AurumReport;
  source: ReportSource;
}

async function loadReport(): Promise<ReportPayload> {
  try {
    const health = await getMetadataHealth().catch(() => ({ status: 'error' }));
    if (health.status !== 'ok') {
      return { report: sampleReport, source: 'fixture' };
    }
    const report = await fetchLatestReport();
    return { report, source: 'live' };
  } catch {
    return { report: sampleReport, source: 'fixture' };
  }
}

export function useReport() {
  return useQuery({
    queryKey: ['aurum', 'report', 'latest'],
    queryFn: loadReport,
    staleTime: 15_000,
  });
}

export function useRunValidation() {
  const queryClient = useQueryClient();
  return async (runId = 'demo_run_001') => {
    const report = await runValidation(runId);
    const payload: ReportPayload = { report, source: 'live' };
    queryClient.setQueryData(['aurum', 'report', 'latest'], payload);
    return payload;
  };
}
