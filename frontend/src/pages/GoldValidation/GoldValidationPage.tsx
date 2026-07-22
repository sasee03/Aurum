import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { withRunIdQuery } from '@/hooks/useReport';

/*
  Gold Layer page scaffold.
  Preserves visual Gold structure with honest planned preview markers.
*/

export function GoldValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  const sampleSilverTable = 'silver.orders_cleaned';
  const sqlPreview = `SELECT DATE_TRUNC('day', o.order_date) AS date,\n  SUM(o.amount) AS daily_revenue\nFROM silver.orders_cleaned o\nGROUP BY 1\nORDER BY 1;`;

  const goldRows = [
    { date: '2024-05-01', daily_revenue: '1,256,780.45', total_orders: 3456, completed_orders: 3212 },
    { date: '2024-05-02', daily_revenue: '1,342,891.56', total_orders: 3678, completed_orders: 3401 },
    { date: '2024-05-03', daily_revenue: '1,198,445.22', total_orders: 3210, computed_status: 'VALIDATED' },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="gold" layer="gold" runId={runId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Gold Layer</h2>
          <DataSourceBadge mode="planned" />
          <Badge variant="secondary">Preview Shell</Badge>
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Generate business-ready Gold outputs from approved Silver data.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10] scrollbar-thin">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {/* Selected Silver Data */}
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-1">Selected Silver Data</h3>
              <p className="text-xs text-[#94a3b8]">{sampleSilverTable} • Cleaned dataset</p>
            </div>

            {/* Business Requirement */}
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">1. Business Requirement</h3>
              <textarea
                className="mt-3 w-full rounded border border-[#252637] p-3 bg-[#0b0c12] text-sm text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
                rows={2}
                defaultValue="Summarize daily revenue and order counts for executive reporting."
              />
              <div className="mt-3 flex justify-end">
                <Button variant="primary">Generate SQL (Planned)</Button>
              </div>
            </div>

            {/* Generated SQL */}
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">2. Generated SQL</h3>
              <div className="mt-3 text-xs text-[#94a3b8]">
                <div className="rounded border border-[#252637] p-3 bg-[#0b0c12]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-[#f1f5f9]">Daily Revenue Aggregation</span>
                    <Badge variant="secondary">Preview</Badge>
                  </div>
                  <pre className="text-[11px] text-[#9ca3af] font-mono">{sqlPreview}</pre>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {/* Planned Gold Output */}
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">3. Planned Gold Output</h3>
              <div className="mt-3 space-y-2 text-xs text-[#94a3b8]">
                <div className="flex justify-between py-1 border-b border-[#252637]">
                  <span>Output Table</span>
                  <span className="font-mono text-[#cbd5e1]">gold.daily_revenue_summary</span>
                </div>
                <div className="flex justify-between py-1 border-b border-[#252637]">
                  <span>Target Grain</span>
                  <span>Daily Summary</span>
                </div>
                <div className="flex justify-between py-1">
                  <span>Build Status</span>
                  <Badge variant="secondary">Planned</Badge>
                </div>
              </div>
            </div>

            {/* Gold Data Preview */}
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">4. Gold Data Preview</h3>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-left text-xs text-[#e5e7eb]">
                  <thead className="text-[#94a3b8] border-b border-[#252637]">
                    <tr>
                      <th className="px-2 py-1.5 font-semibold">date</th>
                      <th className="px-2 py-1.5 font-semibold">daily_revenue</th>
                      <th className="px-2 py-1.5 font-semibold">total_orders</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#252637]">
                    {goldRows.map((r, i) => (
                      <tr key={i} className="hover:bg-[#1a1b28]/40">
                        <td className="px-2 py-1.5">{r.date}</td>
                        <td className="px-2 py-1.5">{r.daily_revenue}</td>
                        <td className="px-2 py-1.5">{r.total_orders}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate(withRunIdQuery(`/projects/${id}/silver`, runId))}>
          Back to Silver
        </Button>
        <Button variant="primary" disabled title="Gold table building planned in Batch 4">
          Approve &amp; Build Gold (Planned)
        </Button>
      </div>
    </div>
  );
}
