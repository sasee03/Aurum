import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Check, RefreshCw, CircleDashed, ArrowRight, Play } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { LogConsole } from '@/components/common/LogConsole';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import {
  isPersistedUserRunId,
  useReport,
  useRunValidation,
  withRunIdQuery,
} from '@/hooks/useReport';
import { layerStageStatus } from '@/utils/reportFormat';
import { cn } from '@/utils/cn';
import type { ExecutionLog } from '@/types';

type StageName = 'Bronze' | 'Silver' | 'Gold';
type StageStatus = 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED';

function getStatusConfig(status: StageStatus) {
  switch (status) {
    case 'SUCCESS':
      return {
        icon: <Check size={20} className="text-[#22c55e]" />,
        ring: 'border-[#22c55e] text-[#22c55e]',
        badge: 'pass' as const,
        line: 'bg-[#22c55e]',
      };
    case 'RUNNING':
      return {
        icon: <RefreshCw size={20} className="text-[#3b82f6] animate-spin" />,
        ring: 'border-[#3b82f6] text-[#3b82f6]',
        badge: 'primary' as const,
        line: 'bg-[#3b82f6]',
      };
    case 'FAILED':
      return {
        icon: <Check size={20} className="text-[#ef4444]" />,
        ring: 'border-[#ef4444] text-[#ef4444]',
        badge: 'failed' as const,
        line: 'bg-[#ef4444]',
      };
    default:
      return {
        icon: <CircleDashed size={20} className="text-[#4b5563]" />,
        ring: 'border-[#252637] text-[#4b5563]',
        badge: 'secondary' as const,
        line: 'bg-[#1a1b28]',
      };
  }
}

export function ValidationDashboardPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runIdParam = searchParams.get('runId') ?? undefined;
  const viewingPersistedRun = isPersistedUserRunId(runIdParam);
  const { displayMode, canRunValidation, isResolved } = useAppMode();
  const { data, isLoading } = useReport();
  const runValidation = useRunValidation();
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [finished, setFinished] = useState(false);
  const [completedRunId, setCompletedRunId] = useState<string | undefined>(runIdParam);

  const report = data?.report;
  const snapshotMode = !canRunValidation;
  // Prefer the URL/active run — never let a stale "latest" report override an upload/connector id.
  const activeRunId = completedRunId ?? runIdParam ?? report?.run_id;

  const stages: { stage: StageName; status: StageStatus }[] = report
    ? [
        {
          stage: 'Bronze',
          status: running && !finished ? 'RUNNING' : layerStageStatus(report.layer_status.bronze),
        },
        {
          stage: 'Silver',
          status: running && !finished ? 'QUEUED' : layerStageStatus(report.layer_status.silver),
        },
        {
          stage: 'Gold',
          status: running && !finished ? 'QUEUED' : layerStageStatus(report.layer_status.gold),
        },
      ]
    : [
        { stage: 'Bronze', status: 'QUEUED' },
        { stage: 'Silver', status: 'QUEUED' },
        { stage: 'Gold', status: 'QUEUED' },
      ];

  function persistedRunNotice(): string {
    if (runIdParam?.startsWith('upload_')) {
      return 'Your uploaded file has already been validated. Continue to see the results — your data will not be replaced with a sample dataset.';
    }
    if (runIdParam?.startsWith('connector_')) {
      return 'Your connected data has already been validated. Continue to see the results — your data will not be replaced with a sample dataset.';
    }
    return 'Your data has already been validated. Continue to see the results — your data will not be replaced with a sample dataset.';
  }

  async function handleRun() {
    // Upload/connector validation already produced a full report — never call
    // POST /runs here (that always re-runs the sample dataset and overwrites context).
    if (viewingPersistedRun && runIdParam) {
      setCompletedRunId(runIdParam);
      setFinished(true);
      setLogs([
        {
          id: '1',
          timestamp: new Date().toISOString(),
          level: 'INFO',
          message: 'Your data was already validated when you uploaded or connected it.',
        },
        {
          id: '2',
          timestamp: new Date().toISOString(),
          level: 'INFO',
          message: 'Loading your existing results — your data will not be replaced.',
        },
      ]);
      navigate(resultsPath);
      return;
    }

    if (!canRunValidation) return;

    setRunning(true);
    setFinished(false);
    setLogs([
      {
        id: '1',
        timestamp: new Date().toISOString(),
        level: 'RUN',
        message: 'Starting validation on the sample dataset…',
      },
    ]);
    try {
      const result = await runValidation('demo_run_001');
      setCompletedRunId(result.report.run_id);
      setLogs((prev) => [
        ...prev,
        {
          id: '2',
          timestamp: new Date().toISOString(),
          level: result.report.layer_status.silver === 'FAIL' ? 'FAIL' : 'PASS',
          message: `Verdict: ${result.report.final_verdict} | Bronze ${result.report.layer_status.bronze} Silver ${result.report.layer_status.silver} Gold ${result.report.layer_status.gold}`,
        },
        {
          id: '3',
          timestamp: new Date().toISOString(),
          level: 'INFO',
          message: `Validation complete. First issue layer: ${result.report.first_failed_layer ?? 'none'}`,
        },
      ]);
      setFinished(true);
    } catch {
      setLogs((prev) => [
        ...prev,
        {
          id: 'err',
          timestamp: new Date().toISOString(),
          level: 'FAIL',
          message: 'Validation could not complete. Check that the backend and database are running.',
        },
      ]);
    } finally {
      setRunning(false);
    }
  }

  if (!isResolved || isLoading) {
    return (
      <div className="p-6">
        <LoadingSkeleton count={3} className="h-16" />
      </div>
    );
  }

  // Results are viewable when there is a report (snapshot, upload, or after a live run)
  const canViewResults = Boolean(report) || finished || viewingPersistedRun;

  const resultsPath = withRunIdQuery(
    `/projects/${id}/validate/bronze`,
    activeRunId,
  );

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={activeRunId} isRunning={running} />
      <PageAssistant page="validation" runId={activeRunId} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Validation Execution</h2>
        <DataSourceBadge mode={displayMode} />
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 flex flex-col gap-6">

        {viewingPersistedRun && (
          <p className="text-sm text-[#94a3b8] rounded-lg border border-[#252637] bg-[#13141e] px-4 py-3 max-w-3xl mx-auto text-center">
            {persistedRunNotice()}
          </p>
        )}

        <div className="flex justify-center">
          <Button
            variant="primary"
            leftIcon={<Play size={16} />}
            onClick={viewingPersistedRun || canRunValidation ? handleRun : undefined}
            disabled={
              running ||
              (!viewingPersistedRun && !canRunValidation)
            }
            title={
              snapshotMode && !viewingPersistedRun
                ? 'Start PostgreSQL and check /health to enable live validation'
                : undefined
            }
          >
            {running
              ? 'Running validation…'
              : viewingPersistedRun
                ? 'Continue to results'
                : 'Run Validation'}
          </Button>
        </div>

        <div className="flex items-center justify-center py-10 bg-[#1a1b28]/30 rounded-xl border border-[#252637]">
          <div className="flex items-center justify-center w-full max-w-4xl px-8">
            {stages.map((stage, index) => {
              const config = getStatusConfig(stage.status);
              return (
                <div key={stage.stage} className="flex items-center flex-1 last:flex-none relative w-full">
                  <div className="flex flex-col items-center gap-3 relative z-10">
                    <div
                      className={cn(
                        'flex items-center justify-center w-16 h-16 rounded-3xl border-2 bg-[#0d0e14] transition-colors duration-500',
                        config.ring,
                      )}
                    >
                      {config.icon}
                    </div>
                    <div className="flex flex-col items-center gap-1.5">
                      <span className="text-sm font-bold text-[#f1f5f9]">{stage.stage}</span>
                      <Badge variant={config.badge} className="px-3">
                        {stage.status}
                      </Badge>
                    </div>
                  </div>
                  {index < stages.length - 1 && (
                    <div
                      className={cn(
                        'absolute top-8 left-8 w-[calc(100%-2rem)] h-1 -translate-y-1/2 transition-colors duration-500',
                        config.line,
                      )}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex-1 min-h-[200px]">
          <LogConsole logs={logs} />
        </div>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex justify-end">
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          disabled={!canViewResults}
          onClick={() => navigate(resultsPath)}
        >
          View Validation Results
        </Button>
      </div>
    </div>
  );
}
