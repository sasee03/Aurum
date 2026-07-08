import { useState, useMemo, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronRight, ChevronDown, ArrowRight, CheckSquare, Square, Eye, AlertTriangle } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { SearchBar } from '@/components/common/SearchBar';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { cn } from '@/utils/cn';
import { getMetadataTables, getMetadataTable } from '@/lib/aurumApi';
import tablesJson from '@/mocks/tables.json';

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

  function toggleSchema(name: string) {
    setExpandedSchemas((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
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
  onToggle,
  onPreview,
}: {
  table: DbTable;
  selected: boolean;
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
          onClick={(e) => { e.stopPropagation(); onPreview(); }}
        >
          Preview
        </Button>
      </div>
    </div>
  );
}

export function DatasetExplorerPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  
  const [allSchemas, setAllSchemas] = useState<SchemaNode[]>([]);
  const [allTables, setAllTables] = useState<DbTable[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingFallback, setUsingFallback] = useState(false);

  async function loadData() {
    setLoading(true);
    setError(null);
    setUsingFallback(false);
    try {
      const res = await getMetadataTables();
      const tables = res.tables || [];
      
      const schemaMap = new Map<string, DbTable[]>();
      const formattedTables: DbTable[] = [];
      
      for (const t of tables) {
        const dbT: DbTable = {
          id: `${t.schema}.${t.table}`,
          schema: t.schema,
          name: t.table,
          owner: 'demo_user',
          rows: t.row_count?.toString() || '0',
          columns: t.column_count || 0,
          size: '-',
          lastUpdated: 'Live'
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
      setUsingFallback(true);
      const fallbackSchemas = tablesJson.schemas as SchemaNode[];
      const fallbackTables = fallbackSchemas.flatMap(s => s.tables);
      setAllSchemas(fallbackSchemas);
      setAllTables(fallbackTables);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

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

  function toggleTable(tableId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(tableId) ? next.delete(tableId) : next.add(tableId);
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(filteredTables.map((t) => t.id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  async function handlePreview(table: DbTable) {
    try {
      toast.loading(`Fetching preview for ${table.name}...`, { id: 'preview' });
      const res = await getMetadataTable(table.name, table.schema);
      const tableData = res.tables?.[0];
      if (tableData) {
        toast.success(
          <div className="text-xs max-h-60 overflow-y-auto w-80 text-left">
            <strong className="block mb-2 text-sm">{table.name} details</strong>
            <pre className="whitespace-pre-wrap font-mono text-[10px] text-gray-800">
              {JSON.stringify(tableData, null, 2)}
            </pre>
          </div>,
          { id: 'preview', duration: 8000 }
        );
      } else {
        toast.success('No metadata returned', { id: 'preview' });
      }
    } catch (e) {
      toast.error('Failed to load table preview', { id: 'preview' });
    }
  }

  const selectedTables = allTables.filter((t) => selectedIds.has(t.id));
  const hasResults = filteredTables.length > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 overflow-hidden">
        <aside
          className="w-48 flex-shrink-0 border-r border-[#252637] bg-[#0d0e14] overflow-y-auto scrollbar-thin p-3"
          aria-label="Database schema tree"
        >
          <p className="mb-2 px-2 text-[10px] font-bold uppercase tracking-widest text-[#4b5563]">
            {usingFallback ? 'DEMO SCHEMAS' : 'LIVE SCHEMAS'}
          </p>
          <SchemaTree schemas={allSchemas} selectedIds={selectedIds} onToggle={toggleTable} />
        </aside>

        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="border-b border-[#252637] px-6 py-4">
            <h2 className="text-lg font-bold text-[#f1f5f9]">Dataset Explorer</h2>
            <p className="text-xs text-[#6b7280]">Select tables for AURUM to validate this run.</p>
          </div>

          {usingFallback && (
            <div className="bg-[#451a03] border-b border-[#78350f] px-6 py-3 flex items-center justify-between">
              <div className="flex items-center gap-3 text-[#fde68a]">
                <AlertTriangle size={16} className="text-[#f59e0b]" />
                <p className="text-xs font-semibold">Demo fallback: backend PostgreSQL metadata is unavailable, showing bundled demo dataset metadata.</p>
              </div>
              <Button variant="secondary" size="sm" onClick={loadData} className="border-[#78350f] text-[#fcd34d] hover:bg-[#78350f]/50">
                Retry Live Connection
              </Button>
            </div>
          )}

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
                  Attempted: <code className="font-mono bg-[#1a1b28] px-1 py-0.5 rounded">GET /metadata/tables</code>
                </p>
                <p className="text-xs text-[#6b7280] mb-4 text-center">
                  Check backend/PostgreSQL connection.<br />
                  Make sure uvicorn is running: <br />
                  <code className="font-mono text-[#f1f5f9] bg-[#1a1b28] px-1 py-0.5 rounded block mt-1">uvicorn api.main:app --reload --port 8000</code>
                </p>
                <Button variant="secondary" size="sm" onClick={loadData}>
                  Retry
                </Button>
              </div>
            ) : hasResults ? (
              filteredTables.map((table) => (
                <TableRowCard
                  key={table.id}
                  table={table}
                  selected={selectedIds.has(table.id)}
                  onToggle={() => toggleTable(table.id)}
                  onPreview={() => handlePreview(table)}
                />
              ))
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
                      {t.name}
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
                onClick={() => navigate(`/projects/${id}/metadata`)}
                className="flex-shrink-0"
              >
                Continue
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
