interface Props {
  title?: string;
  detail: string;
}

export function PlannedBanner({
  title = 'Coming in a future release',
  detail,
}: Props) {
  return (
    <div className="rounded-lg border border-[#f59e0b]/30 bg-[#f59e0b]/5 px-4 py-3 text-sm text-[#fbbf24]">
      <strong className="text-[#f59e0b]">{title}</strong>
      <p className="mt-1 text-[#94a3b8]">{detail}</p>
    </div>
  );
}
