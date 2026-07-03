import React from 'react';
import { cn } from '@/utils/cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary:
    'bg-[#6366f1] text-white hover:bg-[#4f46e5] shadow-[0_0_20px_rgba(99,102,241,0.25)] hover:shadow-[0_0_24px_rgba(99,102,241,0.4)] active:scale-[0.98]',
  secondary:
    'bg-[#1a1b28] text-[#f1f5f9] border border-[#252637] hover:bg-[#252637] active:scale-[0.98]',
  ghost:
    'text-[#94a3b8] hover:text-[#f1f5f9] hover:bg-[#1a1b28] active:scale-[0.98]',
  danger:
    'bg-[#ef4444]/10 text-[#ef4444] border border-[#ef4444]/30 hover:bg-[#ef4444]/20 active:scale-[0.98]',
  outline:
    'border border-[#252637] text-[#f1f5f9] hover:bg-[#1a1b28] active:scale-[0.98]',
};

const sizeClass: Record<Size, string> = {
  sm: 'h-7 px-3 text-xs rounded-md gap-1.5',
  md: 'h-9 px-4 text-sm rounded-lg gap-2',
  lg: 'h-11 px-6 text-sm rounded-lg gap-2',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      isLoading = false,
      leftIcon,
      rightIcon,
      children,
      className,
      disabled,
      ...props
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        aria-busy={isLoading}
        className={cn(
          'inline-flex items-center justify-center font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6366f1] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0d0e14] disabled:pointer-events-none disabled:opacity-50 select-none',
          variantClass[variant],
          sizeClass[size],
          className
        )}
        {...props}
      >
        {isLoading ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : (
          leftIcon
        )}
        {children}
        {!isLoading && rightIcon}
      </button>
    );
  }
);

Button.displayName = 'Button';
