import React from 'react';
import { cn } from '@/utils/cn';
import type { ProjectStatus } from '@/types';

type BadgeVariant = 'pass' | 'warning' | 'failed' | 'default' | 'primary' | 'secondary' | 'accent';

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}

const variantClass: Record<BadgeVariant, string> = {
  pass: 'bg-[#10b981]/15 text-[#10b981] border border-[#10b981]/30',
  warning: 'bg-[#f59e0b]/15 text-[#f59e0b] border border-[#f59e0b]/30',
  failed: 'bg-[#ef4444]/15 text-[#ef4444] border border-[#ef4444]/30',
  default: 'bg-[#131a29] text-[#94a3b8] border border-[#273549]',
  primary: 'bg-[#2563eb]/15 text-[#3b82f6] border border-[#3b82f6]/30',
  secondary: 'bg-[#131a29] text-[#94a3b8] border border-[#273549]',
  accent: 'bg-[#06b6d4]/15 text-[#06b6d4] border border-[#06b6d4]/30',
};

const dotClass: Record<BadgeVariant, string> = {
  pass: 'bg-[#10b981]',
  warning: 'bg-[#f59e0b]',
  failed: 'bg-[#ef4444]',
  default: 'bg-[#94a3b8]',
  primary: 'bg-[#3b82f6]',
  secondary: 'bg-[#94a3b8]',
  accent: 'bg-[#06b6d4]',
};

export function Badge({ variant = 'default', children, className, dot }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide select-none',
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

export function VerdictBadge({ verdict }: { verdict: string }) {
  const variant: BadgeVariant =
    verdict === 'TRUSTED' || verdict === 'PASS' ? 'pass' : verdict === 'WARNING' ? 'warning' : 'failed';
  return <Badge variant={variant}>{verdict}</Badge>;
}
