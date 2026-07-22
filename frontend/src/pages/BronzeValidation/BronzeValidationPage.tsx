import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight, Database, Table, Layers } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { withRunIdQuery } from '@/hooks/useReport';

export function BronzeValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="bronze" layer="bronze" runId={runId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Bronze Layer</h2>
          <DataSourceBadge mode="planned" />
          <Badge variant="secondary">Preview Shell</Badge>
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Raw data ingestion and structural staging layer (Batch 2 wiring planned).
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10] scrollbar-thin">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {/* Selected Source Tables */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center gap-2 mb-3">
                <Database size={16} className="text-[#6366f1]" />
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Selected Source Tables</h3>
              </div>
              <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 text-xs text-[#94a3b8]">
                <p className="font-medium text-[#cbd5e1]">Source Table Selection (Planned)</p>
                <p className="mt-1 text-[#6b7280]">
                  No table ingested yet. Select a source table during Connect to populate Bronze layer metadata.
                </p>
              </div>
            </div>

            {/* Bronze Ingestion / Status Area */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center gap-2 mb-3">
                <Layers size={16} className="text-[#6366f1]" />
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Bronze Ingestion &amp; Status</h3>
              </div>
              <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-[#94a3b8]">Ingestion Status</span>
                  <Badge variant="secondary">Planned</Badge>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-[#94a3b8]">Validation Checks</span>
                  <span className="text-[#6b7280]">Schema, Nulls, PK Uniqueness (Batch 2)</span>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {/* Source Rows vs Bronze Rows */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center gap-2 mb-3">
                <Table size={16} className="text-[#6366f1]" />
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Source Rows vs Bronze Rows</h3>
              </div>
              <div className="space-y-2 text-xs text-[#94a3b8]">
                <div className="flex justify-between py-1 border-b border-[#252637]">
                  <span>Source Rows</span>
                  <span className="font-mono text-[#6b7280]">—</span>
                </div>
                <div className="flex justify-between py-1 border-b border-[#252637]">
                  <span>Bronze Ingested Rows</span>
                  <span className="font-mono text-[#6b7280]">—</span>
                </div>
                <div className="flex justify-between py-1">
                  <span>Ingestion Loss / Delta</span>
                  <span className="font-mono text-[#6b7280]">—</span>
                </div>
              </div>
            </div>

            {/* Bronze Data Preview */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-3">Bronze Data Preview</h3>
              <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#6b7280]">
                Raw row preview will display here after Bronze ingestion.
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => navigate(withRunIdQuery(`/projects/${id}/connect`, runId))}
        >
          Back to Connect
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() => navigate(withRunIdQuery(`/projects/${id}/silver`, runId))}
        >
          Continue to Silver
        </Button>
      </div>
    </div>
  );
}
