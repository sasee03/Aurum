import { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, ChevronDown, ArrowRight, CheckSquare, Square, Eye, AlertTriangle } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { SearchBar } from '@/components/common/SearchBar';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { withRunIdQuery } from '@/hooks/useReport';
import { cn } from '@/utils/cn';
import { calmApiMessage } from '@/utils/apiErrors';
import {
  readRelationSelection,
  relationSelectionKey,
  withRelationSelectionQuery,
} from '@/utils/relationSelection';
import { withConnectorFlowQuery } from '@/utils/connectorFlow';
import {
  getMetadataTables,
  getLiveTablePreview,
  listPostgresSchemas,
  listPostgresTables,
  previewPostgresTable,
  type PostgresTableEntry,
} from '@/lib/aurumApi';

interface DbTable {
  id: string;
  schema: string;
  name: string;
  owner: string;
  rows: string;
  columns: number;
  size: string;
  lastUpdated: string;
}

interface SchemaNode {
  name: string;
  tables: DbTable[];
}

interface TablePreviewColumn {
  name: string;
  data_type: string;
  nullable?: boolean;
}

interface TablePreview {
  schema: string;
  table: string;
  rowCount: number | null;
  columnCount: number | null;
  columns: TablePreviewColumn[];
  rows: Record<string, unknown>[];
}

function SchemaTree({
  schemas,
  selectedIds,
  onToggle,
}: {
  schemas: SchemaNode[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(
    new Set(schemas.map((s) => s.name))
  );

  useEffect(() => {
    setExpandedSchemas(new Set(schemas.map((schema) => schema.name)));
  }, [schemas]);

  function toggleSchema(name: string) {
    setExpandedSchemas((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  return (
    <div className="space-y-1">
      {schemas.map((schema) => (
        <div key={schema.name}>
          <button
            onClick={() => toggleSchema(schema.name)}
            className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold text-[#6b7280] hover:bg-[#1a1b28] hover:text-[#94a3b8] transition-colors focus:outline-none focus:ring-1 focus:ring-[#6366f1]"
            aria-expanded={expandedSchemas.has(schema.name)}
          >
            {expandedSchemas.has(schema.name) ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )}
            {schema.name}
          </button>
          {expandedSchemas.has(schema.name) && (
            <div className="ml-3 space-y-0.5 border-l border-[#252637] pl-3">
              {schema.tables.length === 0 ? (
                <p className="px-2 py-1 text-[11px] text-[#4b5563]">No tables</p>
              ) : (
                schema.tables.map((table) => (
                  <button
                    key={table.id}
                    onClick={() => onToggle(table.id)}
                    className={cn(
                      'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-[#6366f1]',
                      selectedIds.has(table.id)
                        ? 'text-[#6366f1] bg-[#6366f1]/10'
                        : 'text-[#6b7280] hover:bg-[#1a1b28] hover:text-[#94a3b8]'
                    )}
                  >
                    <ChevronRight size={10} className="opacity-50" />
                    {table.name}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function TableRowCard({
  table,
  selected,
  previewing,
  onToggle,
  onPreview,
}: {
  table: DbTable;
  selected: boolean;
  previewing: boolean;
  onToggle: () => void;
  onPreview: () => void;
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-4 border-b border-[#252637] px-4 py-3 transition-all duration-150 cursor-pointer group',
        selected ? 'bg-[#6366f1]/5' : 'hover:bg-[#1a1b28]'
      )}
      onClick={onToggle}
      role="row"
      aria-selected={selected}
    >
      <div className="flex-shrink-0">
        {selected ? (
          <CheckSquare size={16} className="text-[#6366f1]" />
        ) : (
          <Square size={16} className="text-[#4b5563] group-hover:text-[#6b7280]" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p className={cn('text-sm font-semibold truncate', selected ? 'text-[#6366f1]' : 'text-[#f1f5f9]')}>
          {table.name}
        </p>
        <p className="text-[11px] text-[#4b5563]">
          {table.owner} · {table.lastUpdated}
        </p>
      </div>

      <div className="hidden sm:flex items-center gap-6 text-right flex-shrink-0">
        <div>
          <p className="text-xs font-semibold text-[#f1f5f9]">{table.rows}</p>
          <p className="text-[10px] text-[#4b5563]">rows</p>
        </div>
        <div>
          <p className="text-xs font-semibold text-[#f1f5f9]">{table.columns}</p>
          <p className="text-[10px] text-[#4b5563]">cols</p>
        </div>
        <div>
          <p className="text-xs font-semibold text-[#f1f5f9]">{table.size}</p>
          <p className="text-[10px] text-[#4b5563]">size</p>
        </div>
      </div>

      <div className="flex-shrink-0 ml-4">
        <Button 
          variant="ghost" 
          size="sm" 
          leftIcon={<Eye size={14} />} 
          isLoading={previewing}
          onClick={(e) => { e.stopPropagation(); onPreview(); }}
        >
          {previewing ? 'Loading' : 'Preview'}
        </Button>
      </div>
    </div>
  );
}

export function DatasetExplorerPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const connectionId = searchParams.get('connectionId') ?? undefined;
  const databaseName = searchParams.get('database') ?? undefined;
  const connectionSession = searchParams.get('session') ?? undefined;
  const requestedSchema = searchParams.get('schema');
  const requestedTable = searchParams.get('table');
  const requestedRelation = readRelationSelection(searchParams);
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  
  const [allSchemas, setAllSchemas] = useState<SchemaNode[]>([]);
  const [allTables, setAllTables] = useState<DbTable[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [previewingTableId, setPreviewingTableId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setAllSchemas([]);
    setAllTables([]);
    try {
      if (connectionId) {
        const schemaRes = await listPostgresSchemas(connectionId);
        const tableResponses = await Promise.all(
          schemaRes.schemas.map((schema) => listPostgresTables(connectionId, schema)),
        );
        const postgresTables = tableResponses.flatMap((response) => response.tables);
        const formattedTables = postgresTables.map((table: PostgresTableEntry): DbTable => ({
          id: relationSelectionKey(table.schema, table.table),
          schema: table.schema,
          name: table.table,
          owner: table.layer === 'unknown' ? 'postgresql' : table.layer,
          rows: table.row_count !== undefined && table.row_count !== null ? table.row_count.toString() : '-',
          columns: table.column_count || 0,
          size: '-',
          lastUpdated: 'live',
        }));
        const tablesBySchema = new Map<string, DbTable[]>();
        for (const schema of schemaRes.schemas) tablesBySchema.set(schema, []);
        for (const table of formattedTables) tablesBySchema.get(table.schema)?.push(table);

        setAllSchemas(Array.from(tablesBySchema, ([name, tables]) => ({ name, tables })));
        setAllTables(formattedTables);
        return;
      }

      const res = await getMetadataTables();
      const tables = res.tables || [];
      
      const schemaMap = new Map<string, DbTable[]>();
      const formattedTables: DbTable[] = [];
      
      for (const t of tables) {
        const dbT: DbTable = {
          id: relationSelectionKey(t.schema, t.table),
          schema: t.schema,
          name: t.table,
          owner: t.layer ?? 'postgresql',
          rows: t.row_count?.toString() || '0',
          columns: t.column_count || 0,
          size: '-',
          lastUpdated: '—',
        };
        formattedTables.push(dbT);
        
        if (!schemaMap.has(t.schema)) {
          schemaMap.set(t.schema, []);
        }
        schemaMap.get(t.schema)!.push(dbT);
      }
      
      const schemas: SchemaNode[] = Array.from(schemaMap.entries()).map(([name, tables]) => ({
        name,
        tables
      }));
      
      setAllSchemas(schemas);
      setAllTables(formattedTables);
    } catch (err) {
      setAllSchemas([]);
      setAllTables([]);
      setError(
        calmApiMessage(
          err,
          connectionId
            ? 'Could not load tables from this PostgreSQL connection. Re-test the connection and try again.'
            : 'Could not load live PostgreSQL metadata. Check the backend and database, then retry.',
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [connectionId, connectionSession]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (!requestedSchema || !requestedTable || allTables.length === 0) return;
    const requestedId = relationSelectionKey(
      requestedSchema,
      requestedTable,
    );
    if (!allTables.some((table) => table.id === requestedId)) return;
    setSelectedIds((current) =>
      current.size === 0 ? new Set([requestedId]) : current,
    );
  }, [
    allTables,
    requestedSchema,
    requestedTable,
  ]);

  const filteredTables = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return allTables;
    return allTables.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.owner.toLowerCase().includes(q) ||
        t.schema.toLowerCase().includes(q)
    );
  }, [search, allTables]);

  function persistSingleSelection(nextSelection: Set<string>) {
    const nextParams = new URLSearchParams(searchParams);
    if (nextSelection.size === 1) {
      const selectedId = Array.from(nextSelection)[0];
      const selectedTable = allTables.find((table) => table.id === selectedId);
      if (selectedTable) {
        nextParams.set('schema', selectedTable.schema);
        nextParams.set('table', selectedTable.name);
      }
    } else {
      nextParams.delete('schema');
      nextParams.delete('table');
    }
    setSearchParams(nextParams, { replace: true });
  }

  function toggleTable(tableId: string) {
    const next = new Set(selectedIds);
    if (next.has(tableId)) next.delete(tableId);
    else next.add(tableId);
    setSelectedIds(next);
    persistSingleSelection(next);
  }

  function selectAll() {
    const next = new Set(filteredTables.map((t) => t.id));
    setSelectedIds(next);
    persistSingleSelection(next);
  }

  function deselectAll() {
    const next = new Set<string>();
    setSelectedIds(next);
    persistSingleSelection(next);
  }

  async function handlePreview(table: DbTable) {
    try {
      setPreviewingTableId(table.id);
      toast.loading(`Fetching preview for ${table.name}...`, { id: 'preview' });
      let nextPreview: TablePreview | null = null;
      if (connectionId) {
        const tablePreview = await previewPostgresTable(connectionId, table.schema, table.name);
        nextPreview = {
          schema: tablePreview.schema,
          table: tablePreview.table,
          rowCount: tablePreview.metadata.row_count,
          columnCount: tablePreview.metadata.column_count,
          columns: tablePreview.metadata.columns,
          rows: tablePreview.data,
        };
        setAllTables((current) =>
          current.map((entry) =>
            entry.id === table.id
              ? {
                  ...entry,
                  rows: tablePreview.metadata.row_count.toLocaleString(),
                  columns: tablePreview.metadata.column_count,
                }
              : entry,
          ),
        );
      } else {
        const tablePreview = await getLiveTablePreview(table.name, table.schema);
        nextPreview = {
          schema: tablePreview.schema,
          table: tablePreview.table,
          rowCount: tablePreview.row_count,
          columnCount: tablePreview.column_count,
          columns: tablePreview.columns,
          rows: tablePreview.rows,
        };
      }
      if (nextPreview) {
        setPreview(nextPreview);
        toast.success('Preview loaded', { id: 'preview', duration: 1500 });
      } else {
        toast.error('No preview metadata returned', { id: 'preview' });
      }
    } catch (err) {
      toast.error(calmApiMessage(err, 'Failed to load table preview.'), { id: 'preview' });
    } finally {
      setPreviewingTableId(null);
    }
  }

  const selectedTables = allTables.filter((t) => selectedIds.has(t.id));
  const selectedRelation = selectedTables[0];
  const requestedRelationMissing = Boolean(
    requestedRelation &&
      !loading &&
      !allTables.some(
        (table) =>
          table.schema === requestedRelation.schema &&
          table.name === requestedRelation.table,
      ),
  );
  const hasAnyTables = allTables.length > 0;
  const hasResults = filteredTables.length > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav runId={runId} />

      <div className="flex flex-1 overflow-hidden">
        <aside
          className="w-48 flex-shrink-0 border-r border-[#252637] bg-[#0d0e14] overflow-y-auto scrollbar-thin p-3"
          aria-label="Database schema tree"
        >
          <p className="mb-2 px-2 text-[10px] font-bold uppercase tracking-widest text-[#4b5563]">
            {connectionId && databaseName
              ? `${databaseName} / schemas`
              : 'LIVE SCHEMAS'}
          </p>
          <SchemaTree schemas={allSchemas} selectedIds={selectedIds} onToggle={toggleTable} />
        </aside>

        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="border-b border-[#252637] px-6 py-4">
            <h2 className="text-lg font-bold text-[#f1f5f9]">Dataset Explorer</h2>
            <p className="text-xs text-[#6b7280]">Select a relation for AURUM to inspect in this run.</p>
            {requestedRelationMissing && (
              <p className="mt-2 text-xs text-[#f59e0b]">
                Previously selected relation{' '}
                <span className="font-mono">
                  {requestedRelation?.schema}.{requestedRelation?.table}
                </span>{' '}
                is no longer available. Choose another relation below.
              </p>
            )}
          </div>

          <div className="flex items-center gap-3 px-6 py-3 border-b border-[#252637]">
            <SearchBar
              value={search}
              onChange={setSearch}
              placeholder="Search tables..."
              className="flex-1"
            />
            <button
              onClick={selectAll}
              className="text-xs text-[#6366f1] hover:text-[#4f46e5] transition-colors whitespace-nowrap focus:outline-none focus:underline"
              aria-label="Select all tables"
            >
              Select All
            </button>
            <button
              onClick={deselectAll}
              className="text-xs text-[#6b7280] hover:text-[#94a3b8] transition-colors whitespace-nowrap focus:outline-none focus:underline"
              aria-label="Deselect all tables"
            >
              Deselect All
            </button>
          </div>

          <div
            className="flex-1 overflow-y-auto scrollbar-thin relative"
            role="table"
            aria-label="Available tables"
          >
            {loading ? (
              <div className="flex items-center justify-center h-full text-[#6b7280]">
                Loading live tables...
              </div>
            ) : error ? (
              <div className="flex flex-col items-center justify-center h-full">
                <p className="text-sm font-semibold text-red-500 mb-2">{error}</p>
                <p className="text-xs text-[#6b7280] mb-4">
                  Attempted:{' '}
                  <code className="font-mono bg-[#1a1b28] px-1 py-0.5 rounded">
                    {connectionId
                      ? 'GET /connectors/postgres/schemas and /tables'
                      : 'GET /metadata/tables'}
                  </code>
                </p>
                <p className="text-xs text-[#6b7280] mb-4 text-center">
                  {connectionId
                    ? 'Connection passwords are not stored, so an expired session must be tested again.'
                    : 'Check that the backend and PostgreSQL are running.'}
                </p>
                <div className="flex gap-3">
                  <Button variant="secondary" size="sm" onClick={loadData}>
                    Retry
                  </Button>
                  {connectionId && (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => navigate(`/projects/${id}/connect?source=postgresql`)}
                    >
                      Re-test Connection
                    </Button>
                  )}
                </div>
              </div>
            ) : hasResults ? (
              filteredTables.map((table) => (
                <TableRowCard
                  key={table.id}
                  table={table}
                  selected={selectedIds.has(table.id)}
                  previewing={previewingTableId === table.id}
                  onToggle={() => toggleTable(table.id)}
                  onPreview={() => handlePreview(table)}
                />
              ))
            ) : !hasAnyTables ? (
              <div className="flex h-full flex-col items-center justify-center px-6 py-16 text-center">
                <div className="max-w-xl rounded-xl border border-[#252637] bg-[#13141e] p-6">
                  <AlertTriangle size={28} className="mx-auto mb-4 text-[#f59e0b]" />
                  <h3 className="text-base font-semibold text-[#f1f5f9]">
                    {connectionId
                      ? 'No tables found in this PostgreSQL connection'
                      : 'No tables found in the public schema'}
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-[#94a3b8]">
                    {connectionId
                      ? 'This connection is live, but Aurum could not find visible tables in the schemas it can access.'
                      : "If you've uploaded a CSV or validated a connected table, that data lives in a temporary session and won't appear here. Check Run History for those results. To explore a live table, connect to your database via Connectors and ensure it has permanent tables in a visible schema."}
                  </p>
                  <div className="mt-5 flex flex-wrap justify-center gap-3">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => navigate(`/projects/${id}/connect?source=postgresql`)}
                    >
                      Open Connectors
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => navigate('/history')}>
                      Run History
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <p className="text-sm text-[#6b7280]">No tables match "{search}"</p>
                <button
                  onClick={() => setSearch('')}
                  className="mt-2 text-xs text-[#6366f1] hover:underline focus:outline-none"
                >
                  Clear search
                </button>
              </div>
            )}
          </div>

          {selectedIds.size > 0 && (
            <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-3 flex items-center justify-between gap-4 animate-slide-up">
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                <span className="text-sm font-semibold text-[#f1f5f9] whitespace-nowrap">
                  {selectedIds.size} table{selectedIds.size !== 1 ? 's' : ''} selected
                </span>
                <span className="text-[#4b5563]">·</span>
                <div className="flex flex-wrap gap-1.5">
                  {selectedTables.slice(0, 4).map((t) => (
                    <span
                      key={t.id}
                      className="text-xs text-[#6366f1] font-medium"
                    >
                      {t.schema}.{t.name}
                    </span>
                  ))}
                  {selectedTables.length > 4 && (
                    <span className="text-xs text-[#6b7280]">
                      +{selectedTables.length - 4} more
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                rightIcon={<ArrowRight size={14} />}
                onClick={() => {
                  if (!selectedRelation) return;
                  const bronzePath = withRunIdQuery(`/projects/${id}/bronze`, runId);
                  const connectorPath = withConnectorFlowQuery(bronzePath, searchParams);
                  navigate(
                    withRelationSelectionQuery(
                      connectorPath,
                      {
                        schema: selectedRelation.schema,
                        table: selectedRelation.name,
                      },
                    ),
                  );
                }}
                className="flex-shrink-0"
              >
                Continue to Bronze
              </Button>
            </div>
          )}
        </div>
      </div>

      <Dialog
        open={Boolean(preview)}
        onClose={() => setPreview(null)}
        title={preview ? `${preview.schema}.${preview.table}` : 'Table preview'}
        description={
          preview
            ? `${preview.rowCount?.toLocaleString() ?? 'Unknown'} rows, ${preview.columnCount?.toLocaleString() ?? preview.columns.length} columns`
            : undefined
        }
        className="max-h-[85vh] max-w-5xl overflow-hidden"
      >
        {preview && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-[#252637] bg-[#0d0e14] px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Rows</p>
                <p className="mt-1 text-sm font-semibold text-[#f1f5f9]">
                  {preview.rowCount?.toLocaleString() ?? 'Unknown'}
                </p>
              </div>
              <div className="rounded-lg border border-[#252637] bg-[#0d0e14] px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Columns</p>
                <p className="mt-1 text-sm font-semibold text-[#f1f5f9]">
                  {preview.columnCount?.toLocaleString() ?? preview.columns.length}
                </p>
              </div>
              <div className="rounded-lg border border-[#252637] bg-[#0d0e14] px-3 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-[#6b7280]">Sample</p>
                <p className="mt-1 text-sm font-semibold text-[#f1f5f9]">
                  {preview.rows.length.toLocaleString()} row{preview.rows.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>

            <div className="max-h-[46vh] overflow-auto rounded-lg border border-[#252637] scrollbar-thin">
              {preview.columns.length > 0 && preview.rows.length > 0 ? (
                <table className="w-full min-w-max text-left text-xs">
                  <thead className="sticky top-0 bg-[#13141e] text-[#94a3b8]">
                    <tr>
                      {preview.columns.map((column) => (
                        <th key={column.name} className="border-b border-r border-[#252637] px-3 py-2 align-top last:border-r-0">
                          <span className="block font-semibold text-[#f1f5f9]">{column.name}</span>
                          <span className="mt-0.5 block text-[10px] font-normal text-[#6b7280]">
                            {column.data_type}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#252637]">
                    {preview.rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className="hover:bg-[#252637]/30">
                        {preview.columns.map((column) => {
                          const value = row[column.name];
                          return (
                            <td key={column.name} className="max-w-64 border-r border-[#252637] px-3 py-2 text-[#d1d5db] last:border-r-0">
                              {value === null || value === undefined ? (
                                <span className="italic text-[#6b7280]">NULL</span>
                              ) : (
                                <span className="block truncate" title={String(value)}>
                                  {String(value)}
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : preview.columns.length > 0 ? (
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#13141e] text-[#94a3b8]">
                    <tr>
                      <th className="border-b border-[#252637] px-3 py-2">Column</th>
                      <th className="border-b border-[#252637] px-3 py-2">Type</th>
                      <th className="border-b border-[#252637] px-3 py-2">Nullable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#252637]">
                    {preview.columns.map((column) => (
                      <tr key={column.name}>
                        <td className="px-3 py-2 font-medium text-[#f1f5f9]">{column.name}</td>
                        <td className="px-3 py-2 text-[#94a3b8]">{column.data_type}</td>
                        <td className="px-3 py-2 text-[#94a3b8]">
                          {column.nullable === undefined ? '-' : column.nullable ? 'Yes' : 'No'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="px-4 py-8 text-center text-sm text-[#6b7280]">
                  No preview rows or column metadata returned.
                </div>
              )}
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
