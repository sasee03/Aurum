import type { ReportSource } from '@/hooks/useReport';

interface Props {
  source: ReportSource;
  className?: string;
}

export function DataSourceBadge({ source, className = '' }: Props) {
  if (source === 'live') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border border-[#22c55e]/30 bg-[#22c55e]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#22c55e] ${className}`}
      >
        Live API
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#f59e0b] ${className}`}
      title="NOT TRUSTED failure-path fixture — not a PASS/TRUSTED demo"
    >
      Fixture fallback
    </span>
  );
}
