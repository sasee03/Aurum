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
        'rounded-xl border border-[#1e293b] bg-[#111827] p-5 transition-all duration-200 shadow-sm',
        hoverable &&
          'cursor-pointer hover:border-[#3b82f6]/40 hover:bg-[#131a29] hover:shadow-[0_0_16px_rgba(37,99,235,0.12)]',
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
