import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, RefreshCw, CircleDashed, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { LogConsole } from '@/components/common/LogConsole';
import { cn } from '@/utils/cn';

import type { PipelineStageEvent, ExecutionLog } from '@/types';
import validationExecutionJson from '@/mocks/validationExecution.json';
import executionLogsJson from '@/mocks/executionLogs.json';

const initialStages = validationExecutionJson as PipelineStageEvent[];
const logsRecord = executionLogsJson as ExecutionLog[];

export function ValidationDashboardPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  
  // Simulate log streaming
  const [visibleLogs, setVisibleLogs] = useState<ExecutionLog[]>([]);
  // Simulated state that advances to "Finished" after some time so we can show next button
  const [isFinished, setIsFinished] = useState(false);
  const [stages, setStages] = useState(initialStages);

  useEffect(() => {
    let currentIndex = 0;
    const interval = setInterval(() => {
      if (currentIndex < logsRecord.length) {
        setVisibleLogs((prev) => [...prev, logsRecord[currentIndex]]);
        currentIndex++;
      } else {
        clearInterval(interval);
        setTimeout(() => {
          setIsFinished(true);
          // Set all to SUCCESS when finished for mock purpose
          setStages([
            { stage: 'Bronze', status: 'SUCCESS' },
            { stage: 'Silver', status: 'SUCCESS' },
            { stage: 'Gold', status: 'SUCCESS' },
          ]);
        }, 1500);
      }
    }, 400); // add a log every 400ms

    return () => clearInterval(interval);
  }, []);

  function getStatusConfig(status: string) {
    switch (status) {
      case 'SUCCESS':
        return {
          icon: <Check size={20} className="text-[#22c55e]" />,
          ring: 'border-[#22c55e] text-[#22c55e]',
          badge: 'pass' as const,
          line: 'bg-[#22c55e]'
        };
      case 'RUNNING':
        return {
          icon: <RefreshCw size={20} className="text-[#3b82f6] animate-spin" />,
          ring: 'border-[#3b82f6] text-[#3b82f6]',
          badge: 'primary' as const,
          line: 'bg-[#3b82f6]'
        };
      case 'FAILED':
        return {
          icon: <Check size={20} className="text-[#ef4444]" />,
          ring: 'border-[#ef4444] text-[#ef4444]',
          badge: 'failed' as const,
          line: 'bg-[#ef4444]'
        };
      default: // QUEUED
        return {
          icon: <CircleDashed size={20} className="text-[#4b5563]" />,
          ring: 'border-[#252637] text-[#4b5563]',
          badge: 'secondary' as const,
          line: 'bg-[#1a1b28]'
        };
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Validation Dashboard</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Live pipeline execution — Bronze → Silver → Gold
          </p>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 flex flex-col gap-6">
          
          {/* Top Section - Pipeline Progress */}
          <div className="flex items-center justify-center py-10 bg-[#1a1b28]/30 rounded-xl border border-[#252637]">
            <div className="flex items-center justify-center w-full max-w-4xl px-8">
              {stages.map((stage, index) => {
                const config = getStatusConfig(stage.status);
                
                return (
                  <div key={stage.stage} className="flex items-center flex-1 last:flex-none relative w-full">
                    <div className="flex flex-col items-center gap-3 relative z-10">
                      <div className={cn(
                        "flex items-center justify-center w-16 h-16 rounded-3xl border-2 bg-[#0d0e14] transition-colors duration-500",
                        config.ring
                      )}>
                        {config.icon}
                      </div>
                      <div className="flex flex-col items-center gap-1.5">
                        <span className="text-sm font-bold text-[#f1f5f9]">{stage.stage}</span>
                        <Badge variant={config.badge} className="px-3" size="sm">
                          {stage.status}
                        </Badge>
                      </div>
                    </div>
                    {/* Connecting Line */}
                    {index < stages.length - 1 && (
                      <div className={cn(
                        "absolute top-8 left-8 w-[calc(100%-2rem)] h-1 -translate-y-1/2 transition-colors duration-500",
                        config.line
                      )}>
                        <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 text-[#4b5563]">
                          <ArrowRight size={14} className="opacity-50" />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Log Console Section */}
          <div className="flex-1 min-h-[300px]">
            <LogConsole logs={visibleLogs} />
          </div>

        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
          <div className="flex gap-6 text-xs text-[#94a3b8] font-mono">
            <span>Pipeline completion: <strong className="text-[#f1f5f9]">{isFinished ? '100' : '45'}%</strong></span>
            <span>Current active stage: <strong className="text-[#f1f5f9]">{isFinished ? 'Completed' : 'Silver'}</strong></span>
            <span>Estimated remaining time: <strong className="text-[#f1f5f9]">{isFinished ? '0:00' : '2:15'}</strong></span>
          </div>
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            disabled={!isFinished}
            onClick={() => navigate(`/projects/${id}/validate/bronze`)}
          >
            View Validation Results
          </Button>
        </div>
      </div>
    </div>
  );
}
