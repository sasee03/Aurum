import { formatRelationName } from '@/utils/relationPresentation';

export type TableClassification = 'source' | 'pipeline' | 'internal';

export function classifyTable(schema: string, name: string, owner: string): TableClassification {
  const schemaLower = schema.toLowerCase();
  const nameLower = name.toLowerCase();
  const ownerLower = owner.toLowerCase();

  if (
    schemaLower.startsWith('aurum_session_') ||
    schemaLower.endsWith('_candidates') ||
    nameLower.endsWith('_candidates')
  ) return 'internal';
  
  if (['bronze', 'silver', 'gold', 'gold_candidates', 'silver_candidates'].includes(ownerLower)) return 'pipeline';
  
  if (schemaLower.startsWith('bronze') || schemaLower.startsWith('silver') || schemaLower.startsWith('gold')) return 'pipeline';
  
  if (nameLower.startsWith('bronze_') || nameLower.startsWith('silver_') || nameLower.startsWith('gold_')) return 'pipeline';
  
  if (ownerLower === 'internal' || schemaLower === 'information_schema' || schemaLower === 'pg_catalog') return 'internal';
  
  return 'source';
}

export function formatFriendlyName(name: string): string {
  return formatRelationName(name.replace(/^(bronze|silver|gold)_/i, ''));
}
