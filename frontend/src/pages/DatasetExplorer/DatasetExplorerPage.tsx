import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronRight, ChevronDown, ArrowRight, CheckSquare, Square, Eye, AlertTriangle, Database } from 'lucide-react';
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
import { classifyTable, formatFriendlyName } from './datasetExplorerUtils';
import {
  isCurrentDatasetDiscovery,
  reconcileDatasetSelection,
} from './datasetExplorerState';

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
            className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold text-[#94a3b8] hover:bg-[#131a29] hover:text-[#f8fafc] transition-colors focus:outline-none focus:ring-1 focus:ring-[#3b82f6] cursor-pointer"
            aria-expanded={expandedSchemas.has(schema.name)}
          >
            {expandedSchemas.has(schema.name) ? (
              <ChevronDown size={12} className="text-[#3b82f6]" />
            ) : (
              <ChevronRight size={12} className="text-[#64748b]" />
            )}
            <span className="truncate">{schema.name}</span>
          </button>
          {expandedSchemas.has(schema.name) && (
            <div className="ml-3 space-y-0.5 border-l border-[#1e293b] pl-2.5">
              {schema.tables.length === 0 ? (
                <p className="px-2 py-1 text-[11px] text-[#64748b]">No tables</p>
              ) : (
                schema.tables.map((table) => (
                  <button
                    key={table.id}
                    onClick={() => onToggle(table.id)}
                    className={cn(
                      'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors focus:outline-none focus:ring-1 focus:ring-[#3b82f6] cursor-pointer',
                      selectedIds.has(table.id)
                        ? 'text-[#3b82f6] bg-[#2563eb]/15 font-semibold'
                        : 'text-[#94a3b8] hover:bg-[#131a29] hover:text-[#f8fafc]'
                    )}
                  >
                    <ChevronRight size={10} className="opacity-50 shrink-0" />
                    <span className="truncate">{table.name}</span>
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
  onUse,
  isInternal,
}: {
  table: DbTable;
  selected: boolean;
  previewing: boolean;
  onToggle: () => void;
  onPreview: () => void;
  onUse?: () => void;
  isInternal?: boolean;
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-4 border-b border-[#1e293b] px-5 py-3.5 transition-all duration-150 cursor-pointer group select-none',
        selected ? 'bg-[#2563eb]/10' : 'hover:bg-[#131a29]'
      )}
      onClick={isInternal ? undefined : onToggle}
      role="row"
      aria-selected={selected}
    >
      <div className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
        {!isInternal && (
          selected ? (
            <CheckSquare size={18} className="text-[#3b82f6]" />
          ) : (
            <Square size={18} className="text-[#64748b] group-hover:text-[#94a3b8]" />
          )
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className={cn('text-sm font-semibold truncate', selected ? 'text-[#3b82f6]' : 'text-[#f8fafc]')}>
            {formatFriendlyName(table.name)}
          </p>
        </div>
        <p className="text-[11px] text-[#64748b] mt-0.5">
          <span className="font-mono text-[#06b6d4]">{table.schema}.{table.name}</span>
          {table.owner !== 'postgresql' ? ` \u00B7 ${table.owner}` : ''}
        </p>
      </div>

      <div className="flex gap-6 text-center shrink-0">
        <div>
          <p className="text-xs font-semibold text-[#f8fafc]">{table.rows}</p>
          <p className="text-[10px] text-[#64748b]">rows</p>
        </div>
        <div>
          <p className="text-xs font-semibold text-[#f8fafc]">{table.columns > 0 ? table.columns : '—'}</p>
          <p className="text-[10px] text-[#64748b]">cols</p>
        </div>
      </div>

      <div className="flex-shrink-0 ml-4 flex items-center gap-2">
        <Button 
          variant="ghost" 
          size="sm" 
          leftIcon={<Eye size={14} />} 
          isLoading={previewing}
          onClick={(e) => { e.stopPropagation(); onPreview(); }}
        >
          {previewing ? 'Loading' : 'Preview'}
        </Button>
        {!isInternal && onUse && (
          <Button
            variant="primary"
            size="sm"
            onClick={(e) => { e.stopPropagation(); onUse(); }}
            className="text-xs"
          >
            Use this dataset
          </Button>
        )}
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
  const [showInternal, setShowInternal] = useState(false);
  const discoveryContextKey = [connectionId ?? '', databaseName ?? ''].join('\u0000');
  const discoveryRequestRef = useRef(0);
  const discoveryContextRef = useRef(discoveryContextKey);
  discoveryContextRef.current = discoveryContextKey;

  const loadData = useCallback(async () => {
    const requestId = ++discoveryRequestRef.current;
    const requestContext = discoveryContextKey;
    setLoading(true);
    setError(null);
    setAllSchemas([]);
    setAllTables([]);
    setSelectedIds(new Set());
    setPreview(null);
    setPreviewingTableId(null);
    try {
      if (connectionId) {
        const schemaRes = await listPostgresSchemas(connectionId);
        const tableResponses = await Promise.all(
          schemaRes.schemas.map((schema) => listPostgresTables(connectionId, schema)),
        );
        if (
          !isCurrentDatasetDiscovery(requestId, discoveryRequestRef.current) ||
          discoveryContextRef.current !== requestContext
        ) return;
        const postgresTables = tableResponses.flatMap((response) => response.tables);
        const formattedTables = postgresTables.map((table: PostgresTableEntry): DbTable => ({
          id: relationSelectionKey(table.schema, table.table),
          schema: table.schema,
          name: table.table,
          owner: table.layer === 'unknown' ? 'postgresql' : table.layer,
          rows: '—',
          columns: 0,
          size: '—',
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
      if (
        !isCurrentDatasetDiscovery(requestId, discoveryRequestRef.current) ||
        discoveryContextRef.current !== requestContext
      ) return;
      const tables = res.tables || [];
      
      const schemaMap = new Map<string, DbTable[]>();
      const formattedTables: DbTable[] = [];
      
      for (const t of tables) {
        const dbT: DbTable = {
          id: relationSelectionKey(t.schema, t.table),
          schema: t.schema,
          name: t.table,
          owner: t.layer ?? 'postgresql',
          rows: t.row_count != null ? t.row_count.toLocaleString() : '—',
          columns: t.column_count || 0,
          size: '—',
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
      if (
        !isCurrentDatasetDiscovery(requestId, discoveryRequestRef.current) ||
        discoveryContextRef.current !== requestContext
      ) return;
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
      if (
        isCurrentDatasetDiscovery(requestId, discoveryRequestRef.current) &&
        discoveryContextRef.current === requestContext
      ) {
        setLoading(false);
      }
    }
  }, [connectionId, discoveryContextKey]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const hasAutoSelectedRef = useRef(false);

  useEffect(() => {
    setSelectedIds(new Set());
    setPreview(null);
    hasAutoSelectedRef.current = false;
  }, [connectionId, databaseName, id]);

  useEffect(() => {
    if (connectionSession && !hasAutoSelectedRef.current && allTables.length > 0) {
      const parts = connectionSession.split('.');
      if (parts.length === 2) {
        const [schema, name] = parts;
        const target = allTables.find((t) => t.schema === schema && t.name === name);
        if (target) {
          const classification = classifyTable(target.schema, target.name, target.owner);
          if (classification !== 'internal') {
            setSelectedIds(new Set([target.id]));
            hasAutoSelectedRef.current = true;
          }
        }
      }
    }
  }, [connectionId, connectionSession, allTables]);

  useEffect(() => {
    const reconciled = reconcileDatasetSelection(selectedIds, allTables);
    if (reconciled.size === selectedIds.size) return;
    setSelectedIds(reconciled);
    setPreview(null);
  }, [allTables, selectedIds]);

  useEffect(() => {
    if (!requestedSchema || !requestedTable) return;
    const requestedId = relationSelectionKey(requestedSchema, requestedTable);
    if (selectedIds.size === 1 && selectedIds.has(requestedId)) return;
    if (selectedIds.size > 0) {
      setSelectedIds(new Set());
      setPreview(null);
    }
  }, [requestedSchema, requestedTable, selectedIds]);

  const filteredTables = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return allTables;
    return allTables.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        formatFriendlyName(t.name).toLowerCase().includes(q) ||
        t.owner.toLowerCase().includes(q) ||
        t.schema.toLowerCase().includes(q)
    );
  }, [search, allTables]);

  const sourceTables = useMemo(() => filteredTables.filter((t) => classifyTable(t.schema, t.name, t.owner) === 'source'), [filteredTables]);
  const pipelineTables = useMemo(() => filteredTables.filter((t) => classifyTable(t.schema, t.name, t.owner) === 'pipeline'), [filteredTables]);
  const internalTables = useMemo(() => filteredTables.filter((t) => classifyTable(t.schema, t.name, t.owner) === 'internal'), [filteredTables]);

  const visibleSchemas = useMemo(() => {
    return allSchemas.map(s => {
      const filteredTables = s.tables.filter(t => {
        const isInternal = classifyTable(t.schema, t.name, t.owner) === 'internal';
        return showInternal || !isInternal;
      });
      return { ...s, tables: filteredTables };
    }).filter(s => s.tables.length > 0);
  }, [allSchemas, showInternal]);

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

  function toggleTable(id: string) {
    const table = allTables.find((t) => t.id === id);
    if (!table) return;
    if (classifyTable(table.schema, table.name, table.owner) === 'internal') return;
    
    setPreview(null);
    setSelectedIds((prev) => {
      const next = prev.has(id) ? new Set<string>() : new Set([id]);
      persistSingleSelection(next);
      return next;
    });
  }

  function clearSelection() {
    const next = new Set<string>();
    setSelectedIds(next);
    setPreview(null);
    persistSingleSelection(next);
  }

  function handleUseTable(table: DbTable) {
    const metadataPath = withRunIdQuery(`/projects/${id}/metadata`, runId);
    const connectorPath = withConnectorFlowQuery(metadataPath, searchParams);
    navigate(
      withRelationSelectionQuery(
        connectorPath,
        {
          schema: table.schema,
          table: table.name,
        },
      ),
    );
  }

  async function handlePreview(table: DbTable) {
    const discoveryRequest = discoveryRequestRef.current;
    try {
      setPreviewingTableId(table.id);
      toast.loading(`Fetching preview for ${table.name}...`, { id: 'preview' });
      let nextPreview: TablePreview | null = null;
      if (connectionId) {
        const tablePreview = await previewPostgresTable(connectionId, table.schema, table.name);
        if (!isCurrentDatasetDiscovery(discoveryRequest, discoveryRequestRef.current)) return;
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
        if (!isCurrentDatasetDiscovery(discoveryRequest, discoveryRequestRef.current)) return;
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
    } catch {
      if (!isCurrentDatasetDiscovery(discoveryRequest, discoveryRequestRef.current)) return;
      toast.error('Failed to load table preview', { id: 'preview' });
    } finally {
      if (isCurrentDatasetDiscovery(discoveryRequest, discoveryRequestRef.current)) {
        setPreviewingTableId(null);
      }
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
          className="w-52 flex-shrink-0 border-r border-[#1e293b] bg-[#0b0f19] overflow-y-auto scrollbar-thin p-3 select-none"
          aria-label="Database schema tree"
        >
          <p className="mb-2.5 px-2 text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
            {connectionId && databaseName
              ? `${databaseName} / schemas`
              : 'LIVE SCHEMAS'}
          </p>
          <SchemaTree schemas={visibleSchemas} selectedIds={selectedIds} onToggle={toggleTable} />
        </aside>

        <div className="flex flex-1 flex-col overflow-hidden bg-[#0b0f19]">
          <div className="border-b border-[#1e293b] bg-[#111827] px-6 py-4">
            <h2 className="text-xl font-bold text-[#f8fafc] tracking-tight">Dataset Explorer</h2>
            <p className="text-xs text-[#94a3b8]">Select a relation to inspect and process through the Medallion pipeline.</p>
            {requestedRelationMissing && (
              <p className="mt-2 text-xs text-[#f59e0b] bg-[#f59e0b]/10 border border-[#f59e0b]/20 p-2 rounded-md">
                Previously selected relation{' '}
                <span className="font-mono">
                  {requestedRelation?.schema}.{requestedRelation?.table}
                </span>{' '}
                is no longer available. Choose another relation below.
              </p>
            )}
          </div>

          <div className="flex items-center gap-3 px-6 py-3 border-b border-[#1e293b] bg-[#111827]/50">
            <SearchBar
              value={search}
              onChange={setSearch}
              placeholder="Search tables by name or schema..."
              className="flex-1"
            />
          </div>

          <div
            className="flex-1 overflow-y-auto scrollbar-thin relative"
            role="table"
            aria-label="Available tables"
          >
            {loading ? (
              <div className="flex items-center justify-center h-full text-[#94a3b8]">
                Discovering schemas and tables...
              </div>
            ) : error ? (
              <div className="flex flex-col items-center justify-center h-full p-6 text-center">
                <p className="text-sm font-semibold text-[#ef4444] mb-2">{error}</p>
                <p className="text-xs text-[#64748b] mb-4">
                  Attempted:{' '}
                  <code className="font-mono bg-[#131a29] px-1.5 py-0.5 rounded text-[#94a3b8]">
                    {connectionId
                      ? 'GET /connectors/postgres/schemas and /tables'
                      : 'GET /metadata/tables'}
                  </code>
                </p>
                <div className="flex gap-3">
                  <Button variant="secondary" size="sm" onClick={loadData}>
                    Retry Discovery
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
              <div className="pb-10">
                {sourceTables.length > 0 ? (
                  <div className="mb-6">
                    <div className="bg-[#111827] px-5 py-2 border-b border-t border-[#1e293b] sticky top-0 z-10 shadow-sm">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-[#94a3b8]">Source Data</h3>
                    </div>
                    {sourceTables.map((table) => (
                      <TableRowCard
                        key={table.id}
                        table={table}
                        selected={selectedIds.has(table.id)}
                        previewing={previewingTableId === table.id}
                        onToggle={() => toggleTable(table.id)}
                        onPreview={() => handlePreview(table)}
                        onUse={() => handleUseTable(table)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="mb-6 flex flex-col items-center justify-center rounded-xl border border-[#1e293b] bg-[#111827] px-6 py-12 text-center">
                    <Database size={24} className="mx-auto mb-3 text-[#64748b]" />
                    <h3 className="text-sm font-semibold text-[#f8fafc]">No source datasets found</h3>
                    <p className="mt-2 max-w-md text-xs leading-relaxed text-[#94a3b8]">
                      Aurum did not receive any eligible source relations for this connection.
                    </p>
                    {connectionId && databaseName && (
                      <p className="mt-1 max-w-md text-[11px] font-mono text-[#64748b]">
                        Context: {databaseName}{requestedSchema ? ` / ${requestedSchema}` : ''}
                      </p>
                    )}
                    <div className="mt-4 flex gap-3">
                      <Button variant="secondary" size="sm" onClick={loadData}>
                        Refresh
                      </Button>
                      {connectionId && (
                        <Button variant="secondary" size="sm" onClick={() => navigate(`/projects/${id}/connect?source=postgresql`)}>
                          Back to Connect
                        </Button>
                      )}
                    </div>
                    {pipelineTables.length > 0 || internalTables.length > 0 ? (
                      <p className="mt-5 text-[11px] text-[#64748b] italic">
                        Generated and internal relations are available under Advanced or Pipeline Outputs.
                      </p>
                    ) : null}
                  </div>
                )}
                
                {pipelineTables.length > 0 && (
                  <div className="mb-6">
                    <div className="bg-[#111827] px-5 py-2 border-b border-t border-[#1e293b] sticky top-0 z-10 shadow-sm">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-[#94a3b8]">Pipeline Outputs</h3>
                    </div>
                    {pipelineTables.map((table) => (
                      <TableRowCard
                        key={table.id}
                        table={table}
                        selected={selectedIds.has(table.id)}
                        previewing={previewingTableId === table.id}
                        onToggle={() => toggleTable(table.id)}
                        onPreview={() => handlePreview(table)}
                        onUse={() => handleUseTable(table)}
                      />
                    ))}
                  </div>
                )}
                
                {internalTables.length > 0 && (
                  <div>
                    <div className="bg-[#111827] px-5 py-2 border-b border-t border-[#1e293b] sticky top-0 z-10 shadow-sm flex items-center justify-between">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-[#94a3b8]">Internal / Advanced</h3>
                      <button
                        onClick={() => setShowInternal(!showInternal)}
                        className="text-xs text-[#3b82f6] hover:text-[#60a5fa] focus:outline-none transition-colors font-medium cursor-pointer"
                      >
                        {showInternal ? 'Hide internal relations' : 'Show internal relations'}
                      </button>
                    </div>
                    {showInternal && internalTables.map((table) => (
                      <TableRowCard
                        key={table.id}
                        table={table}
                        selected={selectedIds.has(table.id)}
                        previewing={previewingTableId === table.id}
                        onToggle={() => toggleTable(table.id)}
                        onPreview={() => handlePreview(table)}
                        isInternal={true}
                      />
                    ))}
                  </div>
                )}
              </div>
            ) : !hasAnyTables ? (
              <div className="flex h-full flex-col items-center justify-center px-6 py-16 text-center">
                <div className="max-w-xl rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
                  <AlertTriangle size={28} className="mx-auto mb-4 text-[#f59e0b]" />
                  <h3 className="text-base font-semibold text-[#f8fafc]">
                    No source datasets found
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-[#94a3b8]">
                    Aurum did not receive any eligible source relations for this connection.
                  </p>
                  {databaseName && (
                    <p className="mt-2 text-[11px] font-mono text-[#64748b]">
                      Context: {databaseName}{requestedSchema ? ` / ${requestedSchema}` : ''}
                    </p>
                  )}
                  <div className="mt-5 flex flex-wrap justify-center gap-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={loadData}
                    >
                      Refresh
                    </Button>
                    {connectionId && (
                      <Button variant="secondary" size="sm" onClick={() => navigate(`/projects/${id}/connect?source=postgresql`)}>
                        Back to Connect
                      </Button>
                    )}
                  </div>
                  <p className="mt-5 text-[11px] text-[#64748b] italic">
                    Generated and internal relations are available under Advanced.
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <p className="text-sm text-[#64748b]">No tables match "{search}"</p>
                <button
                  onClick={() => setSearch('')}
                  className="mt-2 text-xs font-semibold text-[#3b82f6] hover:underline focus:outline-none cursor-pointer"
                >
                  Clear search
                </button>
              </div>
            )}
          </div>

          {selectedRelation && (
            <div className="border-t border-[#1e293b] bg-[#111827] px-6 py-3.5 flex items-center justify-between gap-4 shadow-lg animate-slide-up sticky bottom-0 z-20">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#94a3b8] uppercase tracking-wider mb-1">
                  Selected dataset
                </p>
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-semibold text-[#f8fafc] truncate">
                    {formatFriendlyName(selectedRelation.name)}
                  </span>
                  <span className="text-[11px] text-[#64748b] font-mono truncate" title={`${selectedRelation.schema}.${selectedRelation.name}`}>
                    {selectedRelation.schema}.{selectedRelation.name}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3 flex-shrink-0">
                <button
                  onClick={clearSelection}
                  className="text-xs text-[#94a3b8] hover:text-[#f8fafc] transition-colors font-medium cursor-pointer px-3 py-2"
                >
                  Clear
                </button>
                <Button
                  variant="primary"
                  size="md"
                  rightIcon={<ArrowRight size={16} />}
                  onClick={() => {
                    if (!selectedRelation) return;
                    const metadataPath = withRunIdQuery(`/projects/${id}/metadata`, runId);
                    const connectorPath = withConnectorFlowQuery(metadataPath, searchParams);
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
                  className="px-5 py-2 h-auto text-sm"
                >
                  Use this dataset
                </Button>
              </div>
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
            ? `${preview.rowCount != null ? preview.rowCount.toLocaleString() : '—'} rows, ${preview.columnCount != null ? preview.columnCount.toLocaleString() : preview.columns.length} columns`
            : undefined
        }
        className="max-h-[85vh] max-w-5xl overflow-hidden"
      >
        {preview && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-3.5 py-2.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Total Rows</p>
                <p className="mt-1 text-sm font-semibold text-[#f8fafc]">
                  <span className="font-semibold text-[#f8fafc]">{preview.rowCount != null ? preview.rowCount.toLocaleString() : '—'}</span> rows returned
                </p>
              </div>
              <div className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-3.5 py-2.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Columns</p>
                <p className="mt-1 text-sm font-semibold text-[#f8fafc]">
                  {preview.columnCount != null ? preview.columnCount.toLocaleString() : preview.columns.length}
                </p>
              </div>
              <div className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-3.5 py-2.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Preview Sample</p>
                <p className="mt-1 text-sm font-semibold text-[#f8fafc]">
                  Showing {preview.rows.length.toLocaleString()} rows
                </p>
              </div>
            </div>

            <div className="max-h-[46vh] overflow-auto rounded-lg border border-[#1e293b] scrollbar-thin">
              {preview.columns.length > 0 && preview.rows.length > 0 ? (
                <table className="w-full min-w-max text-left text-xs">
                  <thead className="sticky top-0 bg-[#111827] text-[#94a3b8] z-10">
                    <tr>
                      {preview.columns.map((column) => (
                        <th key={column.name} className="border-b border-r border-[#1e293b] px-3.5 py-2.5 align-top last:border-r-0">
                          <span className="block font-semibold text-[#f8fafc]">{column.name}</span>
                          <span className="mt-0.5 block text-[10px] font-mono font-normal text-[#06b6d4]">
                            {column.data_type}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1e293b] bg-[#0b0f19]">
                    {preview.rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className="hover:bg-[#131a29] transition-colors">
                        {preview.columns.map((column) => {
                          const value = row[column.name];
                          return (
                            <td key={column.name} className="max-w-64 border-r border-[#1e293b] px-3.5 py-2 text-[#f8fafc] last:border-r-0">
                              {value === null || value === undefined ? (
                                <span className="italic text-[#64748b] font-mono">NULL</span>
                              ) : (
                                <span className="block truncate font-mono text-[12px]" title={String(value)}>
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
                  <thead className="bg-[#111827] text-[#94a3b8]">
                    <tr>
                      <th className="border-b border-[#1e293b] px-3.5 py-2.5 font-semibold">Column</th>
                      <th className="border-b border-[#1e293b] px-3.5 py-2.5 font-semibold">Type</th>
                      <th className="border-b border-[#1e293b] px-3.5 py-2.5 font-semibold">Nullable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1e293b] bg-[#0b0f19]">
                    {preview.columns.map((column) => (
                      <tr key={column.name}>
                        <td className="px-3.5 py-2 font-medium text-[#f8fafc] font-mono">{column.name}</td>
                        <td className="px-3.5 py-2 text-[#06b6d4] font-mono">{column.data_type}</td>
                        <td className="px-3.5 py-2 text-[#94a3b8]">
                          {column.nullable === undefined ? '—' : column.nullable ? 'Yes' : 'No'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="px-4 py-8 text-center text-sm text-[#64748b]">
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
