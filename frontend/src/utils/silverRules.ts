type ComparisonOperator = '=' | '!=' | '<>' | '<' | '<=' | '>' | '>=';

export type DeterministicSilverRule =
  | { type: 'not_null'; column: string }
  | { type: 'distinct' }
  | {
      type: 'compare';
      column: string;
      operator: ComparisonOperator;
      value: string | number | boolean;
    };

const FALLBACK_LIMIT = 160;

function boundedJson(value: object): string {
  try {
    const serialized = JSON.stringify(value);
    if (!serialized) return 'unreadable structured value';
    return serialized.length <= FALLBACK_LIMIT
      ? serialized
      : `${serialized.slice(0, FALLBACK_LIMIT - 1)}…`;
  } catch {
    return 'unreadable structured value';
  }
}

/** Format the exact deterministic Silver rule contract at the React boundary. */
export function formatSilverRule(rule: unknown): string {
  if (typeof rule === 'string') return rule;
  if (rule === null || rule === undefined) return '';
  if (typeof rule !== 'object') return String(rule);

  const structured = rule as Record<string, unknown>;
  if (
    structured.type === 'not_null' &&
    typeof structured.column === 'string'
  ) {
    return `${structured.column} is not null`;
  }
  if (structured.type === 'distinct') {
    return 'Remove exact duplicate rows';
  }
  if (
    structured.type === 'compare' &&
    typeof structured.column === 'string' &&
    typeof structured.operator === 'string' &&
    ['=', '!=', '<>', '<', '<=', '>', '>='].includes(structured.operator) &&
    ['string', 'number', 'boolean'].includes(typeof structured.value)
  ) {
    const displayedValue =
      typeof structured.value === 'string'
        ? JSON.stringify(structured.value)
        : String(structured.value);
    return `${structured.column} ${structured.operator} ${displayedValue}`;
  }

  return `Unsupported rule: ${boundedJson(structured)}`;
}

function parseComparisonValue(raw: string): string | number | boolean {
  if (raw.startsWith('"') && raw.endsWith('"')) {
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed === 'string') return parsed;
    } catch {
      return raw.slice(1, -1);
    }
  }
  if (raw.startsWith("'") && raw.endsWith("'")) {
    return raw.slice(1, -1);
  }
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  if (/^-?(?:\d+|\d*\.\d+)$/.test(raw)) return Number(raw);
  return raw;
}

/** Convert the editable presentation string back to the deterministic API contract. */
export function parseSilverRuleInput(input: string): DeterministicSilverRule {
  const normalized = input.trim();
  if (
    normalized.toLowerCase() === 'distinct' ||
    normalized.toLowerCase().includes('duplicate')
  ) {
    return { type: 'distinct' };
  }

  const notNullMatch = normalized.match(
    /^(?:not_null\((.+)\)|(.+?)\s+is\s+not\s+null)$/i,
  );
  if (notNullMatch) {
    return {
      type: 'not_null',
      column: (notNullMatch[1] || notNullMatch[2]).trim(),
    };
  }

  const comparisonMatch = normalized.match(
    /^([a-zA-Z_][a-zA-Z0-9_]*)\s*(<=|>=|!=|<>|=|<|>)\s*(.+)$/,
  );
  if (comparisonMatch) {
    return {
      type: 'compare',
      column: comparisonMatch[1],
      operator: comparisonMatch[2] as ComparisonOperator,
      value: parseComparisonValue(comparisonMatch[3].trim()),
    };
  }

  return { type: 'not_null', column: normalized };
}
