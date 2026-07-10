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

function layerBadgeVariant(layer: string): 'warning' | 'secondary' | 'primary' | 'default' {
  const l = layer.toLowerCase();
  if (l === 'bronze') return 'warning';
  if (l === 'silver') return 'secondary';
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

  // Reserved for future inline auth — today re-auth is via Connectors page + paste connection_id.
  // const [connectorPassword, setConnectorPassword] = useState('');
  // const authenticateConnector = async (...) => { ... };
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
    <div className="min-h-full p-6 space-y-6 animate-fade-in relative">
      <PageAssistant page="custom_checks" layer="silver" />

      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Custom Checks</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="text-sm text-[#6b7280] mt-1">
          Define domain-specific rules and test them against real validation data. Results are
          additive and do not change the engine trust score or verdict.
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

      {/* ── Define check form ── */}
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
            className={cn(
              'rounded-lg border bg-[#13141e] px-3 py-2 text-[#f1f5f9]',
              formErrors.check_name ? 'border-[#ef4444]' : 'border-[#252637]',
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
            <span className="text-[#f87171]">{formErrors.check_name}</span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
          Rule type
          <select
            className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
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
            className={cn(
              'rounded-lg border bg-[#13141e] px-3 py-2 text-[#f1f5f9]',
              formErrors.column ? 'border-[#ef4444]' : 'border-[#252637]',
            )}
            value={form.column}
            onChange={(e) => {
              setForm({ ...form, column: e.target.value });
              if (formErrors.column) {
                setFormErrors((prev) => ({ ...prev, column: undefined }));
              }
            }}
            placeholder="e.g. customer_id (unused for row_count_condition)"
            disabled={serviceUnavailable || form.rule_type === 'row_count_condition'}
            aria-invalid={Boolean(formErrors.column)}
          />
          {formErrors.column && (
            <span className="text-[#f87171]">{formErrors.column}</span>
          )}
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

      {/* ── Run scope selector ── */}
      {checks.length > 0 && (
        <div className="space-y-4 max-w-4xl">
          <h3 className="text-sm font-semibold text-[#f1f5f9]">Test data source</h3>
          <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
            Run to test against
            <select
              className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9]"
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
            <div className="rounded-lg border border-[#252637] bg-[#0f172a] px-4 py-3 space-y-2">
              <p className="text-xs leading-relaxed text-[#bfdbfe]">
                <strong>This run requires your original file.</strong> Choose it below to test
                against real upload data before you click <span className="font-semibold">Test Check</span>.
                The file is processed in-memory and not saved again. File identity is not verified —
                attach the same file used in the original run.
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="text-xs text-[#94a3b8]"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
              {uploadFile && (
                <p className="text-xs text-[#22c55e]">Selected: {uploadFile.name}</p>
              )}
            </div>
          )}

          {/* Connector run: session ID input */}
          {scope.type === 'connector' && (
            <div className="rounded-lg border border-[#252637] bg-[#0f172a] px-4 py-3 space-y-2">
              <p className="text-xs leading-relaxed text-[#bfdbfe]">
                <strong>This run requires an active database session.</strong> Test the connection
                on the Connectors page, then paste the session ID here before you click{' '}
                <span className="font-semibold">Test Check</span>. Passwords are never stored.
              </p>
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
              <label className="flex flex-col gap-1 text-xs text-[#94a3b8]">
                Connection ID (from Connectors page)
                <input
                  type="text"
                  className="rounded-lg border border-[#252637] bg-[#13141e] px-3 py-2 text-[#f1f5f9] font-mono text-xs"
                  value={connectorSessionId ?? ''}
                  onChange={(e) => {
                    setConnectorSessionId(e.target.value || null);
                  }}
                  placeholder="Paste connection ID from Connectors"
                />
              </label>
            </div>
          )}
        </div>
      )}

      {/* ── Saved checks list ── */}
      {checks.length > 0 && (
        <div className="space-y-4 max-w-4xl">
          <h3 className="text-sm font-semibold text-[#f1f5f9]">Saved checks</h3>
          <div className="flex flex-col gap-4">
            {checks.map((c) => (
              <Card key={c.check_id} className="p-0 overflow-hidden">
                <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-sm font-semibold text-[#f1f5f9]">
                        {checkDisplayName(c)}
                      </h4>
                      <Badge variant={layerBadgeVariant(c.layer)}>{c.layer}</Badge>
                    </div>
                    <p className="text-xs text-[#6b7280]">
                      {c.rule_type.replace(/_/g, ' ')}
                      {c.check_id ? (
                        <>
                          <span className="mx-1.5 text-[#4b5563]">·</span>
                          <span className="font-mono text-[#94a3b8]">{c.check_id}</span>
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
        <Card className="max-w-4xl space-y-4">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[#6b7280]">
            Latest Test Check Result
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={resultStatusVariant(result.status)} className="text-xs">
              {result.status}
            </Badge>
            <p className="text-sm font-medium text-[#f1f5f9]">{result.message}</p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-[#6b7280]">
                Observed
              </span>
              <span className="break-all text-sm text-[#f1f5f9]">
                {String(result.observed_value)}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-[#6b7280]">
                Expected
              </span>
              <span className="break-all text-sm text-[#f1f5f9]">
                {result.expected_condition}
              </span>
            </div>
          </div>
          {(result.data_source || result.scope_note) && (
            <div className="space-y-2 border-t border-[#252637] pt-4">
              {result.data_source && (
                <p className="text-xs leading-relaxed text-[#94a3b8]">
                  <span className="font-semibold text-[#bfdbfe]">Data source</span>
                  <span className="mx-1.5 text-[#4b5563]">·</span>
                  {result.data_source}
                </p>
              )}
              {result.scope_note && (
                <p className="text-xs leading-relaxed text-[#94a3b8]">
                  <span className="font-semibold text-[#fbbf24]">Scope note</span>
                  <span className="mx-1.5 text-[#4b5563]">·</span>
                  {result.scope_note}
                </p>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
