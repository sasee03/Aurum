import React from 'react';
import { Card } from '@/components/ui/Card';
import { cn } from '@/utils/cn';

interface MetricCardProps {
  label: string;
  value: string | number;
  subValue?: React.ReactNode;
  valueClass?: string;
  className?: string;
}

export function MetricCard({ label, value, subValue, valueClass, className }: MetricCardProps) {
  return (
    <Card className={cn('flex flex-col justify-center gap-1.5 p-5 min-h-[96px]', className)}>
      <span className="text-[10px] font-bold uppercase tracking-widest text-[#6b7280]">
        {label}
      </span>
      <div className={cn('text-2xl font-black tracking-tight', valueClass || 'text-[#f1f5f9]')}>
        {value}
      </div>
      {subValue && (
        <div className="text-[10px] font-medium text-[#4b5563] mt-0.5">
          {subValue}
        </div>
      )}
    </Card>
  );
}
