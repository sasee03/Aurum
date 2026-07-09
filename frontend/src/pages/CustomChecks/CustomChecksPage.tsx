import { useCallback, useEffect, useState } from 'react';
import {
  createCustomCheck,
  listCustomChecks,
  runCustomCheck,
  type CustomCheck,
  type CustomCheckRunResult,
} from '@/lib/aurumApi';
import { PageAssistant } from '@/components/common/PageAssistant';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { Button } from '@/components/ui/Button';
import { useAppMode } from '@/context/AppModeContext';
import { CUSTOM_CHECKS_UNAVAILABLE } from '@/utils/apiErrors';

const RULE_TYPES = [
  'not_null',
  'unique',
  'accepted_values',
  'numeric_range',
  'row_count_condition',
  'custom_sql_demo',
] as const;

const EMPTY_FORM: Omit<CustomCheck, 'check_id'> = {
  layer: 'silver',
  check_name: '',
  rule_type: 'row_count_condition',
  column: '',
  operator: '>',
  value: '0',
  severity: 'high',
  description: '',
};

export function CustomChecksPage() {
  const { displayMode, backendReachable } = useAppMode();
  const [form, setForm] = useState(EMPTY_FORM);
  const [checks, setChecks] = useState<CustomCheck[]>([]);
  const [result, setResult] = useState<CustomCheckRunResult | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);

  const load = useCallback(async () => {
    if (!backendReachable) {
      setChecks([]);
      setServiceUnavailable(true);
      return;
    }
    try {
      const data = await listCustomChecks();
      setChecks(data.checks);
      setServiceUnavailable(false);
    } catch {
      setChecks([]);
      setServiceUnavailable(true);
    }
  }, [backendReachable]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setMessage(null);
    try {
      const saved = await createCustomCheck(form);
      setMessage(`Saved ${saved.check_id}`);
      setServiceUnavailable(false);
      await load();
    } catch {
      setServiceUnavailable(true);
    }
  };

  const testCheck = async (checkId: string) => {
    setRunningId(checkId);
    setResult(null);
    try {
      const runResult = await runCustomCheck(checkId);
      setResult(runResult);
      setServiceUnavailable(false);
    } catch {
      setServiceUnavailable(true);
      setResult(null);
    } finally {
      setRunningId(null);
    }
  };

  const sqlSelected = form.rule_type === 'custom_sql_demo';

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative p-6 space-y-6">
      <PageAssistant page="custom_checks" layer="silver" />

      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Custom Checks</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="text-sm text-[#6b7280] mt-1">
          Define domain-specific rules. Test Check currently runs against the Olist demo
          validation session; uploaded and connector-run scoped checks are coming soon.
          Results are additive and do not change the engine trust score or verdict.
        </p>
      </div>

      {!backendReachable && (
        <p className="text-sm text-[#94a3b8] rounded-lg border border-[#252637] bg-[#13141e] px-4 py-3">
          Custom checks require the API to be running. Start the backend and refresh.
        </p>
      )}

      {serviceUnavailable && backendReachable && (
        <p className="text-sm text-[#94a3b8] rounded-lg border border-[#252637] bg-[#13141e] px-4 py-3">
          {CUSTOM_CHECKS_UNAVAILABLE}
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-4xl">
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Layer
          <select
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.layer}
            onChange={(e) => setForm({ ...form, layer: e.target.value as CustomCheck['layer'] })}
            disabled={serviceUnavailable}
          >
            <option value="bronze">bronze</option>
            <option value="silver">silver</option>
            <option value="gold">gold</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Check name
          <input
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.check_name}
            onChange={(e) => setForm({ ...form, check_name: e.target.value })}
            disabled={serviceUnavailable}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Rule type
          <select
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.rule_type}
            onChange={(e) => setForm({ ...form, rule_type: e.target.value })}
            disabled={serviceUnavailable}
          >
            {RULE_TYPES.map((rt) => (
              <option key={rt} value={rt}>
                {rt}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Severity
          <select
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value })}
            disabled={serviceUnavailable}
          >
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Column
          <input
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.column}
            onChange={(e) => setForm({ ...form, column: e.target.value })}
            placeholder="e.g. customer_id (unused for row_count_condition)"
            disabled={serviceUnavailable || form.rule_type === 'row_count_condition'}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Operator
          <input
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.operator}
            onChange={(e) => setForm({ ...form, operator: e.target.value })}
            placeholder=">, >=, <, <=, ==, or between"
            disabled={serviceUnavailable}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8] md:col-span-2">
          Value
          <input
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
            placeholder="e.g. 0 | 1,100 | UK,France,Germany"
            disabled={serviceUnavailable}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8] md:col-span-2">
          Description
          <textarea
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
            rows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            disabled={serviceUnavailable}
          />
        </label>
      </div>

      {sqlSelected && (
        <p className="text-sm text-[#f59e0b] rounded-lg border border-[#3f3a1f] bg-[#1a1810] px-4 py-3 max-w-4xl">
          SQL-based checks (custom_sql_demo) are not yet supported — Test Check will return
          SKIPPED and will not execute arbitrary SQL.
        </p>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <Button variant="primary" onClick={save} disabled={serviceUnavailable}>
          Save Check
        </Button>
      </div>

      {message && <p className="text-sm text-[#22c55e]">{message}</p>}

      {checks.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-[#f1f5f9]">Saved checks</h3>
          {checks.map((c) => (
            <div
              key={c.check_id}
              className="flex items-center justify-between rounded-lg border border-[#252637] px-4 py-2 text-sm"
            >
              <span>
                {c.check_id} — {c.check_name} ({c.layer} / {c.rule_type})
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => c.check_id && testCheck(c.check_id)}
                disabled={serviceUnavailable || runningId === c.check_id}
              >
                {runningId === c.check_id ? 'Running…' : 'Test Check'}
              </Button>
            </div>
          ))}
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4 space-y-2 max-w-4xl">
          <p className="text-sm font-semibold text-[#f1f5f9]">Latest Test Check Result</p>
          <p className="text-sm text-[#f1f5f9]">
            <strong>{result.status}</strong> — {result.message}
          </p>
          <p className="text-xs text-[#94a3b8]">
            observed: {String(result.observed_value)} · expected: {result.expected_condition}
          </p>
          {result.data_source && (
            <p className="text-xs rounded border border-[#334155] bg-[#0f172a] px-2 py-1 text-[#bfdbfe]">
              <strong>Data source:</strong> {result.data_source}
            </p>
          )}
          {result.scope_note && (
            <p className="text-xs rounded border border-[#3f3a1f] bg-[#1a1810] px-2 py-1 text-[#fbbf24]">
              <strong>Scope note:</strong> {result.scope_note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
