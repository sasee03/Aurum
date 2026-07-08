import { useState, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronRight, ChevronDown, ArrowRight, CheckSquare, Square } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { SearchBar } from '@/components/common/SearchBar';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { cn } from '@/utils/cn';
import { PlannedBanner } from '@/components/common/PlannedBanner';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { usePlannedMode } from '@/context/AppModeContext';
import tablesData from '@/mocks/tables.json';

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

const allSchemas: SchemaNode[] = tablesData.schemas as SchemaNode[];
const allTables: DbTable[] = allSchemas.flatMap((s) => s.tables);

// ────────────────────────────────────────────
// Schema Tree
// ────────────────────────────────────────────
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

// ────────────────────────────────────────────
// Table Row Card
// ────────────────────────────────────────────
function TableRowCard({
  table,
  selected,
  onToggle,
}: {
  table: DbTable;
  selected: boolean;
  onToggle: () => void;
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
      {/* Checkbox */}
      <div className="flex-shrink-0">
        {selected ? (
          <CheckSquare size={16} className="text-[#6366f1]" />
        ) : (
          <Square size={16} className="text-[#4b5563] group-hover:text-[#6b7280]" />
        )}
      </div>

      {/* Name */}
      <div className="flex-1 min-w-0">
        <p className={cn('text-sm font-semibold truncate', selected ? 'text-[#6366f1]' : 'text-[#f1f5f9]')}>
          {table.name}
        </p>
        <p className="text-[11px] text-[#4b5563]">
          {table.owner} · {table.lastUpdated}
        </p>
      </div>

      {/* Stats */}
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
    </div>
  );
}

// ────────────────────────────────────────────
// Dataset Explorer Page
// ────────────────────────────────────────────
export function DatasetExplorerPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { displayMode } = usePlannedMode(
    'Dataset Explorer for live connector onboarding is planned / not wired yet.',
  );
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(['tbl-001', 'tbl-002', 'tbl-003', 'tbl-005'])
  );

  const filteredTables = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return allTables;
    return allTables.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.owner.toLowerCase().includes(q) ||
        t.schema.toLowerCase().includes(q)
    );
  }, [search]);

  function toggleTable(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(filteredTables.map((t) => t.id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  const selectedTables = allTables.filter((t) => selectedIds.has(t.id));
  const hasResults = filteredTables.length > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />

      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel — Schema Tree */}
        <aside
          className="w-48 flex-shrink-0 border-r border-[#252637] bg-[#0d0e14] overflow-y-auto scrollbar-thin p-3"
          aria-label="Database schema tree"
        >
          <p className="mb-2 px-2 text-[10px] font-bold uppercase tracking-widest text-[#4b5563]">
            RETAIL_DB / PUBLIC
          </p>
          <SchemaTree schemas={allSchemas} selectedIds={selectedIds} onToggle={toggleTable} />
        </aside>

        {/* Main Content */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Header */}
          <div className="border-b border-[#252637] px-6 py-4">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-bold text-[#f1f5f9]">Dataset Explorer</h2>
              <DataSourceBadge mode={displayMode} />
            </div>
            <p className="text-xs text-[#6b7280] mt-1">
              Sample Olist tables shown as a verified snapshot — not live connector catalog.
            </p>
            <div className="mt-3">
              <PlannedBanner detail="Preview — not wired to GET /metadata/tables. Tables below are fixture data for the onboarding walkthrough." />
            </div>
          </div>

          {/* Search + Actions */}
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

          {/* Table List */}
          <div
            className="flex-1 overflow-y-auto scrollbar-thin"
            role="table"
            aria-label="Available tables"
          >
            {hasResults ? (
              filteredTables.map((table) => (
                <TableRowCard
                  key={table.id}
                  table={table}
                  selected={selectedIds.has(table.id)}
                  onToggle={() => toggleTable(table.id)}
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

          {/* Sticky Footer */}
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
