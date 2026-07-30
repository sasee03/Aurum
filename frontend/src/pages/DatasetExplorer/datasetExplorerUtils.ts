export type TableClassification = 'source' | 'pipeline' | 'internal';

export function classifyTable(schema: string, name: string, owner: string): TableClassification {
  const schemaLower = schema.toLowerCase();
  const nameLower = name.toLowerCase();
  const ownerLower = owner.toLowerCase();

  if (schemaLower.startsWith('aurum_session_')) return 'internal';
  
  if (['bronze', 'silver', 'gold', 'gold_candidates', 'silver_candidates'].includes(ownerLower)) return 'pipeline';
  
  if (schemaLower.startsWith('bronze') || schemaLower.startsWith('silver') || schemaLower.startsWith('gold')) return 'pipeline';
  
  if (nameLower.startsWith('bronze_') || nameLower.startsWith('silver_') || nameLower.startsWith('gold_')) return 'pipeline';
  
  if (ownerLower === 'internal' || schemaLower === 'information_schema' || schemaLower === 'pg_catalog') return 'internal';
  
  return 'source';
}

export function formatFriendlyName(name: string): string {
  let cleanName = name;
  let suffix = '';

  const prefixMatch = /^(src|bronze|silver|gold)_/i.exec(cleanName);
  if (prefixMatch) {
    const prefix = prefixMatch[1].toLowerCase();
    cleanName = cleanName.substring(prefixMatch[0].length);
    if (prefix === 'bronze') suffix = ' — Bronze';
    if (prefix === 'silver') suffix = ' — Silver';
    if (prefix === 'gold') suffix = ' — Gold';
  }

  cleanName = cleanName.replace(/[_-]+/g, ' ').trim();

  const acronyms = new Set(['UCI', 'ID', 'SKU', 'KPI', 'SQL']);
  const words = cleanName.split(' ').map((w) => {
    if (!w) return '';
    const upper = w.toUpperCase();
    if (acronyms.has(upper)) return upper;
    return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
  });

  return words.join(' ') + suffix;
}
