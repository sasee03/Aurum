import { cn } from '@/utils/cn';

interface LoadingSkeletonProps {
  className?: string;
  count?: number;
}

export function LoadingSkeleton({ className, count = 1 }: LoadingSkeletonProps) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'animate-pulse rounded-lg bg-[#1a1b28]',
            className
          )}
          aria-hidden="true"
        />
      ))}
    </>
  );
}

export function ProjectCardSkeleton() {
  return (
    <div className="rounded-xl border border-[#252637] bg-[#13141e] p-4 space-y-3 animate-pulse">
      <div className="h-4 w-2/3 rounded bg-[#1a1b28]" />
      <div className="h-3 w-1/2 rounded bg-[#1a1b28]" />
      <div className="h-5 w-16 rounded-md bg-[#1a1b28]" />
    </div>
  );
}

export function TableRowSkeleton() {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-[#252637] animate-pulse">
      <div className="h-4 w-4 rounded bg-[#1a1b28]" />
      <div className="flex-1 h-4 rounded bg-[#1a1b28]" />
      <div className="h-4 w-24 rounded bg-[#1a1b28]" />
      <div className="h-4 w-16 rounded bg-[#1a1b28]" />
    </div>
  );
}
