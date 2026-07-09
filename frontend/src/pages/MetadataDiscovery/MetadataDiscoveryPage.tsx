import { useState, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { MetricCard } from '@/components/cards/MetricCard';
import { ProgressMetric } from '@/components/common/ProgressMetric';
import { Heatmap } from '@/components/common/Heatmap';
import { PlannedBanner } from '@/components/common/PlannedBanner';
import { PageAssistant } from '@/components/common/PageAssistant';
import { cn } from '@/utils/cn';

import type { DatasetMetadata, DbTable } from '@/types';
import metadataJson from '@/mocks/metadata.json';
import tablesJson from '@/mocks/tables.json';

const metadataRecords = metadataJson as DatasetMetadata[];
const allSchemas = tablesJson.schemas;
const allTables: DbTable[] = allSchemas.flatMap((s) => s.tables);

export function MetadataDiscoveryPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();

  // Only consider tables that have metadata available
  const availableTables = useMemo(() => {
    return allTables.filter((t) => metadataRecords.some((m) => m.tableId === t.id));
  }, []);

  const [activeTabId, setActiveTabId] = useState(availableTables[0]?.id);

  const activeMetadata = useMemo(() => {
    return metadataRecords.find((m) => m.tableId === activeTabId) || metadataRecords[0];
  }, [activeTabId]);

  if (!activeMetadata || availableTables.length === 0) {
    return (
      <div className="flex h-full flex-col overflow-hidden animate-fade-in">
        <ProjectSubNav />
        <div className="flex-1 flex items-center justify-center text-[#6b7280]">
          No metadata available.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav />
      <PageAssistant page="validation" />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Page Header */}
        <div className="px-6 py-6 border-b border-[#252637]">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Metadata Discovery</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Stage 2 profiling — Preview — not wired to live API yet.
          </p>
          <div className="mt-4">
            <PlannedBanner
              detail="Foreign Keys, Duplicate %, Outliers, and Freshness below are preview placeholders. Live profiling will use GET /metadata when wired. Validation report remains the source of truth for checks."
            />
          </div>
          
          {/* Tabs */}
          <div className="flex gap-2 mt-6">
            {availableTables.map((table) => {
              const isActive = activeTabId === table.id;
              return (
                <button
                  key={table.id}
                  onClick={() => setActiveTabId(table.id)}
                  className={cn(
                    'px-4 py-1.5 rounded-full text-xs font-semibold transition-all focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
                    isActive
                      ? 'bg-[#6366f1] text-white shadow-[0_4px_12px_rgba(99,102,241,0.3)]'
                      : 'border border-[#252637] text-[#94a3b8] hover:border-[#6366f1]/40 hover:text-[#f1f5f9]'
                  )}
                >
                  {table.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
          
          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard 
              label="Total Rows" 
              value={activeMetadata.totalRows} 
            />
            <MetricCard 
              label="Columns" 
              value={activeMetadata.columns} 
            />
            <MetricCard 
              label="Primary Keys" 
              value={activeMetadata.primaryKeys} 
              subValue={activeMetadata.pkColumns.join(', ')} 
            />
            <MetricCard 
              label="Foreign Keys" 
              value={activeMetadata.foreignKeys}
              subValue="Preview — planned"
            />

            <MetricCard 
              label="Missing Values" 
              value={`${activeMetadata.missingValuesPct}%`} 
              subValue="below threshold" 
              valueClass="text-[#22c55e]"
            />
            <MetricCard 
              label="Duplicate %" 
              value={`${activeMetadata.duplicatePct}%`} 
              subValue="Preview — planned"
              valueClass="text-[#f59e0b]"
            />
            <MetricCard 
              label="Null %" 
              value={`${activeMetadata.nullPct}%`} 
              valueClass="text-[#ef4444]"
            />
            <MetricCard 
              label="Unique %" 
              value={`${activeMetadata.uniquePct}%`} 
              valueClass="text-[#22c55e]"
            />

            <MetricCard 
              label="Outliers" 
              value={activeMetadata.outliers}
              subValue="Preview — planned"
              valueClass="text-[#f59e0b]"
            />
            <MetricCard 
              label="Freshness" 
              value={activeMetadata.freshness}
              subValue="Preview — planned"
              valueClass="text-[#94a3b8]"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-6">
            {/* Left Panel: Column Completeness */}
            <div className="rounded-xl border border-[#252637] bg-[#1a1b28]/30 p-5">
              <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280] mb-5">
                Column Quality Completeness
              </h3>
              <div className="space-y-4">
                {activeMetadata.columnsQuality.map((col) => (
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

            {/* Right Panel: Heatmap */}
            <div className="rounded-xl border border-[#252637] bg-[#1a1b28]/30 p-5">
              <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280] mb-5">
                Null Density Heatmap
              </h3>
              <div className="flex items-center justify-center h-[calc(100%-2rem)]">
                <Heatmap pattern={activeMetadata.nullDensityPattern} />
              </div>
            </div>
          </div>
        </div>

        {/* Sticky Footer */}
        <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => navigate(`/projects/${id}/select`)}
          >
            Back to Select
          </Button>
          <Button
            variant="primary"
            rightIcon={<ArrowRight size={16} />}
            onClick={() => navigate(`/projects/${id}/validate/config`)}
          >
            Configure Pipeline
          </Button>
        </div>
      </div>
    </div>
  );
}
