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
  if (checks.length === 0) {
    return (
      <p className="text-sm text-[#6b7280]">No checks available for this layer.</p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {checks.map((check) => (
        <ValidationCard
          key={check.check_id}
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
      ))}
    </div>
  );
}
