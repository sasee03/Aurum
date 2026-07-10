import type { ReactNode } from 'react';
import { AlertTriangle, Check, CircleDashed, RefreshCw, X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';

type BadgeVariant = 'pass' | 'warning' | 'failed' | 'default' | 'primary' | 'secondary';

export type LayerStatus = 'PASS' | 'FAIL' | 'IMPACTED' | 'WARN' | 'SKIPPED' | 'QUEUED' | 'RUNNING' | string;

export interface LayerStatusPresentation {
  color: string;
  badge: BadgeVariant;
  icon: ReactNode;
  line: string;
  dashed?: boolean;
}

export function layerStatusPresentation(status: LayerStatus): LayerStatusPresentation {
  const u = status.toUpperCase();
  if (u === 'PASS') {
    return {
      color: '#22c55e',
      badge: 'pass',
      icon: <Check size={20} className="text-[#22c55e]" />,
      line: 'bg-[#22c55e]',
    };
  }
  if (u === 'FAIL' || u === 'FAILED') {
    return {
      color: '#ef4444',
      badge: 'failed',
      icon: <X size={20} className="text-[#ef4444]" />,
      line: 'bg-[#ef4444]',
    };
  }
  if (u === 'IMPACTED' || u === 'WARN' || u === 'WARNING') {
    return {
      color: u === 'IMPACTED' ? '#f97316' : '#f59e0b',
      badge: 'warning',
      icon: <AlertTriangle size={20} className={u === 'IMPACTED' ? 'text-[#f97316]' : 'text-[#f59e0b]'} />,
      line: u === 'IMPACTED' ? 'bg-[#f97316]' : 'bg-[#f59e0b]',
    };
  }
  if (u === 'RUNNING') {
    return {
      color: '#3b82f6',
      badge: 'primary',
      icon: <RefreshCw size={20} className="animate-spin text-[#3b82f6]" />,
      line: 'bg-[#3b82f6]',
    };
  }
  return {
    color: '#4b5563',
    badge: u === 'QUEUED' ? 'secondary' : 'default',
    icon: <CircleDashed size={20} className="text-[#4b5563]" />,
    line: 'bg-[#1a1b28]',
    dashed: true,
  };
}

interface LayerStatusRingProps {
  layer: string;
  status: LayerStatus;
  mode?: 'execution' | 'trust';
  className?: string;
}

export function LayerStatusRing({ layer, status, mode = 'trust', className }: LayerStatusRingProps) {
  const presentation = layerStatusPresentation(status);
  const normalizedStatus = status.toUpperCase();

  if (mode === 'execution') {
    return (
      <div className={cn('flex flex-col items-center gap-3 relative z-10', className)}>
        <div
          className="flex h-16 w-16 items-center justify-center rounded-3xl border-2 bg-[#0d0e14] transition-colors duration-500"
          style={{ borderColor: presentation.color, color: presentation.color }}
        >
          {presentation.icon}
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <span className="text-sm font-bold text-[#f1f5f9]">{layer}</span>
          <Badge variant={presentation.badge} className="px-3">
            {normalizedStatus}
          </Badge>
        </div>
      </div>
    );
  }

  const radius = 52;
  const stroke = 8;
  const normalizedRadius = radius - stroke / 2;
  const circumference = 2 * Math.PI * normalizedRadius;
  const dashArray = presentation.dashed
    ? `${circumference * 0.12} ${circumference * 0.08}`
    : circumference;

  return (
    <div className={cn('flex flex-col items-center rounded-xl border border-[#252637] bg-[#13141e] px-5 py-4', className)}>
      <div className="relative">
        <svg width={radius * 2} height={radius * 2} className="-rotate-90">
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke="#1a1b28"
            strokeWidth={stroke}
          />
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke={presentation.color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={dashArray}
            strokeDashoffset={0}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
          {presentation.icon}
          <Badge variant={presentation.badge}>{normalizedStatus}</Badge>
        </div>
      </div>
      <p className="mt-3 text-sm font-semibold capitalize text-[#f1f5f9]">{layer}</p>
      <p className="text-[10px] text-[#6b7280]">layer_status.{layer}</p>
    </div>
  );
}
