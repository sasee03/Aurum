import { useState, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { CheckCircle2, ArrowRight, Upload, Eye, Database } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { useAppMode } from '@/context/AppModeContext';
import {
  CsvUploadError,
  sourceConnect,
  uploadDatasetCsv,
  type CsvUploadMismatch,
} from '@/lib/aurumApi';
import { calmApiMessage, ApiError } from '@/utils/apiErrors';
import connectorsData from '@/mocks/connectors.json';
import type { Connector } from '@/types';

const connectors = connectorsData as Connector[];

// ────────────────────────────────────────────
// Connector Card
// ────────────────────────────────────────────
function ConnectorCard({
  connector,
  selected,
  compact = false,
  onSelect,
}: {
  connector: Connector;
  selected: boolean;
  compact?: boolean;
  onSelect: () => void;
}) {
  const isPreview = connector.type === 'preview';
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      title={isPreview ? `${connector.name} — coming soon` : undefined}
      className={cn(
        'relative w-full rounded-xl border transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
        compact
          ? 'flex min-h-24 flex-col items-center justify-center gap-2 p-3 text-center'
          : 'flex min-h-20 items-center gap-3 p-4 text-left',
        selected
          ? 'border-[#6366f1] bg-[#6366f1]/10 shadow-[0_0_12px_rgba(99,102,241,0.15)]'
          : 'border-[#252637] bg-[#13141e] hover:border-[#6366f1]/30 hover:bg-[#1a1b28]',
        isPreview && !selected && 'opacity-70',
      )}
    >
      {isPreview && (
        <span className="absolute right-1.5 top-1.5 rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[#6b7280] bg-[#1a1b28] border border-[#252637]">
          Soon
        </span>
      )}
      <div
        className={cn(
          'flex shrink-0 items-center justify-center rounded-lg font-bold transition-colors',
          compact ? 'h-9 w-9 text-xs' : 'h-11 w-11 text-sm',
          selected
            ? 'bg-[#6366f1] text-white'
            : 'bg-[#1a1b28] text-[#6366f1] border border-[#252637]',
        )}
      >
        {connector.icon}
      </div>
      <div className={cn(!compact && 'min-w-0 flex-1')}>
        <span
          className={cn(
            'block font-semibold',
            compact ? 'text-[11px]' : 'text-sm',
            selected ? 'text-[#f1f5f9]' : 'text-[#94a3b8]',
          )}
        >
          {connector.name}
        </span>
        {!compact && (
          <span className="mt-1 block text-xs leading-5 text-[#6b7280]">
            {connector.description}
          </span>
        )}
      </div>
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
      await uploadDatasetCsv(file, projectId);
      toast.success('CSV file uploaded and validated.');
    } catch (err) {
      if (err instanceof CsvUploadError) {
        setMismatch(err.mismatch);
      } else {
        toast.error(calmApiMessage(err, 'Upload failed. Check the backend and database.'));
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
        <button
          type="button"
          title="Column preview coming soon"
          aria-label="Preview File — coming soon"
          onClick={() =>
            toast('Column preview coming soon — upload and validate to continue.', {
              icon: 'ℹ️',
            })
          }
          className="flex items-center gap-1.5 rounded-lg border border-[#252637] bg-[#13141e] px-3 py-1.5 text-xs font-semibold text-[#6b7280] opacity-50 cursor-not-allowed"
        >
          <Eye size={14} /> Preview File
        </button>
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

  const [host, setHost] = useState('localhost');
  const [port, setPort] = useState('');
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [status, setStatus] = useState<ConnectStatus>('idle');
  const [error, setError] = useState<string | null>(null);

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

    const submittedPassword = password;
    setPassword('');
    setStatus('testing');
    setError(null);

    try {
      const res = await sourceConnect({
        host: host.trim(),
        port: portNum,
        database: database.trim(),
        user: username.trim(),
        password: submittedPassword,
      });

      if (!res.connected) {
        setStatus('failed');
        setError(res.message || 'Connection failed.');
        toast.error(res.message || 'Connection failed.');
        return;
      }

      setStatus('connected');
      toast.success('Connection verified.');
    } catch (err: any) {
      setStatus('failed');
      let msg = 'Connection could not be verified due to an unexpected server error.';
      if (err instanceof ApiError) {
        if (err.httpStatus === 401 || err.httpStatus === 404 || err.httpStatus === 503) {
          msg = err.userMessage;
        }
      }
      setError(msg);
      toast.error(msg);
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
      </div>

      <p className="text-xs text-[#6b7280] italic">
        Connects to YOUR Postgres (host/port you enter). Password is never stored or returned —
        re-test after an API restart.
      </p>

      {status === 'connected' && (
        <div className="rounded-xl border border-[#22c55e]/30 bg-[#22c55e]/10 p-4 space-y-3 mt-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#4ade80]">
            <CheckCircle2 size={18} />
            Connection verified.
          </div>
          <p className="text-xs text-[#cbd5e1] leading-relaxed">
            For this demo, Bronze uses Aurum&apos;s configured Source environment. External database handoff will be supported separately.
          </p>
          <div className="pt-2 flex justify-end">
            <Button
              variant="primary"
              rightIcon={<ArrowRight size={16} />}
              onClick={() => navigate(`/projects/${projectId}/bronze`)}
            >
              Continue to Bronze
            </Button>
          </div>
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
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">Coming soon</Badge>
        <span className="text-xs text-[#6b7280]">{connector.name}</span>
      </div>
      <p className="text-sm text-[#94a3b8]">{connector.description}</p>
      <p className="text-sm text-[#6b7280]">
        Connection setup for {connector.name} is not available yet. Use CSV upload or
        PostgreSQL for live validation in this build.
      </p>
    </div>
  );
}

// ────────────────────────────────────────────
// Main Connectors Page
// ────────────────────────────────────────────
export function ConnectorsPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const { displayMode } = useAppMode();
  const requestedSource = searchParams.get('source');
  const [selected, setSelected] = useState<string | null>(() => {
    if (requestedSource === 'csv' || requestedSource === 'postgresql') return requestedSource;
    return null;
  });

  const selectedConnector = connectors.find((c) => c.id === selected);
  const availableConnectors = connectors.filter((connector) => connector.type !== 'preview');
  const plannedConnectors = connectors.filter((connector) => connector.type === 'preview');

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 scrollbar-thin sm:px-6 lg:py-8">
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-6">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-bold text-[#f1f5f9]">Connect Data Sources</h2>
              <DataSourceBadge mode={displayMode} />
            </div>
            <p className="mt-1 text-sm text-[#6b7280]">
              Upload a CSV or connect a live database table for validation.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
            <aside className="space-y-5">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <Database size={15} className="text-[#6366f1]" />
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                    Available now
                  </h3>
                </div>
                <div className="space-y-3">
                  {availableConnectors.map((connector) => (
                    <ConnectorCard
                      key={connector.id}
                      connector={connector}
                      selected={selected === connector.id}
                      onSelect={() => setSelected(connector.id)}
                    />
                  ))}
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                  Coming soon
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  {plannedConnectors.map((connector) => (
                    <ConnectorCard
                      key={connector.id}
                      connector={connector}
                      selected={selected === connector.id}
                      compact
                      onSelect={() => setSelected(connector.id)}
                    />
                  ))}
                </div>
              </div>
            </aside>

            <section className="min-w-0 animate-slide-up rounded-xl border border-[#252637] bg-[#13141e] p-6">
              {selectedConnector ? (
                <>
                  <div className="mb-6 flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#6366f1] text-sm font-bold text-white">
                      {selectedConnector.icon}
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-[#f1f5f9]">
                        {selectedConnector.name}
                      </h3>
                      <p className="text-xs text-[#6b7280]">{selectedConnector.description}</p>
                    </div>
                  </div>

                  {selectedConnector.type === 'csv' && <CsvPanel projectId={id ?? 'demo'} />}
                  {selectedConnector.type === 'postgresql' && (
                    <PostgresPanel projectId={id ?? 'demo'} />
                  )}
                  {selectedConnector.type === 'preview' && (
                    <PreviewConnectorPanel connector={selectedConnector} />
                  )}
                </>
              ) : (
                <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
                  <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-[#252637] bg-[#1a1b28] text-[#6366f1]">
                    <Database size={22} />
                  </div>
                  <h3 className="text-base font-semibold text-[#f1f5f9]">
                    Choose a data source
                  </h3>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-[#6b7280]">
                    Select CSV for file upload or PostgreSQL to test a live database connection.
                  </p>
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
