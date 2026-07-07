import { useCallback, useEffect, useState } from 'react';
import {
  createCustomCheck,
  listCustomChecks,
  runCustomCheck,
  type CustomCheck,
  type CustomCheckRunResult,
} from '@/lib/aurumApi';
import { PageAssistant } from '@/components/common/PageAssistant';
import { Button } from '@/components/ui/Button';
import { CUSTOM_CHECKS_UNAVAILABLE } from '@/utils/apiErrors';

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
  const [form, setForm] = useState(EMPTY_FORM);
  const [checks, setChecks] = useState<CustomCheck[]>([]);
  const [preview, setPreview] = useState<CustomCheckRunResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await listCustomChecks();
      setChecks(data.checks);
      setServiceUnavailable(false);
    } catch {
      setChecks([]);
      setServiceUnavailable(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setMessage(null);
    try {
      const result = await createCustomCheck(form);
      setMessage(`Saved ${result.check_id}`);
      setServiceUnavailable(false);
      await load();
    } catch {
      setServiceUnavailable(true);
    }
  };

  const previewRun = async (checkId: string) => {
    try {
      const result = await runCustomCheck(checkId);
      setPreview(result);
      setServiceUnavailable(false);
    } catch {
      setServiceUnavailable(true);
      setPreview(null);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative p-6 space-y-6">
      <PageAssistant page="custom_checks" layer="silver" />

      <div>
        <h2 className="text-xl font-bold text-[#f1f5f9]">Custom Checks</h2>
        <p className="text-sm text-[#6b7280] mt-1">
          Domain-specific rules — save/list is real when the service is reachable; preview is
          demo-only.
        </p>
      </div>

      {serviceUnavailable && (
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

      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <Button variant="primary" onClick={save} disabled={serviceUnavailable}>
          Save Check
        </Button>
        <span className="text-xs text-[#f59e0b]">
          Demo preview — not yet connected to validation engine.
        </span>
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
                {c.check_id} — {c.check_name} ({c.layer})
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => c.check_id && previewRun(c.check_id)}
                disabled={serviceUnavailable}
              >
                Run Preview
              </Button>
            </div>
          ))}
        </div>
      )}

      {preview && (
        <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4">
          <p className="text-xs text-[#f59e0b] mb-2">
            Demo preview — not yet connected to validation engine.
          </p>
          <p className="text-sm text-[#f1f5f9]">
            <strong>{preview.status}</strong> — {preview.message}
          </p>
        </div>
      )}
    </div>
  );
}
