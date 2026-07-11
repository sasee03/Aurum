import { useEffect } from 'react';
import { ValidationCard } from '@/components/cards/ValidationCard';
import { SQLViewer } from '@/components/common/SQLViewer';
import type { CheckResult } from '@/types/report';
import {
  formatExpected,
  formatObserved,
  toDisplayStatus,
} from '@/utils/reportFormat';

interface Props {
  checks: CheckResult[];
  showSql?: boolean;
}

export function ReportCheckList({ checks, showSql = false }: Props) {
  useEffect(() => {
    if (checks.length === 0 || !window.location.hash) return;

    let checkId: string;
    try {
      checkId = decodeURIComponent(window.location.hash.slice(1));
    } catch {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      document.getElementById(checkId)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [checks]);

  if (checks.length === 0) {
    return (
      <p className="text-sm text-[#6b7280]">No checks available for this layer.</p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {checks.map((check) => (
        <div
          key={check.check_id}
          id={check.check_id}
          className="scroll-mt-6 rounded-lg target:ring-2 target:ring-[#6366f1] target:ring-offset-4 target:ring-offset-[#090a10]"
        >
          <ValidationCard
            title={`${check.check_id} — ${check.check_name}`}
            description={check.detail}
            status={toDisplayStatus(check.status)}
          >
            <div className="flex flex-col gap-4 text-xs">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="flex flex-col gap-1">
                  <span className="text-[#6b7280] font-medium">Observed</span>
                  <span className="text-[#f1f5f9] tracking-tight break-all">
                    {formatObserved(check.observed)}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[#6b7280] font-medium">Expected</span>
                  <span className="text-[#f1f5f9] tracking-tight break-all">
                    {formatExpected(check.expected)}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[#6b7280] font-medium">Engine status</span>
                  <span className="text-[#f1f5f9]">{check.status}</span>
                </div>
              </div>
              {showSql && check.evidence_query && (
                <SQLViewer title={`EVIDENCE — ${check.check_id}`} code={check.evidence_query} />
              )}
            </div>
          </ValidationCard>
        </div>
      ))}
    </div>
  );
}
