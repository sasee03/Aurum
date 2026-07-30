import { ApiError, calmApiMessage } from '@/utils/apiErrors';
import type { LiveTablePreview, ReviewGoldResponse } from '@/lib/aurumApi';

export function goldWorkflowError(error: unknown, fallback: string): { message: string; detail?: string } {
  if (error instanceof ApiError) {
    const detail = error.userMessage;
    if (detail.toLowerCase().includes('permission denied for schema gold')) {
      return {
        message: 'Gold could not prepare the result because the application does not have access to the configured Gold schema.',
        detail,
      };
    }
    if (detail === 'GOLD_DATABASE_UNAVAILABLE') {
      return {
        message: 'Gold could not reach the configured PostgreSQL runtime.',
        detail,
      };
    }
    if (detail === 'GOLD_UNAVAILABLE') {
      return {
        message: 'Gold authority is not configured in the local backend runtime.',
        detail,
      };
    }
    if (detail === 'GOLD_AI_UNAVAILABLE') {
      return {
        message: 'Gold structured interpretation is unavailable in this local backend runtime.',
        detail,
      };
    }
    return { message: detail || fallback, detail };
  }
  return { message: calmApiMessage(error, fallback) };
}

export function goldGenerateButtonLabel(generating: boolean, phase: string | null): string {
  return generating ? phase ?? 'Understanding requirement...' : 'Generate and Review';
}

export function canSubmitGoldGenerate({
  generating,
  selectedSilverTable,
  targetTableName,
  businessRequirement,
}: {
  generating: boolean;
  selectedSilverTable: string;
  targetTableName: string;
  businessRequirement: string;
}): boolean {
  return Boolean(
    !generating &&
    selectedSilverTable &&
    targetTableName.trim() &&
    businessRequirement.trim()
  );
}

export function humanizeGoldIdentifier(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'Gold Result';
  return value
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : part)
    .join(' ');
}

export function goldExpressionLabel(value: unknown): string {
  if (!value || typeof value !== 'object') return '—';
  const expression = value as Record<string, unknown>;
  if (expression.type === 'column' && typeof expression.column === 'string') {
    return expression.column;
  }
  if (
    expression.type === 'binary' &&
    typeof expression.left_column === 'string' &&
    typeof expression.right_column === 'string' &&
    typeof expression.operator === 'string'
  ) {
    const operators: Record<string, string> = {
      add: '+',
      subtract: '-',
      multiply: '*',
    };
    return `${expression.left_column} ${operators[expression.operator] ?? expression.operator} ${expression.right_column}`;
  }
  return JSON.stringify(value);
}

export function goldResultSummary(review: ReviewGoldResponse | null) {
  const changes = review?.planned_changes ?? {};
  const metric = changes.metric && typeof changes.metric === 'object'
    ? changes.metric as Record<string, unknown>
    : {};
  const dimension = typeof changes.dimension === 'string' ? changes.dimension : null;
  const alias = typeof metric.alias === 'string' ? metric.alias : null;
  const aggregation = typeof metric.aggregation === 'string' ? metric.aggregation.toUpperCase() : null;
  const calculation = goldExpressionLabel(metric.expression);

  return {
    title: alias && dimension
      ? `${humanizeGoldIdentifier(alias)} by ${humanizeGoldIdentifier(dimension)}`
      : alias
        ? humanizeGoldIdentifier(alias)
        : 'Gold Business Result',
    metric: alias ?? '—',
    groupedBy: dimension ?? '—',
    calculation,
    aggregation: aggregation ?? '—',
  };
}

export function promotedRelationFrom(response: { target?: Record<string, unknown> } | null): { schema: string; table: string } | null {
  const schema = response?.target?.schema;
  const table = response?.target?.table;
  if (typeof schema !== 'string' || typeof table !== 'string' || !schema || !table) {
    return null;
  }
  return { schema, table };
}

export function previewMatchesPromotedRelation(
  preview: Pick<LiveTablePreview, 'schema' | 'table'>,
  promoted: { schema: string; table: string },
): boolean {
  return preview.schema === promoted.schema && preview.table === promoted.table;
}

export function formattedGoldCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'NULL';
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

function numericValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function goldChartRows(
  preview: LiveTablePreview | null,
  metricAlias?: string | null,
): Array<{ label: string; value: number; widthPct: number }> {
  if (!preview || preview.columns.length < 2 || preview.rows.length === 0) return [];
  const labelColumn = preview.columns[0]?.name;
  const metricColumn = metricAlias && preview.columns.some((column) => column.name === metricAlias)
    ? metricAlias
    : preview.columns.find((column, index) => index > 0 && preview.rows.some((row) => numericValue(row[column.name]) !== null))?.name;
  if (!labelColumn || !metricColumn) return [];

  const rows = preview.rows
    .map((row) => ({
      label: formattedGoldCell(row[labelColumn]),
      value: numericValue(row[metricColumn]),
    }))
    .filter((row): row is { label: string; value: number } => row.value !== null)
    .slice(0, 8);
  const max = Math.max(...rows.map((row) => Math.abs(row.value)), 0);
  if (max <= 0) return [];
  return rows.map((row) => ({
    ...row,
    widthPct: Math.max(4, Math.round((Math.abs(row.value) / max) * 100)),
  }));
}
