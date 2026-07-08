import React from 'react';
import { cn } from '@/utils/cn';
import type { ProjectStatus } from '@/types';

type BadgeVariant = 'pass' | 'warning' | 'failed' | 'default' | 'primary' | 'secondary';

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}

const variantClass: Record<BadgeVariant, string> = {
  pass: 'bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/25',
  warning: 'bg-[#f59e0b]/15 text-[#f59e0b] border border-[#f59e0b]/25',
  failed: 'bg-[#ef4444]/15 text-[#ef4444] border border-[#ef4444]/25',
  default: 'bg-[#1a1b28] text-[#94a3b8] border border-[#252637]',
  primary: 'bg-[#6366f1]/15 text-[#6366f1] border border-[#6366f1]/25',
  secondary: 'bg-[#1a1b28] text-[#94a3b8] border border-[#252637]',
};

const dotClass: Record<BadgeVariant, string> = {
  pass: 'bg-[#22c55e]',
  warning: 'bg-[#f59e0b]',
  failed: 'bg-[#ef4444]',
  default: 'bg-[#94a3b8]',
  primary: 'bg-[#6366f1]',
  secondary: 'bg-[#94a3b8]',
};

export function Badge({ variant = 'default', children, className, dot }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide',
        variantClass[variant],
        className
      )}
    >
      {dot && (
        <span className={cn('h-1.5 w-1.5 rounded-full animate-pulse-slow', dotClass[variant])} />
      )}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: ProjectStatus }) {
  const map: Record<ProjectStatus, BadgeVariant> = {
    PASS: 'pass',
    WARNING: 'warning',
    FAILED: 'failed',
  };
  return <Badge variant={map[status]}>{status}</Badge>;
}
