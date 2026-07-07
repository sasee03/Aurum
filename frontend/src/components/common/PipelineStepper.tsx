import { cn } from '@/utils/cn';
import { ArrowRight } from 'lucide-react';

interface Stage {
  id: string;
  name: string;
  subtitle: string;
}

interface PipelineStepperProps {
  stages: Stage[];
  activeStageId: string;
  onSelectStage?: (id: string) => void;
}

export function PipelineStepper({ stages, activeStageId, onSelectStage }: PipelineStepperProps) {
  return (
    <div className="flex items-center gap-4">
      {stages.map((stage, index) => {
        const isActive = stage.id === activeStageId;
        const isSelected = onSelectStage !== undefined;
        return (
          <div key={stage.id} className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => onSelectStage?.(stage.id)}
              disabled={!isSelected}
              className={cn(
                'flex flex-col items-center justify-center rounded-xl p-3 w-32 border transition-all duration-200',
                isActive
                  ? 'border-[#6366f1] bg-[#6366f1]/10 shadow-[0_0_12px_rgba(99,102,241,0.15)] ring-1 ring-[#6366f1]'
                  : 'border-[#252637] bg-[#1a1b28] hover:border-[#6366f1]/30 hover:bg-[#252637]',
                isSelected ? 'cursor-pointer' : 'cursor-default'
              )}
            >
              <h4 className={cn('text-sm font-bold', isActive ? 'text-[#f1f5f9]' : 'text-[#94a3b8]')}>
                {stage.name}
              </h4>
              <span className="text-[10px] text-[#6b7280] font-medium">{stage.subtitle}</span>
            </button>
            {index < stages.length - 1 && (
              <ArrowRight size={16} className="text-[#4b5563]" />
            )}
          </div>
        );
      })}
    </div>
  );
}
