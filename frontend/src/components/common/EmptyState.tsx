import { PackageOpen } from 'lucide-react';
import { Button } from '@/components/ui/Button';

interface EmptyStateProps {
  title?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  title = 'No Existing Projects',
  description = 'Create your first project to begin validating data.',
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center animate-fade-in">
      <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl border border-[#252637] bg-[#1a1b28]">
        <PackageOpen size={32} className="text-[#6366f1]" />
      </div>
      <h3 className="mb-2 text-lg font-semibold text-[#f1f5f9]">{title}</h3>
      <p className="mb-8 max-w-xs text-sm text-[#6b7280]">{description}</p>
      {actionLabel && onAction && (
        <Button variant="primary" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
