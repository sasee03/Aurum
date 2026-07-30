import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createCustomCheck,
  fetchRuns,
  listCustomChecks,
  runCustomCheck,
  runCustomCheckWithFile,
  type CustomCheck,
  type CustomCheckRunResult,
  type ValidationRunSummary,
} from '@/lib/aurumApi';
import { PageAssistant } from '@/components/common/PageAssistant';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { OLIST_DEMO_PROJECT_ID } from '@/components/cards/ProjectCard';
import { useAppMode } from '@/context/AppModeContext';
import { CUSTOM_CHECKS_UNAVAILABLE } from '@/utils/apiErrors';
import { formatRunOptionLabel, getRunDisplayName } from '@/utils/runLabels';
import { cn } from '@/utils/cn';

function layerBadgeVariant(layer: string): 'warning' | 'secondary' | 'primary' | 'accent' | 'default' {
  const l = layer.toLowerCase();
  if (l === 'bronze') return 'warning';
  if (l === 'silver') return 'accent';
  if (l === 'gold') return 'primary';
  return 'default';
}

function checkDisplayName(check: CustomCheck): string {
  const name = check.check_name?.trim();
  if (name) return name;
  return check.check_id || 'Untitled check';
}

function resultStatusVariant(status: string): 'pass' | 'failed' | 'warning' | 'secondary' {
  const u = status.toUpperCase();
  if (u === 'PASS') return 'pass';
  if (u === 'FAIL' || u === 'FAILED') return 'failed';
  if (u === 'SKIPPED') return 'secondary';
  return 'warning';
}

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

type RunScope =
  | { type: 'demo' }
  | { type: 'upload'; run: ValidationRunSummary }
  | { type: 'connector'; run: ValidationRunSummary };

function formatRunDataSource(run: ValidationRunSummary): string {
  return getRunDisplayName(run);
}

export function CustomChecksPage() {
  const navigate = useNavigate();
  const { displayMode, backendReachable } = useAppMode();
  const [form, setForm] = useState(EMPTY_FORM);
  const [checks, setChecks] = useState<CustomCheck[]>([]);
  const [runs, setRuns] = useState<ValidationRunSummary[]>([]);
  const [result, setResult] = useState<CustomCheckRunResult | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);
  const [formErrors, setFormErrors] = useState<{ check_name?: string; column?: string }>({});

  // Run-scope selector state.
  const [selectedRunId, setSelectedRunId] = useState<string>('demo');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [connectorSessionId, setConnectorSessionId] = useState<string | null>(null);

  const selectedRun: ValidationRunSummary | undefined = runs.find(
    (r) => r.run_id === selectedRunId,
  );
  const scope: RunScope = !selectedRun
    ? { type: 'demo' }
    : selectedRun.mode === 'upload'
      ? { type: 'upload', run: selectedRun }
      : selectedRun.mode === 'connector'
        ? { type: 'connector', run: selectedRun }
        : { type: 'demo' };

  const load = useCallback(async () => {
    if (!backendReachable) {
      setChecks([]);
      setServiceUnavailable(true);
      return;
    }
    try {
      const [checksData, runsData] = await Promise.all([listCustomChecks(), fetchRuns()]);
      setChecks(checksData.checks);
      setRuns(runsData.runs.filter((r) => ['upload', 'connector', 'demo'].includes(r.mode)));
      setServiceUnavailable(false);
    } catch {
      setChecks([]);
      setServiceUnavailable(true);
    }
  }, [backendReachable]);

  useEffect(() => {
    load();
  }, [load]);

  const columnRequired = form.rule_type !== 'row_count_condition';

  const save = async () => {
    setMessage(null);
    const errors: { check_name?: string; column?: string } = {};
    if (!form.check_name.trim()) {
      errors.check_name = 'Enter a check name.';
    }
    if (columnRequired && !form.column.trim()) {
      errors.column = 'Enter a column name for this rule type.';
    }
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }
    setFormErrors({});
    try {
      const saved = await createCustomCheck({
        ...form,
        check_name: form.check_name.trim(),
        column: form.column.trim(),
      });
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
      let runResult: CustomCheckRunResult;

      if (scope.type === 'demo') {
        runResult = await runCustomCheck(checkId);
      } else if (scope.type === 'upload') {
        if (!uploadFile) {
          setResult({
            check_id: checkId,
            status: 'SKIPPED',
            message:
              'Re-select the original CSV file to run this check against the upload data.',
            observed_value: null,
            expected_condition: '',
            data_source: formatRunDataSource(scope.run),
            scope_note:
              'File identity is not verified — this checks whatever file you attach, ' +
              'not necessarily the original upload. Ensure you\'re re-uploading the same ' +
              'file used in the original run.',
          });
          return;
        }
        runResult = await runCustomCheckWithFile(checkId, scope.run.run_id, uploadFile);
      } else {
        // connector
        if (!connectorSessionId) {
          setResult({
            check_id: checkId,
            status: 'SKIPPED',
            message:
              'Connector session is not active. Re-test the connection via the Connectors page, ' +
              'then enter the session connection ID below.',
            observed_value: null,
            expected_condition: '',
            data_source: formatRunDataSource(scope.run),
            scope_note: 'Connector passwords are not persisted. Re-authenticate to continue.',
          });
          return;
        }
        runResult = await runCustomCheck(checkId, {
          runId: scope.run.run_id,
          connectionId: connectorSessionId,
        });
      }

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
    <div className="min-h-full p-6 space-y-6 animate-fade-in relative bg-[#0b0f19]">
      <PageAssistant page="custom_checks" layer="silver" />

      <div className="border-b border-[#1e293b] pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Custom Validation Checks</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="text-sm text-[#94a3b8] mt-1">
          Define domain-specific rules and test them against real validation data. Results are
          additive and do not alter the underlying system verdict.
        </p>
      </div>

      {!backendReachable && (
        <p className="text-xs text-[#94a3b8] rounded-xl border border-[#1e293b] bg-[#111827] px-4 py-3">
          Custom checks require active backend API server connection.
        </p>
      )}

      {serviceUnavailable && backendReachable && (
        <p className="text-xs text-[#ef4444] rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 px-4 py-3">
          {CUSTOM_CHECKS_UNAVAILABLE}
        </p>
      )}

      {/* ── Define check form ── */}
      <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm max-w-4xl space-y-4">
        <h3 className="text-base font-semibold text-[#f8fafc]">Create New Check</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Layer
            <select
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={form.layer}
              onChange={(e) => setForm({ ...form, layer: e.target.value as CustomCheck['layer'] })}
              disabled={serviceUnavailable}
            >
              <option value="bronze">Bronze</option>
              <option value="silver">Silver</option>
              <option value="gold">Gold</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Check Name
            <input
              className={cn(
                'rounded-lg border bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]',
                formErrors.check_name ? 'border-[#ef4444]' : 'border-[#273549]',
              )}
              value={form.check_name}
              onChange={(e) => {
                setForm({ ...form, check_name: e.target.value });
                if (formErrors.check_name) {
                  setFormErrors((prev) => ({ ...prev, check_name: undefined }));
                }
              }}
              disabled={serviceUnavailable}
              aria-invalid={Boolean(formErrors.check_name)}
            />
            {formErrors.check_name && (
              <span className="text-[#ef4444]">{formErrors.check_name}</span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Rule Type
            <select
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={form.rule_type}
              onChange={(e) => {
                const next = e.target.value;
                setForm({ ...form, rule_type: next });
                if (next === 'row_count_condition' && formErrors.column) {
                  setFormErrors((prev) => ({ ...prev, column: undefined }));
                }
              }}
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
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value })}
              disabled={serviceUnavailable}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Target Column
            <input
              className={cn(
                'rounded-lg border bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]',
                formErrors.column ? 'border-[#ef4444]' : 'border-[#273549]',
              )}
              value={form.column}
              onChange={(e) => {
                setForm({ ...form, column: e.target.value });
                if (formErrors.column) {
                  setFormErrors((prev) => ({ ...prev, column: undefined }));
                }
              }}
              placeholder="e.g. customer_id"
              disabled={serviceUnavailable || form.rule_type === 'row_count_condition'}
              aria-invalid={Boolean(formErrors.column)}
            />
            {formErrors.column && (
              <span className="text-[#ef4444]">{formErrors.column}</span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Operator
            <input
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={form.operator}
              onChange={(e) => setForm({ ...form, operator: e.target.value })}
              placeholder=">, >=, <, <=, ==, or between"
              disabled={serviceUnavailable}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8] md:col-span-2">
            Expected Value
            <input
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={form.value}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
              placeholder="e.g. 0 | 1,100 | UK,France,Germany"
              disabled={serviceUnavailable}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8] md:col-span-2">
            Description
            <textarea
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              disabled={serviceUnavailable}
            />
          </label>
        </div>

        {sqlSelected && (
          <p className="text-xs text-[#f59e0b] rounded-lg border border-[#f59e0b]/30 bg-[#f59e0b]/10 p-3">
            SQL-based checks (custom_sql_demo) are not yet supported.
          </p>
        )}

        <div className="pt-2 flex items-center justify-between">
          <Button variant="primary" size="md" onClick={save} disabled={serviceUnavailable}>
            Save Custom Check
          </Button>
          {message && <p className="text-xs text-[#10b981] font-semibold">{message}</p>}
        </div>
      </div>

      {/* ── Run scope selector ── */}
      {checks.length > 0 && (
        <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm space-y-4 max-w-4xl">
          <h3 className="text-base font-semibold text-[#f8fafc]">Test Data Source</h3>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Target Validation Run
            <select
              className="rounded-lg border border-[#273549] bg-[#131a29] px-3 py-2 text-[#f8fafc] focus:outline-none focus:border-[#3b82f6]"
              value={selectedRunId}
              onChange={(e) => {
                setSelectedRunId(e.target.value);
                setUploadFile(null);
                setConnectorSessionId(null);
                setResult(null);
              }}
              disabled={serviceUnavailable}
            >
              <option value="demo">Sample dataset (default)</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {formatRunOptionLabel(r)}
                </option>
              ))}
            </select>
          </label>

          {/* Upload run: re-attach file */}
          {scope.type === 'upload' && (
            <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4 space-y-2">
              <p className="text-xs leading-relaxed text-[#94a3b8]">
                Choose file below to test against upload data before clicking <span className="font-semibold text-[#f8fafc]">Test Check</span>.
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="text-xs text-[#94a3b8]"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
              {uploadFile && (
                <p className="text-xs text-[#10b981]">Selected: {uploadFile.name}</p>
              )}
            </div>
          )}

          {/* Connector run: session ID input */}
          {scope.type === 'connector' && (
            <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4 space-y-3">
              <p className="text-xs leading-relaxed text-[#94a3b8]">
                Active PostgreSQL session required. Paste session connection ID below.
              </p>
              <div className="flex gap-3">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    navigate(
                      `/projects/${scope.run.project_id ?? OLIST_DEMO_PROJECT_ID}/connect?source=postgresql`,
                    )
                  }
                >
                  Open Connectors
                </Button>
                <input
                  type="text"
                  className="flex-1 rounded-lg border border-[#273549] bg-[#0b0f19] px-3 py-1.5 text-[#f8fafc] font-mono text-xs focus:outline-none"
                  value={connectorSessionId ?? ''}
                  onChange={(e) => {
                    setConnectorSessionId(e.target.value || null);
                  }}
                  placeholder="Paste Connection ID from Connectors"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Saved checks list ── */}
      {checks.length > 0 && (
        <div className="space-y-4 max-w-4xl">
          <h3 className="text-base font-semibold text-[#f8fafc]">Saved Custom Checks</h3>
          <div className="flex flex-col gap-3">
            {checks.map((c) => (
              <Card key={c.check_id} className="p-4 bg-[#111827] border-[#1e293b]">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 flex-col gap-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-sm font-semibold text-[#f8fafc]">
                        {checkDisplayName(c)}
                      </h4>
                      <Badge variant={layerBadgeVariant(c.layer)}>{c.layer}</Badge>
                    </div>
                    <p className="text-xs text-[#94a3b8] font-mono">
                      {c.rule_type.replace(/_/g, ' ')}
                      {c.check_id ? (
                        <>
                          <span className="mx-1.5 text-[#64748b]">·</span>
                          <span className="text-[#06b6d4]">{c.check_id}</span>
                        </>
                      ) : null}
                    </p>
                    {c.description?.trim() ? (
                      <p className="text-xs leading-relaxed text-[#94a3b8]">{c.description}</p>
                    ) : null}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="shrink-0 self-start sm:self-center"
                    onClick={() => c.check_id && testCheck(c.check_id)}
                    disabled={serviceUnavailable || runningId === c.check_id}
                  >
                    {runningId === c.check_id ? 'Running…' : 'Test Check'}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* ── Result panel ── */}
      {result && (
        <Card className="max-w-4xl space-y-4 bg-[#111827] border-[#1e293b] p-6 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[#64748b]">
            Latest Test Check Result
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={resultStatusVariant(result.status)} className="text-xs">
              {result.status}
            </Badge>
            <p className="text-sm font-semibold text-[#f8fafc]">{result.message}</p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 font-mono">
            <div className="flex flex-col gap-1 p-3 rounded-lg border border-[#1e293b] bg-[#131a29]">
              <span className="text-[11px] font-semibold uppercase text-[#64748b]">
                Observed Value
              </span>
              <span className="break-all text-xs text-[#f8fafc]">
                {String(result.observed_value)}
              </span>
            </div>
            <div className="flex flex-col gap-1 p-3 rounded-lg border border-[#1e293b] bg-[#131a29]">
              <span className="text-[11px] font-semibold uppercase text-[#64748b]">
                Expected Condition
              </span>
              <span className="break-all text-xs text-[#f8fafc]">
                {result.expected_condition}
              </span>
            </div>
          </div>
          {(result.data_source || result.scope_note) && (
            <div className="space-y-2 border-t border-[#1e293b] pt-4 text-xs text-[#94a3b8]">
              {result.data_source && (
                <p>
                  <span className="font-semibold text-[#3b82f6]">Data Source:</span> {result.data_source}
                </p>
              )}
              {result.scope_note && (
                <p>
                  <span className="font-semibold text-[#f59e0b]">Scope Note:</span> {result.scope_note}
                </p>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
