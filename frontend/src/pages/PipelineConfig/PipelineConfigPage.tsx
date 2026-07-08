import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PlayCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { PipelineStepper } from '@/components/common/PipelineStepper';
import pipelineRulesJson from '@/mocks/pipelineRules.json';
import type { PipelineRule } from '@/types';

const rules = pipelineRulesJson as PipelineRule[];

const STAGES = [
  { id: 'source', name: 'Orders', subtitle: 'Source' },
  { id: 'bronze', name: 'Bronze', subtitle: 'Raw Ingestion' },
  { id: 'silver', name: 'Silver', subtitle: 'Transformed' },
  { id: 'gold', name: 'Gold', subtitle: 'KPI / Reports' },
];

export function PipelineConfigPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [activeStageId, setActiveStageId] = useState('bronze');

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Pipeline Configuration</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Define or accept default validation rules per medallion layer before execution.
          </p>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 flex flex-col gap-6">
          
          {/* Top Section - Pipeline Flow */}
          <div className="flex justify-center py-4 bg-[#1a1b28]/30 rounded-xl border border-[#252637]">
            <PipelineStepper 
              stages={STAGES} 
              activeStageId={activeStageId} 
              onSelectStage={setActiveStageId} 
            />
          </div>

          {/* Middle Section - Rule Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 flex-1">
            {['Bronze', 'Silver', 'Gold'].map((layer) => {
              const rule = rules.find((r) => r.category === layer);
              return (
                <div key={layer} className="flex flex-col rounded-xl border border-[#252637] bg-[#1a1b28]/30 overflow-hidden">
                  <div className="px-5 py-4 border-b border-[#252637] bg-[#1a1b28]">
                    <h3 className="text-xs font-bold uppercase tracking-widest text-[#22c55e]">
                      {layer} RULES
                    </h3>
                  </div>
                  <div className="p-5 flex-1 font-mono text-[11px] text-[#94a3b8] leading-relaxed whitespace-pre bg-[#0d0e14] overflow-x-auto scrollbar-thin">
                    {rule?.code || 'No rules configured.'}
                  </div>
                </div>
              );
            })}
          </div>

        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-end gap-3">
          <Button
            variant="ghost"
            onClick={() => navigate(`/projects/${id}/metadata`)} // Go back to metadata or previous step
          >
            Validate Metadata
          </Button>
          <Button
            variant="primary"
            rightIcon={<PlayCircle size={16} />}
            onClick={() => navigate(`/projects/${id}/validate/execution`)}
          >
            Start Validation
          </Button>
        </div>
      </div>
    </div>
  );
}
