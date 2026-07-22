import { useState, useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Database,
  Table,
  Layers,
  RefreshCw,
  AlertCircle,
  Check,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import {
  fetchSourceTables,
  ingestToBronze,
  verifyBronze,
  type SourceTableEntry,
  type IngestToBronzeItemResult,
  type VerifyBronzeItemResult,
} from '@/lib/aurumApi';
import { calmApiMessage } from '@/utils/apiErrors';
import { withRunIdQuery } from '@/hooks/useReport';

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

/** Strict Silver Eligibility Rule: Requires backend status === 'success' AND match === true */
function isEligibleForSilver(r: VerifyBronzeItemResult | undefined): boolean {
  return Boolean(r && r.status === 'success' && r.match === true);
}

export function BronzeValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;

  // Source tables state
  const [loadingTables, setLoadingTables] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [schema, setSchema] = useState<string>('public');
  const [sourceTables, setSourceTables] = useState<SourceTableEntry[]>([]);
  const [selectedTableNames, setSelectedTableNames] = useState<string[]>([]);

  // Ingestion & Verification state
  const [ingesting, setIngesting] = useState(false);
  const [ingestResults, setIngestResults] = useState<IngestToBronzeItemResult[] | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResults, setVerifyResults] = useState<VerifyBronzeItemResult[] | null>(null);

  // Selected table for preview & Silver handoff
  const [activePreviewTable, setActivePreviewTable] = useState<string | null>(null);

  const isBusy = ingesting || verifying;

  function resetStaleResults() {
    setIngestResults(null);
    setVerifyResults(null);
    setActivePreviewTable(null);
  }

  async function loadSourceTables() {
    if (isBusy) return;
    setLoadingTables(true);
    setTablesError(null);
    resetStaleResults();
    try {
      const res = await fetchSourceTables();
      setSchema(res.schema || 'public');
      setSourceTables(res.tables || []);
      if (res.tables && res.tables.length > 0) {
        setSelectedTableNames(res.tables.map((t) => t.table));
      } else {
        setSelectedTableNames([]);
      }
    } catch (err: any) {
      setTablesError(calmApiMessage(err, 'Failed to discover source tables from backend API.'));
      setSourceTables([]);
      setSelectedTableNames([]);
    } finally {
      setLoadingTables(false);
    }
  }

  useEffect(() => {
    void loadSourceTables();
  }, []);

  function toggleTableSelection(tableName: string) {
    if (isBusy || loadingTables) return;
    resetStaleResults();
    setSelectedTableNames((prev) =>
      prev.includes(tableName)
        ? prev.filter((t) => t !== tableName)
        : [...prev, tableName],
    );
  }

  function toggleSelectAll() {
    if (isBusy || loadingTables) return;
    resetStaleResults();
    if (selectedTableNames.length === sourceTables.length) {
      setSelectedTableNames([]);
    } else {
      setSelectedTableNames(sourceTables.map((t) => t.table));
    }
  }

  async function handleIngestAndVerify() {
    if (selectedTableNames.length === 0 || isBusy || loadingTables) return;

    setIngesting(true);
    resetStaleResults();

    try {
      // Step 1: Ingest to Bronze
      const ingestRes = await ingestToBronze(selectedTableNames);
      setIngestResults(ingestRes.results);

      // Identify successfully ingested tables
      const successfulTables = ingestRes.results
        .filter((r) => r.status === 'success')
        .map((r) => r.table);

      setIngesting(false);

      if (successfulTables.length > 0) {
        // Step 2: Verify Bronze for successful tables
        setVerifying(true);
        const verifyRes = await verifyBronze(successfulTables);
        setVerifyResults(verifyRes.results);

        // Select the FIRST ELIGIBLE table (status === 'success' AND match === true)
        const firstEligible = verifyRes.results.find((r) => isEligibleForSilver(r));
        if (firstEligible) {
          setActivePreviewTable(firstEligible.table);
        } else {
          setActivePreviewTable(null);
        }
      }
    } catch (err: any) {
      setTablesError(calmApiMessage(err, 'Bronze ingestion or verification failed.'));
    } finally {
      setIngesting(false);
      setVerifying(false);
    }
  }

  // Bronze shows Live ONLY when there is genuine verified data (status === 'success' AND match === true)
  const hasLiveResults = Boolean(verifyResults && verifyResults.some(isEligibleForSilver));
  const activeVerifyItem = verifyResults?.find((r) => r.table === activePreviewTable);
  const activeIsEligible = isEligibleForSilver(activeVerifyItem);
  const previewRows = activeVerifyItem?.preview_sample ?? [];
  const previewColumns = previewRows.length > 0 ? Object.keys(previewRows[0]) : [];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="bronze" layer="bronze" runId={runId} />

      {/* Header */}
      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Bronze Layer</h2>
          <DataSourceBadge mode={hasLiveResults ? 'live' : 'planned'} />
          {hasLiveResults && (
            <Badge variant="pass">
              {verifyResults?.filter((r) => isEligibleForSilver(r)).length} Ingested &amp; Matched
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Raw 1:1 source data ingestion and validation layer.
        </p>
      </div>

      {/* Content Body */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10] scrollbar-thin">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Source Tables Selection & Ingestion Action */}
          <div className="lg:col-span-2 space-y-5">
            {/* Selected Source Tables Panel */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Database size={17} className="text-[#6366f1]" />
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">Discover Source Tables</h3>
                  <span className="text-xs text-[#6b7280]">({schema})</span>
                </div>
                <div className="flex items-center gap-2">
                  {sourceTables.length > 0 && (
                    <button
                      type="button"
                      onClick={toggleSelectAll}
                      disabled={loadingTables || isBusy}
                      className="text-xs text-[#6366f1] hover:text-[#818cf8] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {selectedTableNames.length === sourceTables.length ? 'Deselect All' : 'Select All'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={loadSourceTables}
                    disabled={loadingTables || isBusy}
                    className="p-1 text-[#6b7280] hover:text-[#f1f5f9] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Refresh source tables"
                  >
                    <RefreshCw size={14} className={loadingTables || isBusy ? 'animate-spin' : ''} />
                  </button>
                </div>
              </div>

              {loadingTables ? (
                <LoadingSkeleton count={3} className="h-16" />
              ) : tablesError ? (
                <div className="rounded-lg border border-[#ef4444]/30 bg-[#450a0a]/30 p-4 text-xs text-[#fca5a5] space-y-2">
                  <div className="flex items-center gap-2 font-semibold text-[#ef4444]">
                    <AlertCircle size={16} />
                    Failed to discover tables
                  </div>
                  <p>{tablesError}</p>
                  <Button variant="secondary" size="sm" onClick={loadSourceTables} disabled={isBusy}>
                    Retry Discovery
                  </Button>
                </div>
              ) : sourceTables.length === 0 ? (
                <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#94a3b8]">
                  No tables found in source schema <span className="font-mono text-[#f1f5f9]">{schema}</span>.
                </div>
              ) : (
                <div className="space-y-2">
                  {sourceTables.map((entry) => {
                    const isSelected = selectedTableNames.includes(entry.table);
                    return (
                      <div
                        key={entry.table}
                        onClick={() => toggleTableSelection(entry.table)}
                        className={`flex items-center justify-between p-3.5 rounded-lg border transition-all ${
                          isBusy || loadingTables ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                        } ${
                          isSelected
                            ? 'border-[#6366f1]/60 bg-[#6366f1]/10'
                            : 'border-[#252637] bg-[#13141e] hover:border-[#6366f1]/30 hover:bg-[#1a1b28]'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className={`h-4 w-4 rounded border flex items-center justify-center transition-colors ${
                              isSelected
                                ? 'border-[#6366f1] bg-[#6366f1] text-white'
                                : 'border-[#4b5563] bg-[#1a1b28]'
                            }`}
                          >
                            {isSelected && <Check size={12} />}
                          </div>
                          <div>
                            <span className="text-sm font-semibold text-[#f1f5f9]">
                              {entry.table}
                            </span>
                            <span className="ml-2 text-xs text-[#6b7280]">
                              {entry.schema}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-4 text-xs text-[#94a3b8]">
                          {entry.row_count != null && (
                            <span>{formatNumber(entry.row_count)} rows</span>
                          )}
                          {entry.column_count != null && (
                            <span>{entry.column_count} cols</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Ingest Action Bar */}
              <div className="mt-5 flex items-center justify-between pt-4 border-t border-[#252637]">
                <span className="text-xs text-[#94a3b8]">
                  {selectedTableNames.length} of {sourceTables.length} table
                  {sourceTables.length === 1 ? '' : 's'} selected
                </span>
                <Button
                  variant="primary"
                  disabled={selectedTableNames.length === 0 || isBusy || loadingTables}
                  isLoading={ingesting || verifying}
                  onClick={handleIngestAndVerify}
                >
                  {ingesting
                    ? 'Ingesting to Bronze…'
                    : verifying
                      ? 'Verifying Ingestion…'
                      : 'Ingest Selected Tables to Bronze'}
                </Button>
              </div>
            </div>

            {/* Ingestion & Verification Status Results */}
            {(ingestResults || verifyResults) && (
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4 animate-slide-up">
                <div className="flex items-center gap-2">
                  <Layers size={17} className="text-[#6366f1]" />
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">Ingestion &amp; Verification Status</h3>
                </div>

                <div className="space-y-3">
                  {selectedTableNames.map((tableName) => {
                    const ingRes = ingestResults?.find((r) => r.table === tableName);
                    const verRes = verifyResults?.find((r) => r.table === tableName);
                    const eligible = isEligibleForSilver(verRes);

                    return (
                      <div
                        key={tableName}
                        className="rounded-lg border border-[#252637] bg-[#13141e] p-4 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-[#f1f5f9]">
                            {tableName}
                          </span>
                          {ingRes?.status === 'error' ? (
                            <Badge variant="failed">Ingestion Failed</Badge>
                          ) : verRes ? (
                            <Badge variant={eligible ? 'pass' : 'failed'}>
                              {eligible ? 'Verified (Match)' : 'Mismatch / Ineligible'}
                            </Badge>
                          ) : (
                            <Badge variant="secondary">Ingested</Badge>
                          )}
                        </div>

                        {ingRes?.error && (
                          <p className="text-xs text-[#ef4444] leading-relaxed">
                            Error: {ingRes.error}
                          </p>
                        )}

                        {verRes && verRes.status === 'success' && (
                          <div className="grid grid-cols-3 gap-2 pt-2 text-xs text-[#94a3b8] border-t border-[#252637]">
                            <div>
                              <span className="text-[#6b7280]">Source Rows: </span>
                              <span className="font-mono text-[#f1f5f9]">
                                {formatNumber(verRes.source_row_count)}
                              </span>
                            </div>
                            <div>
                              <span className="text-[#6b7280]">Bronze Rows: </span>
                              <span className="font-mono text-[#f1f5f9]">
                                {formatNumber(verRes.bronze_row_count)}
                              </span>
                            </div>
                            <div>
                              <span className="text-[#6b7280]">Match: </span>
                              <span
                                className={`font-semibold ${
                                  verRes.match ? 'text-[#22c55e]' : 'text-[#ef4444]'
                                }`}
                              >
                                {verRes.match ? 'Exact (100%)' : 'Mismatch (Ineligible)'}
                              </span>
                            </div>
                          </div>
                        )}
                        {verRes && verRes.status === 'error' && (
                          <p className="text-xs text-[#ef4444]">
                            Verification error: {verRes.error}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Source vs Bronze Summary & Dynamic Data Preview */}
          <div className="space-y-5">
            {/* Source vs Bronze Summary */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center gap-2 mb-3">
                <Table size={16} className="text-[#6366f1]" />
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Source Rows vs Bronze Rows</h3>
              </div>

              {verifyResults && verifyResults.length > 0 ? (
                <div className="space-y-3">
                  {verifyResults.map((v) => {
                    const eligible = isEligibleForSilver(v);
                    const isSelected = activePreviewTable === v.table;
                    return (
                      <div
                        key={v.table}
                        onClick={() => {
                          if (eligible && !isBusy) {
                            setActivePreviewTable(v.table);
                          }
                        }}
                        className={`p-3 rounded-lg border transition-colors ${
                          eligible && !isBusy ? 'cursor-pointer' : 'cursor-not-allowed opacity-75'
                        } ${
                          isSelected
                            ? 'border-[#6366f1] bg-[#6366f1]/10'
                            : 'border-[#252637] bg-[#13141e] hover:bg-[#1a1b28]'
                        }`}
                      >
                        <div className="flex justify-between items-center text-xs font-semibold text-[#f1f5f9]">
                          <span>{v.table}</span>
                          <span className={eligible ? 'text-[#22c55e]' : 'text-[#ef4444]'}>
                            {eligible ? 'Matched (Eligible)' : 'Mismatch (Ineligible)'}
                          </span>
                        </div>
                        <div className="mt-2 flex justify-between text-xs text-[#94a3b8]">
                          <span>Source: {formatNumber(v.source_row_count)}</span>
                          <span>Bronze: {formatNumber(v.bronze_row_count)}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="space-y-2 text-xs text-[#94a3b8]">
                  <div className="flex justify-between py-1.5 border-b border-[#252637]">
                    <span>Source Total Rows</span>
                    <span className="font-mono text-[#6b7280]">
                      {sourceTables.length > 0
                        ? formatNumber(
                            sourceTables.reduce((acc, t) => acc + (t.row_count || 0), 0),
                          )
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-[#252637]">
                    <span>Bronze Ingested Rows</span>
                    <span className="font-mono text-[#6b7280]">
                      {hasLiveResults ? 'Verified' : 'Not ingested yet'}
                    </span>
                  </div>
                  <div className="flex justify-between py-1.5">
                    <span>Ingestion Delta</span>
                    <span className="font-mono text-[#6b7280]">
                      {hasLiveResults ? '0' : '—'}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Bronze Data Preview */}
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Bronze Data Preview</h3>
                {verifyResults && verifyResults.length > 1 && (
                  <select
                    className="rounded border border-[#252637] bg-[#1a1b28] px-2 py-1 text-xs text-[#f1f5f9] focus:outline-none"
                    value={activePreviewTable || ''}
                    disabled={isBusy}
                    onChange={(e) => {
                      const selectedItem = verifyResults.find((r) => r.table === e.target.value);
                      if (isEligibleForSilver(selectedItem)) {
                        setActivePreviewTable(e.target.value);
                      }
                    }}
                  >
                    {verifyResults.map((v) => {
                      const eligible = isEligibleForSilver(v);
                      return (
                        <option key={v.table} value={v.table} disabled={!eligible}>
                          {v.table} {eligible ? '(Eligible)' : '(Ineligible - Mismatch)'}
                        </option>
                      );
                    })}
                  </select>
                )}
              </div>

              {activePreviewTable && activeIsEligible && previewRows.length > 0 ? (
                <div>
                  <p className="text-xs text-[#6b7280] mb-3">
                    Showing sample rows from <span className="font-mono text-[#f1f5f9]">bronze.{activePreviewTable}</span>
                  </p>
                  <div className="overflow-x-auto max-h-[340px] rounded-lg border border-[#252637] scrollbar-thin">
                    <table className="w-full text-left text-xs whitespace-nowrap">
                      <thead className="sticky top-0 bg-[#13141e] border-b border-[#252637] text-[#94a3b8]">
                        <tr>
                          {previewColumns.map((col) => (
                            <th key={col} className="px-3 py-2 font-semibold border-r border-[#252637] last:border-r-0">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#252637]">
                        {previewRows.map((row, idx) => (
                          <tr key={idx} className="hover:bg-[#1a1b28]/40">
                            {previewColumns.map((col) => (
                              <td key={col} className="px-3 py-2 border-r border-[#252637] last:border-r-0 text-[#f1f5f9]">
                                {row[col] !== null && row[col] !== undefined
                                  ? String(row[col])
                                  : <span className="text-[#6b7280] italic">null</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#6b7280]">
                  {verifying
                    ? 'Fetching preview sample from backend…'
                    : verifyResults && verifyResults.length > 0 && !activeIsEligible
                      ? 'No verified 1:1 matching table is available for Silver handoff.'
                      : 'Ingest and verify source tables to display real Bronze data preview.'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Footer Navigation Bar */}
      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => navigate(withRunIdQuery(`/projects/${id}/connect`, runId))}
        >
          Back to Connect
        </Button>
        <Button
          variant="primary"
          disabled={!activePreviewTable || !activeIsEligible || isBusy}
          rightIcon={<ArrowRight size={16} />}
          onClick={() => {
            if (activePreviewTable && activeIsEligible) {
              navigate(`/projects/${encodeURIComponent(id || '')}/silver?table=${encodeURIComponent(activePreviewTable)}`);
            }
          }}
        >
          {activePreviewTable && activeIsEligible
            ? `Continue to Silver (${activePreviewTable})`
            : 'Continue to Silver'}
        </Button>
      </div>
    </div>
  );
}
