import { cn } from '@/utils/cn';

interface ProgressMetricProps {
  label: string;
  percentage: number;
  colorClass?: string;
}

export function ProgressMetric({ label, percentage, colorClass = 'bg-[#22c55e]' }: ProgressMetricProps) {
  return (
    <div className="flex items-center gap-4 text-xs">
      <div className="w-28 flex-shrink-0 truncate font-mono text-[#94a3b8]" title={label}>
        {label}
      </div>
      <div className="flex-1 h-2.5 rounded-full bg-[#1a1b28] overflow-hidden">
        <div 
          className={cn('h-full transition-all duration-500 ease-out', colorClass)}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="w-10 flex-shrink-0 text-right font-semibold text-[#6366f1]">
        {percentage}%
      </div>
    </div>
  );
}
