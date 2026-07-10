/** Shared friendly labels for validation run modes — keep UI copy consistent. */

export function runSourceLabel(mode: string): string {
  switch (mode) {
    case 'upload':
      return 'Uploaded file';
    case 'connector':
      return 'Database connection';
    case 'demo':
      return 'Sample dataset';
    case 'live':
      return 'Live validation';
    default:
      return 'Validation';
  }
}

export function formatRelativeOrDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const delta = Date.now() - ms;
  const sec = Math.round(delta / 1000);
  if (sec < 45) return 'Just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
  const day = Math.round(hr / 24);
  if (day < 14) return `${day} day${day === 1 ? '' : 's'} ago`;
  return new Date(ms).toLocaleString();
}
