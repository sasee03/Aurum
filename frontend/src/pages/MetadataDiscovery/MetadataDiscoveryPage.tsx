import { useState, useMemo, useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { ProgressMetric } from '@/components/common/ProgressMetric';
import { Heatmap } from '@/components/common/Heatmap';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { withRunIdQuery } from '@/hooks/useReport';
import { getMetadataTables, getMetadataTable } from '@/lib/aurumApi';
import { cn } from '@/utils/cn';

interface ColumnProfile {
  name: string;
  completeness: number;
}

interface TableProfile {
  tableId: string;
  tableName: string;
  schema: string;
  totalRows: string;
  columns: number;
  primaryKeys: number;
  pkColumns: string[];
  missingValuesPct: number;
  nullPct: number;
  uniquePct: number;
  columnsQuality: ColumnProfile[];
  nullDensityPattern: number[][];
}

/** Build a null density heatmap pattern from column null rates (fallback: zeros). */
function buildHeatmapPattern(columnStats: Record<string, unknown>[]): number[][] {
  const vals = columnStats.slice(0, 20).map((c) => {
    const rate = (c as Record<string, unknown>).null_rate;
    return typeof rate === 'number' ? Math.round(rate * 10) : 0;
  });
  const rows: number[][] = [];
  for (let i = 0; i < 4; i++) {
    rows.push(vals.slice(i * 5, i * 5 + 5).concat([0, 0, 0, 0, 0]).slice(0, 5));
  }
  return rows;
}

function toNumber(value: unknown, fallback = 0): number {
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
}

function toRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object')
    : [];
}

function toStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((entry) => toStringArray(entry));
  }
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return toStringArray(record.columns ?? record.column_names ?? record.name ?? record.column);
  }
  return [];
}

function primaryKeyColumns(table: Record<string, unknown>): string[] {
  const direct = toStringArray(
    table.pkColumns ?? table.pk_columns ?? table.primary_key_columns ?? table.primary_keys,
  );
  if (direct.length > 0) return direct;

  const candidateKeys = table.candidate_keys;
  if (Array.isArray(candidateKeys) && candidateKeys.length > 0) {
    return toStringArray(candidateKeys[0]);
  }
  return [];
}

/** Map the raw GET /metadata/tables/{name} response into a flat TableProfile. */
function toTableProfile(raw: Record<string, unknown>): TableProfile {
  const tables = toRecordArray(raw.tables);
  const t = (tables[0] ?? raw) as Record<string, unknown>;

  const schema = (t.schema as string | undefined) ?? '';
  const tableName = (t.table as string | undefined) ?? (t.name as string | undefined) ?? 'unknown';
  const tableId = `${schema}.${tableName}`;
  const rowCount = toNumber(t.row_count);
  const columnStats = toRecordArray(t.columns);
  const pkColumns = primaryKeyColumns(t);

  const columnsQuality: ColumnProfile[] = columnStats.map((c) => {
    const nullRate = toNumber(c.null_rate);
    return { name: String(c.name ?? c.column_name ?? 'unknown'), completeness: Math.round((1 - nullRate) * 100) };
  });

  const avgNullPct =
    columnStats.length > 0
      ? Math.round(
          (columnStats.reduce((sum, c) => sum + toNumber(c.null_rate), 0) / columnStats.length) *
            100,
        )
      : 0;

  return {
    tableId,
    tableName,
    schema,
    totalRows: rowCount.toLocaleString(),
    columns: columnStats.length || toNumber(t.column_count),
    primaryKeys: pkColumns.length,
    pkColumns,
    missingValuesPct: avgNullPct,
    nullPct: avgNullPct,
    uniquePct: 100 - avgNullPct,
    columnsQuality,
    nullDensityPattern: buildHeatmapPattern(columnStats),
  };
}

export function MetadataDiscoveryPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  const [tableNames, setTableNames] = useState<{ name: string; schema: string }[]>([]);
  const [profiles, setProfiles] = useState<Map<string, TableProfile>>(new Map());
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load table list on mount
  useEffect(() => {
    async function fetchTables() {
      setLoading(true);
      setError(null);
      try {
        const res = await getMetadataTables();
        const tables: { name: string; schema: string }[] = (res.tables ?? []).map(
          (t: Record<string, unknown>) => ({
            name: t.table as string,
            schema: t.schema as string,
          }),
        );
        setTableNames(tables);
        if (tables.length > 0) {
          setActiveTabId(`${tables[0].schema}.${tables[0].name}`);
        }
      } catch {
        setError('Could not load tables from GET /metadata/tables. Check the backend is running.');
      } finally {
        setLoading(false);
      }
    }
    fetchTables();
  }, []);

  // Load profile for active table whenever it changes
  useEffect(() => {
    if (!activeTabId) return;
    const entry = tableNames.find((t) => `${t.schema}.${t.name}` === activeTabId);
    if (!entry) return;
    if (profiles.has(activeTabId)) return; // already loaded

    async function fetchProfile() {
      setLoadingProfile(true);
      try {
        const raw = await getMetadataTable(entry!.name, entry!.schema);
        const profile = toTableProfile(raw as Record<string, unknown>);
        setProfiles((prev) => new Map(prev).set(activeTabId!, profile));
      } catch {
        // leave profile missing — show empty state for this table
      } finally {
        setLoadingProfile(false);
      }
    }
    fetchProfile();
  }, [activeTabId, tableNames, profiles]);

  const activeProfile = activeTabId ? profiles.get(activeTabId) : undefined;

  if (loading) {
    return (
      <div className="flex h-full flex-col overflow-hidden animate-fade-in">
        <ProjectSubNav runId={runId} />
        <div className="p-6">
          <LoadingSkeleton count={4} className="h-16" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col overflow-hidden animate-fade-in">
        <ProjectSubNav runId={runId} />
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
          <AlertTriangle size={32} className="text-[#f59e0b]" />
          <p className="text-sm text-[#94a3b8]">{error}</p>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (tableNames.length === 0) {
    return (
      <div className="flex h-full flex-col overflow-hidden animate-fade-in">
        <ProjectSubNav runId={runId} />
        <div className="flex flex-1 items-center justify-center text-[#6b7280]">
          No tables found in the connected database.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="validation" runId={runId} />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Metadata Discovery</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Auto-profiled from GET /metadata/tables — select a table to inspect.
          </p>

          {/* Table tabs */}
          <div className="flex gap-2 mt-6 flex-wrap">
            {tableNames.map((t) => {
              const tabId = `${t.schema}.${t.name}`;
              const isActive = activeTabId === tabId;
              return (
                <button
                  key={tabId}
                  onClick={() => setActiveTabId(tabId)}
                  className={cn(
                    'px-4 py-1.5 rounded-full text-xs font-semibold transition-all focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
                    isActive
                      ? 'bg-[#6366f1] text-white shadow-[0_4px_12px_rgba(99,102,241,0.3)]'
                      : 'border border-[#252637] text-[#94a3b8] hover:border-[#6366f1]/40 hover:text-[#f1f5f9]',
                  )}
                >
                  {t.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
          {loadingProfile ? (
            <LoadingSkeleton count={4} className="h-16" />
          ) : activeProfile ? (
            <>
              {/* Stats Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard label="Total Rows" value={activeProfile.totalRows} />
                <MetricCard label="Columns" value={activeProfile.columns} />
                <MetricCard
                  label="Primary Keys"
                  value={activeProfile.primaryKeys}
                  subValue={activeProfile.pkColumns.join(', ') || '—'}
                />
                <MetricCard label="Missing Values" value={`${activeProfile.missingValuesPct}%`} />
                <MetricCard label="Null %" value={`${activeProfile.nullPct}%`} />
                <MetricCard label="Unique %" value={`${activeProfile.uniquePct}%`} />
                <MetricCard label="Schema" value={activeProfile.schema} />
                <MetricCard label="Table" value={activeProfile.tableName} />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-6">
                {/* Column completeness */}
                {activeProfile.columnsQuality.length > 0 && (
                  <div className="rounded-xl border border-[#252637] bg-[#1a1b28]/30 p-5">
                    <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280] mb-5">
                      Column Completeness
                    </h3>
                    <div className="space-y-4">
                      {activeProfile.columnsQuality.slice(0, 12).map((col) => (
                        <ProgressMetric
                          key={col.name}
                          label={col.name}
                          percentage={col.completeness}
                          colorClass={
                            col.completeness === 100
                              ? 'bg-[#22c55e]'
                              : col.completeness > 90
                                ? 'bg-[#22c55e]/80'
                                : 'bg-[#f59e0b]'
                          }
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Null density heatmap */}
                <div className="rounded-xl border border-[#252637] bg-[#1a1b28]/30 p-5">
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280] mb-5">
                    Null Density Heatmap
                  </h3>
                  <div className="flex items-center justify-center h-[calc(100%-2rem)]">
                    <Heatmap pattern={activeProfile.nullDensityPattern} />
                  </div>
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-[#6b7280]">
              Loading profile for this table…
            </p>
          )}
        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => navigate(withRunIdQuery(`/projects/${id}/select`, runId))}
          >
            Back to Select
          </Button>
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            onClick={() =>
              navigate(withRunIdQuery(`/projects/${id}/validate/config`, runId))
            }
          >
            Configure Pipeline
          </Button>
        </div>
      </div>
    </div>
  );
}
