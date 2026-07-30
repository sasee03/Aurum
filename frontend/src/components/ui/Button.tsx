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
    'bg-[#2563eb] text-white hover:bg-[#1d4ed8] shadow-[0_0_16px_rgba(37,99,235,0.3)] hover:shadow-[0_0_20px_rgba(37,99,235,0.45)] active:scale-[0.98] border border-[#3b82f6]/40',
  secondary:
    'bg-[#131a29] text-[#f8fafc] border border-[#273549] hover:bg-[#1f293d] hover:border-[#3b82f6]/50 active:scale-[0.98]',
  ghost:
    'text-[#94a3b8] hover:text-[#f8fafc] hover:bg-[#131a29] active:scale-[0.98]',
  danger:
    'bg-[#ef4444]/10 text-[#ef4444] border border-[#ef4444]/30 hover:bg-[#ef4444]/20 active:scale-[0.98]',
  outline:
    'border border-[#273549] text-[#f8fafc] hover:bg-[#131a29] hover:border-[#3b82f6]/40 active:scale-[0.98]',
};

const sizeClass: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs rounded-md gap-1.5',
  md: 'h-10 px-4 text-sm rounded-lg gap-2',
  lg: 'h-11 px-6 text-sm font-medium rounded-lg gap-2',
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
          'inline-flex items-center justify-center font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3b82f6] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b0f19] disabled:pointer-events-none disabled:opacity-50 select-none cursor-pointer',
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
