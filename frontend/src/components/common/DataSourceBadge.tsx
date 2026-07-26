import type { DataSourceMode } from '@/types/appMode';
import { MODE_LABELS } from '@/types/appMode';

interface Props {
  mode: DataSourceMode;
  className?: string;
}

export function DataSourceBadge({ mode, className = '' }: Props) {
  if (mode === 'loading') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border border-[#4b5563]/30 bg-[#1a1b28] px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#6b7280] ${className}`}
      >
        Checking…
      </span>
    );
  }

  if (mode === 'live') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border border-[#22c55e]/30 bg-[#22c55e]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#22c55e] ${className}`}
      >
        {MODE_LABELS.live}
      </span>
    );
  }

  if (mode === 'user_upload') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border border-[#06b6d4]/30 bg-[#06b6d4]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#22d3ee] ${className}`}
        title="Validated from your uploaded CSV"
      >
        {MODE_LABELS.user_upload}
      </span>
    );
  }

  if (mode === 'planned') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border border-[#6366f1]/30 bg-[#6366f1]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#818cf8] ${className}`}
        title="No live result yet"
      >
        {MODE_LABELS.planned}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#f59e0b] ${className}`}
      title="Verified backend-generated snapshot — not live validation"
    >
      {MODE_LABELS.verified_snapshot}
    </span>
  );
}
