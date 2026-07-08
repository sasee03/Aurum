import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';

interface ValidationCardProps {
  title: string;
  description: string;
  status: 'PASS' | 'WARNING' | 'FAIL';
  children?: React.ReactNode;
}

export function ValidationCard({ title, description, status, children }: ValidationCardProps) {
  const [expanded, setExpanded] = useState(false);

  const statusVariant = status === 'FAIL' ? 'failed' : status === 'WARNING' ? 'warning' : 'pass';
  
  return (
    <Card className="p-0 overflow-hidden">
      <button
        onClick={() => children && setExpanded(!expanded)}
        className={cn(
          "w-full flex items-center justify-between p-4 transition-colors focus:outline-none focus:bg-[#1a1b28]",
          children ? "hover:bg-[#1a1b28] cursor-pointer" : "cursor-default"
        )}
      >
        <div className="flex flex-col items-start gap-1 text-left">
          <h4 className="text-sm font-semibold text-[#f1f5f9]">{title}</h4>
          <p className="text-xs text-[#6b7280]">{description}</p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={statusVariant} className="flex-shrink-0">
            {status === 'FAIL' ? '❌ FAIL' : status === 'WARNING' ? '⚠️ WARNING' : '✓ PASS'}
          </Badge>
          {children && (
            <div className="text-[#6b7280]">
              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </div>
          )}
        </div>
      </button>
      {expanded && children && (
        <div className="border-t border-[#252637] bg-[#0d0e14]/50 p-4 animate-slide-up">
          {children}
        </div>
      )}
    </Card>
  );
}
