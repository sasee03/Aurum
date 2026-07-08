import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, ArrowRight, Upload, Eye, AlertTriangle } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/utils/cn';
import { PlannedBanner } from '@/components/common/PlannedBanner';
import { getMetadataHealth } from '@/lib/aurumApi';
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
        'flex flex-col items-center justify-center gap-2 rounded-xl border p-5 text-center transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#6366f1]',
        selected
          ? 'border-[#6366f1] bg-[#6366f1]/10 shadow-[0_0_12px_rgba(99,102,241,0.15)]'
          : 'border-[#252637] bg-[#13141e] hover:border-[#6366f1]/30 hover:bg-[#1a1b28]'
      )}
    >
      <div
        className={cn(
          'flex h-10 w-10 items-center justify-center rounded-lg text-sm font-bold transition-colors',
          selected
            ? 'bg-[#6366f1] text-white'
            : 'bg-[#1a1b28] text-[#6366f1] border border-[#252637]'
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
// CSV Config Panel
// ────────────────────────────────────────────
function CsvPanel({ onConnect }: { onConnect: () => void }) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [testing, setTesting] = useState(false);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setFileName(file.name);
  }

  async function handleValidate() {
    setTesting(true);
    await new Promise((r) => setTimeout(r, 1200));
    setTesting(false);
    setConnected(true);
    toast.success('File validated successfully!');
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
          <span className="text-[11px] text-[#4b5563]">CSV files only</span>
          <input
            id="csv-upload"
            type="file"
            accept=".csv"
            className="sr-only"
            onChange={handleFileChange}
            aria-label="Upload CSV file"
          />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
            Delimiter
          </label>
          <select
            className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
            aria-label="Delimiter"
          >
            <option value=",">Comma (,)</option>
            <option value=";">Semicolon (;)</option>
            <option value="\t">Tab</option>
            <option value="|">Pipe (|)</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
            Encoding
          </label>
          <select
            className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] px-3 py-2.5 text-sm text-[#f1f5f9] focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
            aria-label="Encoding"
          >
            <option value="utf-8">UTF-8</option>
            <option value="utf-16">UTF-16</option>
            <option value="latin1">Latin-1</option>
          </select>
        </div>
      </div>

      <label className="flex items-center gap-2.5 cursor-pointer">
        <input type="checkbox" defaultChecked className="h-4 w-4 rounded border-[#252637] accent-[#6366f1]" />
        <span className="text-sm text-[#94a3b8]">First row is header</span>
      </label>

      <div className="flex items-center gap-2 pt-2 border-t border-[#252637]">
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<Eye size={14} />}
          onClick={() => toast('Preview coming soon', { icon: '👁' })}
        >
          Preview File
        </Button>
        <Button
          variant="secondary"
          size="sm"
          isLoading={testing}
          onClick={handleValidate}
          className="gap-2"
        >
          {connected ? (
            <>
              <CheckCircle2 size={14} className="text-[#22c55e]" />
              <span className="text-[#22c55e]">Validated</span>
            </>
          ) : (
            'Validate Connection'
          )}
        </Button>
      </div>

      <p className="text-xs text-[#6b7280] italic">CSV upload flow UI ready; backend ingestion pending.</p>

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
    </div>
  );
}

// ────────────────────────────────────────────
// PostgreSQL Config Panel
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
        toast.success('PostgreSQL connected successfully!');
      } else {
        setDegraded(true);
      }
    } catch (e) {
      toast.error('Backend API is not running. Check connection.');
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
          disabled readOnly
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
          className="gap-2"
        >
          {connected ? (
            <>
              <CheckCircle2 size={14} className="text-[#22c55e]" />
              <span className="text-[#22c55e]">Connected</span>
            </>
          ) : (
            'Test Backend DB Connection'
          )}
        </Button>
        {connected && (
          <Badge variant="pass" dot>
            Connected
          </Badge>
        )}
      </div>

      <p className="text-xs text-[#6b7280] italic">Demo mode: using backend configured PostgreSQL connection. Custom credentials UI is ready; dynamic connection wiring is pending.</p>

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
                Backend is running, but local PostgreSQL is unavailable on this laptop.
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
// Main Connectors Page
// ────────────────────────────────────────────
export function ConnectorsPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [selected, setSelected] = useState<string | null>(null);

  function handleConnect() {
    navigate(`/projects/${id}/select`);
  }

  const selectedConnector = connectors.find((c) => c.id === selected);

  return (
    <div className="min-h-full px-6 py-8 animate-fade-in">
      {/* Page Header */}
      <div className="mb-8">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Connect Data Sources</h2>
        <p className="mt-1 text-sm text-[#6b7280]">
          Current demo uses preloaded Olist data via PostgreSQL. CSV and PostgreSQL connector flows
          are shown as the planned onboarding path.
        </p>
        <div className="mt-4 max-w-2xl">
          <PlannedBanner detail="Preview — not wired to live API yet. Connector selection does not persist credentials or test connections." />
        </div>
        <p className="mt-2 text-sm text-[#6b7280]">Select a system to configure your connection.</p>
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

              {selectedConnector.type === 'csv' && <CsvPanel onConnect={handleConnect} />}
              {selectedConnector.type === 'postgresql' && <PostgresPanel onConnect={handleConnect} />}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
