import React from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';

/*
  Simplified Silver Validation page scaffold.
  Visual structure is based on the provided design image:
  - Selected Bronze Table
  - Cleaning Rules list + Generate SQL
  - Generated SQL per rule
  - Planned Changes + Transformation Result
  - Silver Data Preview
*/

export function SilverValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  const sampleTable = 'bronze.silver_orders';
  const cleaningRules = [
    'Remove duplicate orders (based on order_id)',
    'Remove rows where customer_id is null',
    'Convert order_date to DATE type',
    'Convert amount to DECIMAL(12,2)',
    'Standardize status to UPPERCASE',
  ];

  const generatedSql = cleaningRules.map((r, i) => ({
    id: `rule-${i + 1}`,
    title: r,
    sql: `-- SQL for: ${r}\nSELECT * FROM __INPUT__`,
  }));

  const previewRows = [
    { order_id: 10001, customer_id: 'CUST_001', order_date: '2024-05-20', amount: '450.00', status: 'DELIVERED' },
    { order_id: 10002, customer_id: 'CUST_002', order_date: '2024-05-20', amount: '199.00', status: 'PENDING' },
    { order_id: 10003, customer_id: 'CUST_003', order_date: '2024-05-21', amount: '750.50', status: 'DELIVERED' },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="silver" layer="silver" runId={runId} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Silver Validation</h2>
          <DataSourceBadge mode="live" />
          <Badge variant="secondary">LAYER FAIL</Badge>
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">Clean and transform your Bronze data to build trusted Silver layer.</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10]">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-2">Selected Bronze Table</h3>
              <div className="text-xs text-[#94a3b8]">{sampleTable} • 10,024 rows • 12 columns</div>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">2. Cleaning Rules (Ordered)</h3>
                <Button variant="ghost">+ Add Rule</Button>
              </div>
              <ol className="space-y-2 text-sm text-[#e5e7eb]">
                {cleaningRules.map((r, i) => (
                  <li key={i} className="flex items-center justify-between">
                    <span>{i + 1}. {r}</span>
                    <div className="text-xs text-[#6b7280]">⋮</div>
                  </li>
                ))}
              </ol>
              <div className="mt-4">
                <Button variant="primary">Generate SQL</Button>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-2">4. Planned Changes</h3>
              <ul className="text-sm text-[#94a3b8] space-y-2">
                <li>Remove duplicate orders based on order_id.</li>
                <li>Remove rows where customer_id is null.</li>
                <li>Convert order_date to DATE type.</li>
                <li>Convert amount to DECIMAL(12,2).</li>
                <li>Standardize status to UPPERCASE.</li>
              </ul>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">3. Generated SQL (Per Rule)</h3>
              <div className="mt-3 space-y-2 text-xs text-[#94a3b8]">
                {generatedSql.map((g) => (
                  <div key={g.id} className="rounded border border-[#252637] p-2 bg-[#0b0c12]">
                    <div className="flex items-center justify-between">
                      <div>{g.title}</div>
                      <Button variant="ghost">View SQL</Button>
                    </div>
                    <pre className="mt-2 text-[11px] text-[#9ca3af]">{g.sql}</pre>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">5. Transformation Result</h3>
              <div className="mt-2 text-sm text-[#94a3b8]">
                <div className="flex justify-between"><span>Bronze Rows</span><span>10,024</span></div>
                <div className="flex justify-between"><span>Silver Rows</span><span>9,356</span></div>
                <div className="flex justify-between"><span>Rows Affected</span><span>668</span></div>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] p-4 bg-[#0d0e14]">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">6. Silver Data Preview</h3>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-left text-xs text-[#e5e7eb]">
                  <thead className="text-[#94a3b8]">
                    <tr>
                      <th className="px-2 py-1">order_id</th>
                      <th className="px-2 py-1">customer_id</th>
                      <th className="px-2 py-1">order_date</th>
                      <th className="px-2 py-1">product_id</th>
                      <th className="px-2 py-1">quantity</th>
                      <th className="px-2 py-1">amount</th>
                      <th className="px-2 py-1">status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows.map((r) => (
                      <tr key={r.order_id} className="border-t border-[#252637]">
                        <td className="px-2 py-1">{r.order_id}</td>
                        <td className="px-2 py-1">{r.customer_id}</td>
                        <td className="px-2 py-1">{r.order_date}</td>
                        <td className="px-2 py-1">P{String(r.order_id).slice(-3)}</td>
                        <td className="px-2 py-1">{r.amount === '199.00' ? 1 : 2}</td>
                        <td className="px-2 py-1">{r.amount}</td>
                        <td className="px-2 py-1">{r.status}</td>
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
        <Button variant="ghost" onClick={() => navigate(`/projects/${id}/validate/bronze`)}>
          Back to Bronze
        </Button>
        <Button variant="primary" rightIcon={<ArrowRight size={16} />}>
          Approve & Execute
        </Button>
      </div>
    </div>
  );
}
