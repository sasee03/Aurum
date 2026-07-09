import { useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, ArrowRight, Upload, Eye, AlertTriangle } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { useAppMode } from '@/context/AppModeContext';
import { CsvUploadError, getMetadataHealth, uploadDatasetCsv, type CsvUploadMismatch } from '@/lib/aurumApi';
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
          <span className="text-[11px] text-[#4b5563]">CSV files only — Olist raw_orders shape</span>
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
        Upload must match the Olist raw_orders schema. Mismatched files are rejected — demo data is
        never substituted.
      </p>

      <Button
        variant="secondary"
        className="w-full"
        rightIcon={<ArrowRight size={16} />}
        onClick={() => navigate(`/projects/${projectId}/select`)}
      >
        Continue with demo walkthrough
      </Button>
    </div>
  );
}

// ────────────────────────────────────────────
// PostgreSQL Config Panel — real backend DB reachability test
// ────────────────────────────────────────────
function PostgresPanel({ onConnect }: { onConnect: () => void }) {
  const [connected, setConnected] = useState(false);
  const [degraded, setDegraded] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleTest() {
    setTesting(true);
    setConnected(false);
    setDegraded(false);
    try {
      const res = await getMetadataHealth();
      if (res.status === 'ok') {
        setConnected(true);
        toast.success('PostgreSQL connected successfully.');
      } else {
        setDegraded(true);
      }
    } catch {
      toast.error('Backend API is not running. Check the connection.');
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2">
          <Input label="Host" defaultValue="localhost" disabled readOnly />
        </div>
        <Input label="Port" type="number" defaultValue="5433" disabled readOnly />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Input label="Database" defaultValue="aurum" disabled readOnly />
        <Input label="Schema" defaultValue="public" disabled readOnly />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Input label="Username" defaultValue="aurum" disabled readOnly />
        <Input
          label="Password"
          type={showPassword ? 'text' : 'password'}
          defaultValue="aurum"
          disabled
          readOnly
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
      </div>
      <label className="flex items-center gap-2.5 cursor-not-allowed opacity-60">
        <input type="checkbox" disabled className="h-4 w-4 rounded border-[#252637] accent-[#6366f1]" />
        <span className="text-sm text-[#94a3b8]">Enable SSL</span>
      </label>

      <div className="flex items-center gap-3 pt-2 border-t border-[#252637]">
        <Button
          variant="secondary"
          isLoading={testing}
          onClick={handleTest}
          size="sm"
        >
          {connected ? (
            <>
              <CheckCircle2 size={14} className="text-[#22c55e]" />
              <span className="text-[#22c55e]">DB reachable</span>
            </>
          ) : (
            'Test Backend DB Connection'
          )}
        </Button>
      </div>

      <p className="text-xs text-[#6b7280] italic">
        Uses the backend-configured PostgreSQL connection from your .env file.
      </p>

      {connected && (
        <Button
          variant="primary"
          className="w-full"
          rightIcon={<ArrowRight size={16} />}
          onClick={onConnect}
        >
          Explore Datasets
        </Button>
      )}

      {degraded && (
        <div className="mt-4 p-3 bg-[#451a03] border border-[#78350f] rounded-md space-y-2 animate-slide-up">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="text-[#f59e0b] mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold text-[#fde68a]">
                Backend is running, but local PostgreSQL is unavailable on this machine.
              </p>
              <p className="text-xs text-[#fcd34d] mt-1">
                You can continue with clearly labelled demo metadata.
              </p>
            </div>
          </div>
          <Button
            variant="secondary"
            className="w-full mt-2 border-[#78350f] text-[#fcd34d] hover:bg-[#78350f]/50 gap-2"
            rightIcon={<ArrowRight size={14} />}
            onClick={onConnect}
          >
            Continue with Demo Metadata
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
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { displayMode } = useAppMode();
  const [selected, setSelected] = useState<string | null>(null);

  function handleConnect() {
    navigate(`/projects/${id}/select`);
  }

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
              {selectedConnector.type === 'postgresql' && <PostgresPanel onConnect={handleConnect} />}
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
