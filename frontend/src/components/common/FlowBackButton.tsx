import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { cn } from '@/utils/cn';

interface FlowBackButtonProps {
  path: string;
  label: string;
  className?: string;
  /** Compact text-link style for ProjectSubNav; default is ghost button. */
  variant?: 'ghost' | 'nav';
}

export function FlowBackButton({
  path,
  label,
  className,
  variant = 'ghost',
}: FlowBackButtonProps) {
  const navigate = useNavigate();

  if (variant === 'nav') {
    return (
      <button
        type="button"
        onClick={() => navigate(path)}
        className={cn(
          'inline-flex items-center gap-1.5 px-2 py-3 text-xs font-semibold text-[#6b7280] hover:text-[#f1f5f9] transition-colors focus:outline-none focus:text-[#f1f5f9]',
          className,
        )}
        aria-label={label}
      >
        <ArrowLeft size={14} />
        <span className="hidden sm:inline">{label}</span>
        <span className="sm:hidden">Back</span>
      </button>
    );
  }

  return (
    <Button
      variant="ghost"
      leftIcon={<ArrowLeft size={16} />}
      onClick={() => navigate(path)}
      className={className}
    >
      {label}
    </Button>
  );
}
