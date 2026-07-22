import React from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';

/*
  Simplified Gold Layer page scaffold based on provided design image:
  - Business Requirement input
  - KPI Plan list with readiness indicators
  - Generated SQL preview per KPI
  - Ready to Build summary
  - Gold Data Preview table
*/

export function GoldValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  const kpis = [
    'GMV',
    'Total Orders',
    'Completed Orders',
    'Refund Rate',
    'Top Categories',
    'Top Brands',
    'Repeat Purchase Rate',
  ];

  const sqlPreview = `SELECT DATE_TRUNC('day', o.order_date) AS date,\n  SUM(o.gross_amount) AS gmv\nFROM silver.orders o\nWHERE o.order_status = 'completed'\nGROUP BY 1\nORDER BY 1;`;

  const goldRows = [
    { date: '2024-05-01', GMV: '1,256,780.45', total_orders: 3456, completed_orders: 3212 },
    { date: '2024-05-02', GMV: '1,342,891.56', total_orders: 3678, completed_orders: 3401 },
    { date: '2024-05-03', GMV: '1,198,445.22', total_orders: 3210, completed_orders: 2987 },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="gold" layer="gold" runId={runId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Gold Layer</h2>
          <DataSourceBadge mode="live" />
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">Generate business-ready Gold outputs from approved Silver data.</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10]">
        <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
          <h3 className="text-sm font-semibold text-[#f1f5f9]">1. Business Requirement</h3>
          <textarea
            className="mt-3 w-full rounded p-3 bg-[#0b0c12] text-sm text-[#e5e7eb]"
            rows={2}
            defaultValue={"I need an executive e-commerce dashboard."}
          />
          <div className="mt-3 text-right">
            <Button variant="primary">Generate KPI Plan</Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">2. KPI Plan</h3>
              <ul className="mt-3 text-sm text-[#e5e7eb] space-y-2">
                {kpis.map((k) => (
                  <li key={k} className="flex items-center justify-between">
                    <span>{k}</span>
                    <Badge variant="pass">Ready</Badge>
                  </li>
                ))}
                <li className="flex items-center justify-between text-[#f59e0b]">
                  <span>Customer Satisfaction — missing reviews.rating</span>
                  <span>Unavailable</span>
                </li>
              </ul>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">3. Generated SQL</h3>
              <div className="mt-3 text-xs text-[#94a3b8]">
                <div className="rounded border border-[#252637] p-3 bg-[#0b0c12]">
                  <div className="flex items-center justify-between">
                    <div>GMV</div>
                    <Button variant="ghost">View SQL</Button>
                  </div>
                  <pre className="mt-2 text-[11px] text-[#9ca3af]">{sqlPreview}</pre>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">4. Ready to Build</h3>
              <div className="mt-3 text-sm text-[#94a3b8]">
                <div className="flex justify-between"><span>KPIs ready</span><strong>12</strong></div>
                <div className="flex justify-between"><span>unavailable</span><strong>2</strong></div>
              </div>
              <div className="mt-4 text-xs text-[#94a3b8]">
                Planned outputs: executive_summary, top_categories, top_brands
              </div>
              <div className="mt-4 text-right">
                <Button variant="primary">Approve & Build Gold</Button>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">5. Gold Data Preview</h3>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-left text-xs text-[#e5e7eb]">
                  <thead className="text-[#94a3b8]">
                    <tr>
                      <th className="px-2 py-1">date</th>
                      <th className="px-2 py-1">GMV</th>
                      <th className="px-2 py-1">total_orders</th>
                      <th className="px-2 py-1">completed_orders</th>
                      <th className="px-2 py-1">refund_rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {goldRows.map((r) => (
                      <tr key={r.date} className="border-t border-[#252637]">
                        <td className="px-2 py-1">{r.date}</td>
                        <td className="px-2 py-1">{r.GMV}</td>
                        <td className="px-2 py-1">{r.total_orders}</td>
                        <td className="px-2 py-1">{r.completed_orders}</td>
                        <td className="px-2 py-1">2.18%</td>
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
        <Button variant="ghost" onClick={() => navigate(`/projects/${id}/validate/silver`)}>
          Back to Silver
        </Button>
        <Button variant="primary" rightIcon={<ArrowRight size={16} />}>
          Approve & Build Gold
        </Button>
      </div>
    </div>
  );
}
