import { Bug } from 'lucide-react';

interface RootCauseCardProps {
  explanation: string;
  affectedRecords: string;
  suggestedFix: string;
}

export function RootCauseCard({ explanation, affectedRecords, suggestedFix }: RootCauseCardProps) {
  return (
    <div className="rounded-lg border border-[#ef4444]/30 bg-[#ef4444]/5 p-4 shadow-[0_0_15px_rgba(239,68,68,0.05)]">
      <div className="flex gap-2 items-center mb-2 text-[#ef4444]">
        <Bug size={16} />
        <h4 className="text-sm font-bold">Root Cause</h4>
      </div>
      <p className="text-xs text-[#f1f5f9] mb-3 leading-relaxed">
        {explanation}
      </p>
      <div className="space-y-1 mt-3 text-[11px]">
        <div className="flex gap-2">
          <span className="text-[#6b7280] font-medium w-24">Impact:</span>
          <span className="text-[#f59e0b] font-mono">{affectedRecords}</span>
        </div>
        <div className="flex gap-2">
          <span className="text-[#6b7280] font-medium w-24">Suggested fix:</span>
          <span className="text-[#92cae5]">{suggestedFix}</span>
        </div>
      </div>
    </div>
  );
}
