import { useState, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { CheckCircle2, ArrowRight, Upload, Eye, Database, Server } from 'lucide-react';
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
  testPostgresConnection,
  uploadDatasetCsv,
  type CsvUploadMismatch,
  type PostgresTestSuccess,
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
        'relative w-full rounded-xl border transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#3b82f6] cursor-pointer select-none',
        compact
          ? 'flex min-h-24 flex-col items-center justify-center gap-2 p-3 text-center'
          : 'flex min-h-20 items-center gap-3.5 p-4 text-left',
        selected
          ? 'border-[#3b82f6] bg-[#2563eb]/15 shadow-[0_0_16px_rgba(37,99,235,0.2)]'
          : 'border-[#1e293b] bg-[#111827] hover:border-[#3b82f6]/40 hover:bg-[#131a29]',
        isPreview && !selected && 'opacity-70',
      )}
    >
      {isPreview && (
        <span className="absolute right-2 top-2 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[#64748b] bg-[#131a29] border border-[#273549]">
          Soon
        </span>
      )}
      <div
        className={cn(
          'flex shrink-0 items-center justify-center rounded-lg font-bold transition-colors',
          compact ? 'h-9 w-9 text-xs' : 'h-11 w-11 text-sm',
          selected
            ? 'bg-[#2563eb] text-white shadow-[0_0_12px_rgba(37,99,235,0.4)]'
            : 'bg-[#131a29] text-[#3b82f6] border border-[#273549]',
        )}
      >
        {connector.icon}
      </div>
      <div className={cn(!compact && 'min-w-0 flex-1')}>
        <span
          className={cn(
            'block font-semibold',
            compact ? 'text-[11px]' : 'text-sm',
            selected ? 'text-[#f8fafc]' : 'text-[#94a3b8]',
          )}
        >
          {connector.name}
        </span>
        {!compact && (
          <span className="mt-1 block text-xs leading-5 text-[#64748b]">
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
      <Input label="Dataset Name" placeholder="e.g. events_2024" />

      {/* File upload */}
      <div className="space-y-1.5">
        <span className="text-xs font-medium text-[#94a3b8]">
          Upload CSV
        </span>
        <label
          htmlFor="csv-upload"
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[#273549] bg-[#131a29] py-8 px-4 text-center transition-colors hover:border-[#3b82f6]/50 hover:bg-[#1f293d]"
        >
          <Upload size={24} className="text-[#3b82f6]" />
          <span className="text-sm text-[#94a3b8]">
            {fileName ? (
              <span className="text-[#3b82f6] font-semibold">{fileName}</span>
            ) : (
              <>
                <span className="text-[#f8fafc] font-medium">Click to upload</span> or drag and drop
              </>
            )}
          </span>
          <span className="text-[11px] text-[#64748b]">CSV files only — unsupported layouts are rejected explicitly</span>
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
        <div className="rounded-xl border border-[#ef4444]/40 bg-[#ef4444]/10 p-4 space-y-2">
          <p className="text-sm font-semibold text-[#ef4444]">{mismatch.error}</p>
          {mismatch.missing_columns.length > 0 && (
            <p className="text-xs text-[#fca5a5]">
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
          <label className="text-xs font-medium text-[#94a3b8]">
            Delimiter
          </label>
          <select
            className="w-full rounded-lg border border-[#273549] bg-[#131a29] px-3.5 py-2.5 text-sm text-[#f8fafc] focus:border-[#3b82f6] focus:outline-none"
            aria-label="Delimiter"
            disabled
          >
            <option value=",">Comma (,)</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-[#94a3b8]">
            Encoding
          </label>
          <select
            className="w-full rounded-lg border border-[#273549] bg-[#131a29] px-3.5 py-2.5 text-sm text-[#f8fafc] focus:border-[#3b82f6] focus:outline-none"
            aria-label="Encoding"
            disabled
          >
            <option value="utf-8">UTF-8</option>
          </select>
        </div>
      </div>

      <label className="flex items-center gap-2.5 cursor-not-allowed opacity-60">
        <input type="checkbox" defaultChecked disabled className="h-4 w-4 rounded border-[#273549] accent-[#3b82f6]" />
        <span className="text-sm text-[#94a3b8]">First row is header</span>
      </label>

      <div className="flex items-center justify-between gap-3 pt-3 border-t border-[#1e293b]">
        <button
          type="button"
          title="Column preview coming soon"
          aria-label="Preview File — coming soon"
          onClick={() =>
            toast('Column preview coming soon — upload and validate to continue.', {
              icon: 'ℹ️',
            })
          }
          className="flex items-center gap-1.5 rounded-lg border border-[#273549] bg-[#131a29] px-3.5 py-2 text-xs font-semibold text-[#64748b] opacity-50 cursor-not-allowed"
        >
          <Eye size={14} /> Preview File
        </button>
        <Button
          variant="primary"
          size="md"
          isLoading={uploading}
          disabled={!file || !canRunValidation}
          onClick={handleUpload}
        >
          Validate &amp; Ingest CSV
        </Button>
      </div>

      <p className="text-xs text-[#64748b] italic">
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
// PostgreSQL Config Panel — user-supplied connection
// ────────────────────────────────────────────
type ConnectStatus = 'idle' | 'testing' | 'connected' | 'failed';

function PostgresPanel({ projectId }: { projectId: string }) {
  const navigate = useNavigate();

  const [host, setHost] = useState('localhost');
  const [port, setPort] = useState('5433');
  const [database, setDatabase] = useState('aurum');
  const [username, setUsername] = useState('aurum');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [status, setStatus] = useState<ConnectStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<PostgresTestSuccess | null>(null);

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
    setConnection(null);

    try {
      const res = await testPostgresConnection({
        host: host.trim(),
        port: portNum,
        database: database.trim(),
        username: username.trim(),
        password: submittedPassword,
        project_id: projectId,
      });

      if (!res.connected) {
        setStatus('failed');
        setError(res.error || 'Connection failed.');
        toast.error(res.error || 'Connection failed.');
        return;
      }

      setConnection(res);
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
    <div className="space-y-5">
      {status !== 'connected' && (
        <>
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
                className="text-xs font-semibold text-[#3b82f6] hover:text-[#60a5fa] transition-colors cursor-pointer"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            }
          />

          <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[#1e293b]">
            <Button
              variant="primary"
              isLoading={status === 'testing'}
              onClick={handleTest}
              size="md"
            >
              {status === 'testing' ? 'Testing Connection…' : 'Test & Connect PostgreSQL'}
            </Button>
            {status === 'failed' && error && (
              <span className="text-xs text-[#ef4444]" role="alert">
                Failed: {error}
              </span>
            )}
          </div>

          <p className="text-xs text-[#64748b] italic">
            Connects to your target PostgreSQL database. Passwords are never stored or returned —
            re-test after an API restart.
          </p>
        </>
      )}

      {status === 'connected' && connection && (
        <div className="rounded-xl border border-[#10b981]/40 bg-[#10b981]/10 p-5 space-y-4 animate-fade-in">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 text-base font-bold text-[#10b981]">
              <CheckCircle2 size={20} />
              Connected to PostgreSQL Database
            </div>
            <Badge variant="pass">Active Session</Badge>
          </div>

          <div className="grid grid-cols-2 gap-4 rounded-lg bg-[#0b0f19]/80 p-4 border border-[#1e293b]">
            <div className="flex items-center gap-3">
              <Server size={18} className="text-[#3b82f6]" />
              <div>
                <span className="block text-[11px] font-semibold text-[#64748b] uppercase tracking-wider">Host / Port</span>
                <span className="text-sm font-medium text-[#f8fafc]">{host}:{port}</span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Database size={18} className="text-[#06b6d4]" />
              <div>
                <span className="block text-[11px] font-semibold text-[#64748b] uppercase tracking-wider">Database</span>
                <span className="text-sm font-medium text-[#f8fafc]">{connection.database}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setStatus('idle')}
            >
              Configure Different Connection
            </Button>
            <Button
              variant="primary"
              size="md"
              rightIcon={<ArrowRight size={16} />}
              onClick={() => {
                const params = new URLSearchParams({
                  connectionId: connection.connection_id,
                  database: connection.database,
                });
                navigate(`/projects/${projectId}/select?${params.toString()}`);
              }}
            >
              Explore Schemas &amp; Tables
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
        <span className="text-xs text-[#64748b]">{connector.name}</span>
      </div>
      <p className="text-sm text-[#94a3b8]">{connector.description}</p>
      <p className="text-sm text-[#64748b]">
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
    return 'postgresql';
  });

  const selectedConnector = connectors.find((c) => c.id === selected);
  const availableConnectors = connectors.filter((connector) => connector.type !== 'preview');
  const plannedConnectors = connectors.filter((connector) => connector.type === 'preview');

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 scrollbar-thin lg:py-8">
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-6">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Connect Data Source</h2>
              <DataSourceBadge mode={displayMode} />
            </div>
            <p className="mt-1 text-sm text-[#94a3b8]">
              Connect a PostgreSQL database or upload a CSV dataset to initiate Aurum Medallion processing.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
            <aside className="space-y-6">
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <Database size={15} className="text-[#3b82f6]" />
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-[#64748b]">
                    Supported Connectors
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
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#64748b]">
                  Coming Soon
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

            <section className="min-w-0 animate-slide-up rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
              {selectedConnector ? (
                <>
                  <div className="mb-6 flex items-center gap-3.5 pb-4 border-b border-[#1e293b]">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#2563eb] text-sm font-bold text-white shadow-[0_0_12px_rgba(37,99,235,0.3)]">
                      {selectedConnector.icon}
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-[#f8fafc]">
                        {selectedConnector.name}
                      </h3>
                      <p className="text-xs text-[#94a3b8]">{selectedConnector.description}</p>
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
                  <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-[#273549] bg-[#131a29] text-[#3b82f6]">
                    <Database size={24} />
                  </div>
                  <h3 className="text-base font-semibold text-[#f8fafc]">
                    Choose a Data Source
                  </h3>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-[#94a3b8]">
                    Select PostgreSQL to establish a live connection or CSV for direct dataset upload.
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
