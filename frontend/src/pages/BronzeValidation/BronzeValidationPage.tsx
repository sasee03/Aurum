import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { ValidationCard } from '@/components/cards/ValidationCard';
import type { ValidationMetric } from '@/types';
import bronzeValidationJson from '@/mocks/bronzeValidation.json';

const validations = bronzeValidationJson as ValidationMetric[];

export function BronzeValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  
  const passCount = validations.filter(v => v.status === 'PASS').length;
  const warnCount = validations.filter(v => v.status === 'WARNING').length;
  const failCount = validations.filter(v => v.status === 'FAIL').length;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Bronze Validation</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Raw ingestion checks — the foundation. Nothing downstream is trustworthy if Bronze fails.
          </p>
          <div className="flex gap-2 mt-4">
            <Badge variant="pass">{passCount} PASS</Badge>
            <Badge variant="warning">{warnCount} WARNING</Badge>
            <Badge variant="failed">{failCount} FAIL</Badge>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 flex flex-col gap-4 bg-[#090a10]">
          {validations.map((val) => (
            <ValidationCard
              key={val.id}
              title={val.title}
              description={val.description}
              status={val.status}
            >
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
                {val.details.passedChecks && (
                  <div className="flex flex-col gap-1">
                    <span className="text-[#6b7280] font-medium">Passed Checks</span>
                    <span className="text-[#f1f5f9] tracking-tight">{val.details.passedChecks}</span>
                  </div>
                )}
                {val.details.threshold && (
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-[#6b7280] font-medium">Threshold</span>
                    <span className="text-[#f1f5f9] tracking-tight">{val.details.threshold}</span>
                  </div>
                )}
                {val.details.expectedValue && (
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-[#6b7280] font-medium">Expected Value</span>
                    <span className="text-[#f1f5f9] tracking-tight">{val.details.expectedValue}</span>
                  </div>
                )}
                {val.details.measuredValue && (
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-[#6b7280] font-medium">Measured Value</span>
                    <span className={val.status === 'WARNING' || val.status === 'FAIL' ? 'text-[#f59e0b]' : 'text-[#f1f5f9]'}>
                      {val.details.measuredValue}
                    </span>
                  </div>
                )}
                {val.details.timestamp && (
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-[#6b7280] font-medium">Timestamp</span>
                    <span className="text-[#f1f5f9] tracking-tight">{val.details.timestamp}</span>
                  </div>
                )}
              </div>
            </ValidationCard>
          ))}
        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => navigate(`/projects/${id}/validate/execution`)}
          >
            Back to Dashboard
          </Button>
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            onClick={() => navigate(`/projects/${id}/validate/silver`)}
          >
            Proceed to Silver Validation
          </Button>
        </div>
      </div>
    </div>
  );
}
