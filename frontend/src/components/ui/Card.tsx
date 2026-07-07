import React from 'react';
import { cn } from '@/utils/cn';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  role?: string;
  tabIndex?: number;
  'aria-label'?: string;
  hoverable?: boolean;
}

export function Card({ children, className, onClick, hoverable = false, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-[#252637] bg-[#13141e] p-4 transition-all duration-200',
        hoverable &&
          'cursor-pointer hover:border-[#6366f1]/30 hover:bg-[#1a1b28] hover:shadow-[0_0_16px_rgba(99,102,241,0.08)]',
        onClick && 'cursor-pointer',
        className
      )}
      onClick={onClick}
      {...props}
    >
      {children}
    </div>
  );
}
