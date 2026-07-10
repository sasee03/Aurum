import { useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, ArrowRight, Upload, Eye } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { useAppMode } from '@/context/AppModeContext';
import {
  CsvUploadError,
  listPostgresSchemas,
  listPostgresTables,
  testPostgresConnection,
  uploadDatasetCsv,
  validatePostgresTable,
  type CsvUploadMismatch,
  type PostgresTableEntry,
} from '@/lib/aurumApi';
import connectorsData from '@/mocks/connectors.json';
import type { Connector } from '@/types';

const connectors = connectorsData as Connector[];

// ────────────────────────────────────────────
// Connector Card
// ────────────────────────────────────────────
function ConnectorCard({
  connector,
  selected,
  onSelect,
}: {
  connector: Connector;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'relative flex flex-col items-center justify-center gap-2 rounded-xl border p-5 text-center transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
        selected
          ? 'border-[#6366f1] bg-[#6366f1]/10 shadow-[0_0_12px_rgba(99,102,241,0.15)]'
          : 'border-[#252637] bg-[#13141e] hover:border-[#6366f1]/30 hover:bg-[#1a1b28]',
      )}
    >
      <div
        className={cn(
          'flex h-10 w-10 items-center justify-center rounded-lg text-sm font-bold transition-colors',
          selected
            ? 'bg-[#6366f1] text-white'
            : 'bg-[#1a1b28] text-[#6366f1] border border-[#252637]',
        )}
      >
        {connector.icon}
      </div>
      <span className={cn('text-xs font-semibold', selected ? 'text-[#f1f5f9]' : 'text-[#94a3b8]')}>
        {connector.name}
      </span>
    </button>
  );
}

// ────────────────────────────────────────────
// CSV upload — wired to POST /datasets/upload
// ────────────────────────────────────────────
function CsvPanel({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { canRunValidation } = useAppMode();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [mismatch, setMismatch] = useState<CsvUploadMismatch | null>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setFileName(selected.name);
      setMismatch(null);
    }
  }

  async function handleUpload() {
    if (!file) {
      toast.error('Select a CSV file first.');
      return;
    }
    if (!canRunValidation) {
      toast.error('Database is unreachable — start PostgreSQL and check /health.');
      return;
    }
    setUploading(true);
    setMismatch(null);
    try {
      const report = await uploadDatasetCsv(file, projectId);
      toast.success('CSV validated — proceeding to pipeline configuration.');
      navigate(
        `/projects/${projectId}/validate/config?runId=${encodeURIComponent(report.run_id)}`,
      );
    } catch (err) {
      if (err instanceof CsvUploadError) {
        setMismatch(err.mismatch);
      } else {
        toast.error('Upload failed. Check the backend and database.');
      }
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Input label="Dataset Name" placeholder="e.g. orders_2024" />

      {/* File upload */}
      <div className="space-y-1.5">
        <span className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
          Upload CSV
        </span>
        <label
          htmlFor="csv-upload"
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-[#252637] bg-[#1a1b28] py-6 px-4 text-center transition-colors hover:border-[#6366f1]/50 hover:bg-[#252637]/40"
        >
          <Upload size={20} className="text-[#6b7280]" />
          <span className="text-sm text-[#6b7280]">
            {fileName ? (
              <span className="text-[#6366f1] font-medium">{fileName}</span>
            ) : (
              <>
                <span className="text-[#f1f5f9]">Click to upload</span> or drag and drop
              </>
            )}
          </span>
          <span className="text-[11px] text-[#4b5563]">CSV files only — must match the expected orders format</span>
          <input
            ref={fileInputRef}
            id="csv-upload"
            type="file"
            accept=".csv"
            className="sr-only"
            onChange={handleFileChange}
            aria-label="Upload CSV file"
          />
        </label>
      </div>

      {mismatch && (
        <div className="rounded-lg border border-[#ef4444]/40 bg-[#450a0a]/40 p-4 space-y-2">
          <p className="text-sm font-semibold text-[#fca5a5]">{mismatch.error}</p>
          {mismatch.missing_columns.length > 0 && (
            <p className="text-xs text-[#fecaca]">
              Missing columns: {mismatch.missing_columns.join(', ')}
            </p>
          )}
          <p className="text-xs text-[#94a3b8]">
            Expected: {mismatch.expected_columns.join(', ')}
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
            Delimiter
          </label>
          <select
            className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
            aria-label="Delimiter"
            disabled
          >
            <option value=",">Comma (,)</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
            Encoding
          </label>
          <select
            className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
            aria-label="Encoding"
            disabled
          >
            <option value="utf-8">UTF-8</option>
          </select>
        </div>
      </div>

      <label className="flex items-center gap-2.5 cursor-not-allowed opacity-60">
        <input type="checkbox" defaultChecked disabled className="h-4 w-4 rounded border-[#252637] accent-[#6366f1]" />
        <span className="text-sm text-[#94a3b8]">First row is header</span>
      </label>

      <div className="flex items-center gap-2 pt-2 border-t border-[#252637]">
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<Eye size={14} />}
          onClick={() => toast('Column preview coming soon', { icon: '👁' })}
        >
          Preview File
        </Button>
        <Button
          variant="primary"
          size="sm"
          isLoading={uploading}
          disabled={!file || !canRunValidation}
          onClick={handleUpload}
        >
          Validate &amp; Run
        </Button>
      </div>

      <p className="text-xs text-[#6b7280] italic">
        Your file must match the expected column layout. Mismatched files are rejected — your
        data is never swapped for a sample dataset.
      </p>

      <Button
        variant="secondary"
        className="w-full"
        rightIcon={<ArrowRight size={16} />}
        onClick={() => navigate(`/projects/${projectId}/select`)}
      >
        Try the sample dataset instead
      </Button>
    </div>
  );
}

// ────────────────────────────────────────────
// PostgreSQL Config Panel — user-supplied connection (not app DATABASE_URL)
// ────────────────────────────────────────────
type ConnectStatus = 'idle' | 'testing' | 'connected' | 'failed';

function PostgresPanel({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { canRunValidation } = useAppMode();

  const [host, setHost] = useState('localhost');
  const [port, setPort] = useState('');
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [status, setStatus] = useState<ConnectStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [connectionId, setConnectionId] = useState<string | null>(null);

  const [schemas, setSchemas] = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState('');
  const [tables, setTables] = useState<PostgresTableEntry[]>([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [validating, setValidating] = useState(false);
  const [mismatch, setMismatch] = useState<CsvUploadMismatch | null>(null);

  async function handleTest() {
    if (!host.trim() || !port.trim() || !database.trim() || !username.trim()) {
      toast.error('Host, port, database, and username are required.');
      return;
    }
    const portNum = Number(port);
    if (!Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
      toast.error('Port must be an integer between 1 and 65535.');
      return;
    }

    setStatus('testing');
    setError(null);
    setConnectionId(null);
    setSchemas([]);
    setTables([]);
    setSelectedSchema('');
    setSelectedTable('');
    setMismatch(null);

    try {
      const result = await testPostgresConnection({
        host: host.trim(),
        port: portNum,
        database: database.trim(),
        username: username.trim(),
        password,
        project_id: projectId,
      });
      // Clear password from UI state after submission — never show it back.
      setPassword('');

      if (!result.connected) {
        setStatus('failed');
        setError(result.error);
        toast.error(result.error);
        return;
      }

      setStatus('connected');
      setConnectionId(result.connection_id);
      toast.success('Connected to PostgreSQL.');

      setLoadingMeta(true);
      try {
        const schemaRes = await listPostgresSchemas(result.connection_id);
        setSchemas(schemaRes.schemas);
        const preferred = schemaRes.schemas.includes('public')
          ? 'public'
          : (schemaRes.schemas[0] ?? '');
        setSelectedSchema(preferred);
        if (preferred) {
          const tableRes = await listPostgresTables(result.connection_id, preferred);
          setTables(tableRes.tables);
        }
      } catch {
        toast.error('Connected, but schema listing failed. Re-test the connection.');
      } finally {
        setLoadingMeta(false);
      }
    } catch {
      setStatus('failed');
      setError('Backend API is not running or the request timed out.');
      toast.error('Backend API is not running. Check the connection.');
      setPassword('');
    }
  }

  async function handleSchemaChange(nextSchema: string) {
    setSelectedSchema(nextSchema);
    setSelectedTable('');
    setTables([]);
    setMismatch(null);
    if (!connectionId || !nextSchema) return;
    setLoadingMeta(true);
    try {
      const tableRes = await listPostgresTables(connectionId, nextSchema);
      setTables(tableRes.tables);
    } catch {
      toast.error('Failed to list tables. Re-test the connection.');
    } finally {
      setLoadingMeta(false);
    }
  }

  async function handleValidate() {
    if (!connectionId || !selectedSchema || !selectedTable) {
      toast.error('Select a schema and table first.');
      return;
    }
    if (!canRunValidation) {
      toast.error('Aurum database is unreachable — start PostgreSQL and check /health.');
      return;
    }
    setValidating(true);
    setMismatch(null);
    try {
      const report = await validatePostgresTable({
        connection_id: connectionId,
        schema: selectedSchema,
        table: selectedTable,
        project_id: projectId,
      });
      toast.success('Table validated — opening quality report.');
      navigate(
        `/projects/${projectId}/report/quality?runId=${encodeURIComponent(report.run_id)}`,
      );
    } catch (err) {
      if (err instanceof CsvUploadError) {
        setMismatch(err.mismatch);
      } else {
        toast.error('Validation failed. Check the backend and database.');
      }
    } finally {
      setValidating(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2">
          <Input
            label="Host"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="localhost"
            autoComplete="off"
          />
        </div>
        <Input
          label="Port"
          type="number"
          value={port}
          onChange={(e) => setPort(e.target.value)}
          placeholder="e.g. 5432"
          autoComplete="off"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Input
          label="Database"
          value={database}
          onChange={(e) => setDatabase(e.target.value)}
          placeholder="your_database"
          autoComplete="off"
        />
        <Input
          label="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="postgres"
          autoComplete="off"
        />
      </div>
      <Input
        label="Password"
        type={showPassword ? 'text' : 'password'}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Enter password"
        autoComplete="new-password"
        rightIcon={
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="text-xs text-[#6b7280] hover:text-[#f1f5f9] transition-colors"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? 'Hide' : 'Show'}
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-[#252637]">
        <Button variant="secondary" isLoading={status === 'testing'} onClick={handleTest} size="sm">
          {status === 'connected' ? (
            <>
              <CheckCircle2 size={14} className="text-[#22c55e]" />
              <span className="text-[#22c55e]">Connected</span>
            </>
          ) : status === 'testing' ? (
            'Testing…'
          ) : (
            'Test Connection'
          )}
        </Button>
        {status === 'failed' && error && (
          <span className="text-xs text-[#ef4444]" role="alert">
            Failed: {error}
          </span>
        )}
        {status === 'connected' && connectionId && (
          <span className="text-xs text-[#6b7280]">Session {connectionId}</span>
        )}
      </div>

      <p className="text-xs text-[#6b7280] italic">
        Connects to YOUR Postgres (host/port you enter). Password is never stored or returned —
        re-test after an API restart.
      </p>

      {status === 'connected' && (
        <div className="space-y-3 pt-2 border-t border-[#252637]">
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                Schema
              </label>
              <select
                className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:outline-none"
                value={selectedSchema}
                disabled={loadingMeta || schemas.length === 0}
                onChange={(e) => handleSchemaChange(e.target.value)}
              >
                {schemas.length === 0 && <option value="">No schemas</option>}
                {schemas.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                Table
              </label>
              <select
                className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:outline-none"
                value={selectedTable}
                disabled={loadingMeta || tables.length === 0}
                onChange={(e) => {
                  setSelectedTable(e.target.value);
                  setMismatch(null);
                }}
              >
                <option value="">Select a table</option>
                {tables.map((t) => (
                  <option key={`${t.schema}.${t.table}`} value={t.table}>
                    {t.table}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {mismatch && (
            <div className="rounded-md border border-[#7f1d1d] bg-[#450a0a] p-3 space-y-1">
              <p className="text-sm font-semibold text-[#fecaca]">Schema mismatch</p>
              <p className="text-xs text-[#fca5a5]">{mismatch.error}</p>
              {mismatch.missing_columns.length > 0 && (
                <p className="text-xs text-[#fca5a5]">
                  Missing: {mismatch.missing_columns.join(', ')}
                </p>
              )}
            </div>
          )}

          <Button
            variant="primary"
            className="w-full"
            isLoading={validating}
            disabled={!selectedTable || validating}
            rightIcon={<ArrowRight size={16} />}
            onClick={handleValidate}
          >
            Validate this table
          </Button>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────
// Connector config panel for non-CSV/non-Postgres connectors
// ────────────────────────────────────────────
function PreviewConnectorPanel({ connector }: { connector: Connector }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-[#94a3b8]">{connector.description}</p>
      <p className="text-sm text-[#6b7280]">
        Connection configuration for {connector.name} is not available in the current build.
      </p>
    </div>
  );
}

// ────────────────────────────────────────────
// Main Connectors Page
// ────────────────────────────────────────────
export function ConnectorsPage() {
  const { id } = useParams<{ id: string }>();
  const { displayMode } = useAppMode();
  const [selected, setSelected] = useState<string | null>(null);

  const selectedConnector = connectors.find((c) => c.id === selected);

  return (
    <div className="min-h-full px-6 py-8 animate-fade-in">
      {/* Page Header */}
      <div className="mb-8">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Connect Data Sources</h2>
          <DataSourceBadge mode={displayMode} />
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Select a system to configure your connection.
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Connector Grid */}
        <div className="w-full lg:w-80 flex-shrink-0">
          <div className="grid grid-cols-2 gap-3">
            {connectors.map((connector) => (
              <ConnectorCard
                key={connector.id}
                connector={connector}
                selected={selected === connector.id}
                onSelect={() => setSelected(connector.id)}
              />
            ))}
          </div>
          {!selected && (
            <p className="mt-4 text-xs text-[#4b5563] text-center">
              Select a connector above to configure it.
            </p>
          )}
        </div>

        {/* Config Panel */}
        {selectedConnector && (
          <div className="flex-1 animate-slide-up">
            <div className="rounded-xl border border-[#252637] bg-[#13141e] p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#6366f1] text-sm font-bold text-white">
                  {selectedConnector.icon}
                </div>
                <h3 className="text-base font-semibold text-[#f1f5f9]">{selectedConnector.name}</h3>
              </div>

              {selectedConnector.type === 'csv' && <CsvPanel projectId={id ?? 'demo'} />}
              {selectedConnector.type === 'postgresql' && (
                <PostgresPanel projectId={id ?? 'demo'} />
              )}
              {selectedConnector.type === 'preview' && (
                <PreviewConnectorPanel connector={selectedConnector} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
