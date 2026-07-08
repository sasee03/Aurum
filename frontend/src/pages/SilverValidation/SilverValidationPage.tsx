import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { ValidationCard } from '@/components/cards/ValidationCard';
import { SQLViewer } from '@/components/common/SQLViewer';
import { RootCauseCard } from '@/components/cards/RootCauseCard';
import type { ValidationMetric } from '@/types';
import silverValidationJson from '@/mocks/silverValidation.json';

const validations = silverValidationJson as ValidationMetric[];

export function SilverValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  
  const passCount = validations.filter(v => v.status === 'PASS').length;
  const warnCount = validations.filter(v => v.status === 'WARNING').length;
  const failCount = validations.filter(v => v.status === 'FAIL').length;

  const mCode = `SELECT 
  o.order_id, o.customer_id, o.status,
  o.total * (1 - o.discount_pct) AS net_total 
FROM bronze.orders o
WHERE o.status != 'void'
  AND o.discount_pct <= 0   -- ⚠️ BUG: excludes valid discounted orders`;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Silver Validation</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Transformation correctness — where logic bugs typically hide.
          </p>
          <div className="flex gap-2 mt-4">
            <Badge variant="pass">{passCount} PASS</Badge>
            <Badge variant="warning">{warnCount} WARNING</Badge>
            <Badge variant="failed">{failCount} FAIL</Badge> // Mock hardcoded 2 FAIL is from original mock image, actually dynamically computing is 2 FAIL
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-hidden p-6 gap-6 bg-[#090a10] grid grid-cols-1 lg:grid-cols-3">
          {/* Left panel validations */}
          <div className="lg:col-span-2 flex flex-col gap-4 overflow-y-auto scrollbar-thin">
            {validations.map((val) => (
              <ValidationCard
                key={val.id}
                title={val.title}
                description={val.description}
                status={val.status}
              >
                <div className="flex flex-col gap-4 text-xs">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {val.details.expectedValue && (
                      <div className="flex flex-col gap-1">
                        <span className="text-[#6b7280] font-medium">Expected Value</span>
                        <span className="text-[#f1f5f9] tracking-tight">{val.details.expectedValue}</span>
                      </div>
                    )}
                    {val.details.measuredValue && (
                      <div className="flex flex-col gap-1">
                        <span className="text-[#6b7280] font-medium">Measured Value</span>
                        <span className={val.status === 'FAIL' ? 'text-[#ef4444]' : 'text-[#f59e0b]'}>
                          {val.details.measuredValue}
                        </span>
                      </div>
                    )}
                    {val.details.threshold && (
                      <div className="flex flex-col gap-1">
                        <span className="text-[#6b7280] font-medium">Threshold</span>
                        <span className="text-[#f1f5f9] tracking-tight">{val.details.threshold}</span>
                      </div>
                    )}
                    {val.details.timestamp && (
                      <div className="flex flex-col gap-1">
                        <span className="text-[#6b7280] font-medium">Timestamp</span>
                        <span className="text-[#f1f5f9] tracking-tight">{val.details.timestamp}</span>
                      </div>
                    )}
                  </div>
                  
                  {val.details.rootCause && (
                    <RootCauseCard 
                      explanation={val.details.rootCause.explanation}
                      affectedRecords={val.details.rootCause.affectedRecords}
                      suggestedFix={val.details.rootCause.suggestedFix}
                    />
                  )}
                </div>
              </ValidationCard>
            ))}
          </div>

          <div className="h-full flex flex-col">
            <SQLViewer 
              title="TRANSFORMATION SQL — NET_TOTAL" 
              code={mCode}
              errorLine={6}
            />
          </div>
        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => navigate(`/projects/${id}/validate/bronze`)}
          >
             Back to Bronze
          </Button>
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            disabled
          >
            Proceed to Gold Validation
          </Button>
        </div>
      </div>
    </div>
  );
}
