const ACRONYMS = new Set(['UCI', 'ID', 'SKU', 'KPI', 'SQL']);

/** Human-readable presentation for a physical relation name; it never renames the database object. */
export function formatRelationName(name: string): string {
  const withoutSourcePrefix = name.replace(/^src_/i, '');
  const words = withoutSourcePrefix
    .replace(/[_-]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase();
      return ACRONYMS.has(upper)
        ? upper
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    });

  return words.join(' ');
}
