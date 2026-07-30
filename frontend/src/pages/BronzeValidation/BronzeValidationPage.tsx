import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Database,
  Table,
  RefreshCw,
  AlertCircle,
  Check,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import {
  fetchSourceTables,
  getLiveTablePreview,
  ingestToBronze,
  ingestConnectorRelationsToBronze,
  listPostgresTables,
  verifyBronze,
  verifyConnectorRelationsInBronze,
  type ConnectorBronzeItemResult,
  type ConnectorRelationPayload,
  type SourceTableEntry,
  type IngestToBronzeItemResult,
  type LiveTablePreview,
  type VerifyBronzeItemResult,
} from '@/lib/aurumApi';
import { calmApiMessage } from '@/utils/apiErrors';
import {
  canIngestBronzeSelection,
  initialBronzeSelection,
  toggleAllBronzeTables,
  toggleBronzeTable,
} from '@/utils/bronzeSelection';
import { readRelationSelection } from '@/utils/relationSelection';
import { bronzeDiscoveryErrorMessage, withConnectorFlowQuery } from '@/utils/connectorFlow';

type BronzeResultItem = VerifyBronzeItemResult | ConnectorBronzeItemResult;

function relationKey(relation: ConnectorRelationPayload): string {
  return `${relation.schema}.${relation.table}`;
}

function resultSource(result: BronzeResultItem, fallbackSchema = 'configured_source'): ConnectorRelationPayload {
  if ('source' in result) return result.source;
  return { schema: fallbackSchema, table: result.table };
}

function resultBronze(result: BronzeResultItem): ConnectorRelationPayload {
  if ('bronze' in result) return result.bronze;
  return { schema: 'bronze', table: result.table };
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

/** Strict Silver Eligibility Rule: Requires backend status === 'success' AND match === true */
function isEligibleForSilver(r: BronzeResultItem | undefined): boolean {
  return Boolean(r && r.status === 'success' && r.match === true);
}

export function BronzeValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const connectionId = searchParams.get('connectionId') ?? undefined;
  const databaseName = searchParams.get('database') ?? undefined;
  const carriedRelation = readRelationSelection(searchParams);
  const carriedSchema = carriedRelation?.schema;
  const carriedTable = carriedRelation?.table;
  const connectorMode = Boolean(connectionId);
  const sourceDiscoveryContext = [
    connectionId ?? '',
    databaseName ?? '',
    carriedSchema ?? '',
    carriedTable ?? '',
  ].join('\u0000');

  // Source tables state
  const [loadingTables, setLoadingTables] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [schema, setSchema] = useState<string>('public');
  const [sourceTables, setSourceTables] = useState<SourceTableEntry[]>([]);
  const [selectedRelations, setSelectedRelations] = useState<ConnectorRelationPayload[]>(
    () => (carriedRelation ? [carriedRelation] : []),
  );

  // Ingestion & Verification state
  const [ingesting, setIngesting] = useState(false);
  const [ingestStage, setIngestStage] = useState<string>('');
  const [ingestResults, setIngestResults] = useState<IngestToBronzeItemResult[] | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResults, setVerifyResults] = useState<BronzeResultItem[] | null>(null);

  // Selected table for preview & Silver handoff
  const [activePreviewKey, setActivePreviewKey] = useState<string | null>(null);
  const [bronzePreview, setBronzePreview] = useState<LiveTablePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const sourceDiscoveryTokenRef = useRef(0);
  const sourceDiscoveryContextRef = useRef(sourceDiscoveryContext);
  sourceDiscoveryContextRef.current = sourceDiscoveryContext;

  const isBusy = ingesting || verifying;
  const canIngest = canIngestBronzeSelection(
    selectedRelations.map(relationKey),
    isBusy,
    loadingTables,
  );

  const resetStaleResults = useCallback(() => {
    setIngestResults(null);
    setVerifyResults(null);
    setActivePreviewKey(null);
    setBronzePreview(null);
    setPreviewError(null);
  }, []);

  const loadSourceTables = useCallback(async () => {
    const discoveryToken = ++sourceDiscoveryTokenRef.current;
    const requestContext = sourceDiscoveryContext;
    setLoadingTables(true);
    setTablesError(null);
    resetStaleResults();
    try {
      if (connectionId) {
        const res = await listPostgresTables(connectionId, carriedSchema);
        if (
          discoveryToken !== sourceDiscoveryTokenRef.current ||
          sourceDiscoveryContextRef.current !== requestContext
        ) return;
        setSchema(res.schema || carriedSchema || 'public');
        setSourceTables(res.tables || []);
        setSelectedRelations(carriedSchema && carriedTable ? [{ schema: carriedSchema, table: carriedTable }] : []);
      } else {
        const res = await fetchSourceTables();
        if (
          discoveryToken !== sourceDiscoveryTokenRef.current ||
          sourceDiscoveryContextRef.current !== requestContext
        ) return;
        setSchema(res.schema || 'public');
        setSourceTables(res.tables || []);
        setSelectedRelations(initialBronzeSelection().map((table) => ({ schema: res.schema || 'public', table })));
      }
    } catch (err: any) {
      if (
        discoveryToken !== sourceDiscoveryTokenRef.current ||
        sourceDiscoveryContextRef.current !== requestContext
      ) return;
      setTablesError(bronzeDiscoveryErrorMessage(err, connectorMode));
      setSourceTables([]);
      setSelectedRelations([]);
    } finally {
      if (
        discoveryToken === sourceDiscoveryTokenRef.current &&
        sourceDiscoveryContextRef.current === requestContext
      ) setLoadingTables(false);
    }
  }, [connectionId, connectorMode, carriedSchema, carriedTable, resetStaleResults, sourceDiscoveryContext]);

  useEffect(() => {
    void loadSourceTables();
  }, [loadSourceTables]);

  function toggleTableSelection(relation: ConnectorRelationPayload) {
    if (isBusy || loadingTables) return;
    resetStaleResults();
    setSelectedRelations((previous) => {
      const nextKeys = toggleBronzeTable(previous.map(relationKey), relationKey(relation));
      return nextKeys
        .map((key) => {
          const [schemaName, tableName] = key.split('.');
          return { schema: schemaName, table: tableName };
        })
        .filter((item) => item.schema && item.table);
    });
  }

  function toggleSelectAll() {
    if (isBusy || loadingTables) return;
    resetStaleResults();
    const available = sourceTables.map((table) => relationKey({ schema: table.schema, table: table.table }));
    const nextKeys = toggleAllBronzeTables(selectedRelations.map(relationKey), available);
    setSelectedRelations(
      nextKeys.map((key) => {
        const [schemaName, tableName] = key.split('.');
        return { schema: schemaName, table: tableName };
      }),
    );
  }

  async function handleIngestAndVerify() {
    if (!canIngest) return;

    setIngesting(true);
    setIngestStage('Preparing Bronze dataset…');
    resetStaleResults();

    try {
      // Step 1: Ingest to Bronze
      if (connectorMode && connectionId) {
        setIngestStage('Ingesting PostgreSQL tables to Bronze…');
        const ingestRes = await ingestConnectorRelationsToBronze(connectionId, selectedRelations);
        setIngestResults(ingestRes.results.map((result) => ({
          table: result.source.table,
          status: result.status,
          error: result.error,
        })));

        const successfulRelations = ingestRes.results
          .filter((r) => r.status === 'success')
          .map((r) => r.source);

        setIngesting(false);

        if (successfulRelations.length > 0) {
          setVerifying(true);
          setIngestStage('Verifying row counts & schema fidelity…');
          const verifyRes = await verifyConnectorRelationsInBronze(connectionId, successfulRelations);
          setVerifyResults(verifyRes.results);

          const firstEligible = verifyRes.results.find((r) => isEligibleForSilver(r));
          setActivePreviewKey(firstEligible ? relationKey(resultSource(firstEligible, schema)) : null);
        }
        return;
      }

      const selectedTableNames = selectedRelations.map((relation) => relation.table);
      setIngestStage('Copying source rows into raw Bronze table…');
      const ingestRes = await ingestToBronze(selectedTableNames);
      setIngestResults(ingestRes.results);

      const successfulTables = ingestRes.results
        .filter((r) => r.status === 'success')
        .map((r) => r.table);

      setIngesting(false);

      if (successfulTables.length > 0) {
        setVerifying(true);
        setIngestStage('Verifying 1:1 Bronze fidelity…');
        const verifyRes = await verifyBronze(successfulTables);
        setVerifyResults(verifyRes.results);

        const firstEligible = verifyRes.results.find((r) => isEligibleForSilver(r));
        setActivePreviewKey(firstEligible ? relationKey(resultSource(firstEligible, schema)) : null);
      }
    } catch (err: any) {
      setTablesError(calmApiMessage(err, 'Bronze ingestion or verification failed.'));
    } finally {
      setIngesting(false);
      setVerifying(false);
      setIngestStage('');
    }
  }

  // Bronze shows Live ONLY when there is genuine verified data (status === 'success' AND match === true)
  const hasLiveResults = Boolean(verifyResults && verifyResults.some(isEligibleForSilver));
  const activeVerifyItem = verifyResults?.find((r) => relationKey(resultSource(r, schema)) === activePreviewKey);
  const activeIsEligible = isEligibleForSilver(activeVerifyItem);
  const previewRows = activeVerifyItem && 'preview_sample' in activeVerifyItem
    ? activeVerifyItem.preview_sample ?? []
    : bronzePreview?.rows ?? [];
  const previewColumns = previewRows.length > 0 ? Object.keys(previewRows[0]) : [];

  useEffect(() => {
    let active = true;
    async function loadBronzePreview() {
      setBronzePreview(null);
      setPreviewError(null);
      if (!activeVerifyItem || !activeIsEligible) return;
      if ('preview_sample' in activeVerifyItem && activeVerifyItem.preview_sample?.length) return;
      const bronze = resultBronze(activeVerifyItem);
      try {
        const preview = await getLiveTablePreview(bronze.table, bronze.schema);
        if (active) setBronzePreview(preview);
      } catch (err) {
        if (active) {
          setPreviewError(calmApiMessage(err, 'Verified Bronze relation has no available live preview endpoint response.'));
        }
      }
    }
    void loadBronzePreview();
    return () => {
      active = false;
    };
  }, [activePreviewKey, activeIsEligible, activeVerifyItem]);

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runId} />
      <PageAssistant page="bronze" layer="bronze" runId={runId} selectedTable={carriedTable || undefined} />

      {/* Header */}
      <div className="px-6 py-5 border-b border-[#1e293b] bg-[#0b0f19]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Bronze Ingestion</h2>
          {hasLiveResults ? (
            <DataSourceBadge mode="live" />
          ) : (
            <Badge variant="secondary">Raw Ingestion</Badge>
          )}
          {hasLiveResults && (
            <Badge variant="pass">
              {verifyResults?.filter((r) => isEligibleForSilver(r)).length} Ingested &amp; Matched
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#94a3b8]">
          Aurum captures the selected source faithfully with 1:1 schema and row verification.
        </p>
      </div>

      {/* Content Body */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#0b0f19] scrollbar-thin">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Source Tables Selection & Ingestion Action */}
          <div className="lg:col-span-2 space-y-5">
            {/* Selected Source Tables Panel */}
            <div className="rounded-xl border border-[#1e293b] p-6 bg-[#111827] shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2.5">
                  <Database size={18} className="text-[#3b82f6]" />
                  <h3 className="text-base font-semibold text-[#f8fafc]">Select Source Tables for Ingestion</h3>
                  <span className="text-xs text-[#64748b] font-mono">({schema})</span>
                </div>
                <div className="flex items-center gap-3">
                  {sourceTables.length > 0 && (
                    <button
                      type="button"
                      onClick={toggleSelectAll}
                      disabled={loadingTables || isBusy}
                      className="text-xs font-semibold text-[#3b82f6] hover:text-[#60a5fa] transition-colors disabled:opacity-40 cursor-pointer"
                    >
                      {selectedRelations.length === sourceTables.length ? 'Deselect All' : 'Select All'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={loadSourceTables}
                    disabled={loadingTables || isBusy}
                    className="p-1 text-[#64748b] hover:text-[#f8fafc] transition-colors disabled:opacity-40 cursor-pointer"
                    title="Refresh source tables"
                  >
                    <RefreshCw size={14} className={loadingTables || isBusy ? 'animate-spin' : ''} />
                  </button>
                </div>
              </div>

              {carriedRelation && (
                <div className="mb-4 rounded-lg border border-[#3b82f6]/30 bg-[#2563eb]/10 px-3.5 py-2.5 text-xs text-[#94a3b8]">
                  From Dataset Explorer:{' '}
                  <span className="font-mono font-semibold text-[#f8fafc]">
                    {carriedRelation.schema}.{carriedRelation.table}
                  </span>
                  . Confirm your table selection below to proceed with Bronze ingestion.
                </div>
              )}

              {loadingTables ? (
                <LoadingSkeleton count={3} className="h-16" />
              ) : tablesError ? (
                <div className="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4 text-xs text-[#ef4444] space-y-2">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertCircle size={16} />
                    Failed to discover source tables
                  </div>
                  <p>{tablesError}</p>
                  <Button variant="secondary" size="sm" onClick={loadSourceTables} disabled={isBusy}>
                    Retry Discovery
                  </Button>
                </div>
              ) : sourceTables.length === 0 ? (
                <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-6 text-center text-xs text-[#94a3b8]">
                  No source tables found in schema <span className="font-mono text-[#f8fafc]">{schema}</span>.
                </div>
              ) : (
                <div className="space-y-2.5">
                  {sourceTables.map((entry) => {
                    const entryRelation = { schema: entry.schema, table: entry.table };
                    const entryKey = relationKey(entryRelation);
                    const isSelected = selectedRelations.some((item) => relationKey(item) === entryKey);
                    return (
                      <div
                        key={entryKey}
                        onClick={() => toggleTableSelection(entryRelation)}
                        className={`flex items-center justify-between p-3.5 rounded-xl border transition-all ${
                          isBusy || loadingTables ? 'cursor-not-allowed opacity-60' : 'cursor-pointer select-none'
                        } ${
                          isSelected
                            ? 'border-[#3b82f6] bg-[#2563eb]/15 shadow-[0_0_12px_rgba(37,99,235,0.15)]'
                            : 'border-[#1e293b] bg-[#131a29] hover:border-[#3b82f6]/40 hover:bg-[#1f293d]'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className={`h-4 w-4 rounded border flex items-center justify-center transition-colors ${
                              isSelected
                                ? 'border-[#3b82f6] bg-[#3b82f6] text-white'
                                : 'border-[#64748b] bg-[#131a29]'
                            }`}
                          >
                            {isSelected && <Check size={12} />}
                          </div>
                          <div>
                            <span className="text-sm font-semibold text-[#f8fafc]">
                              {entry.table}
                            </span>
                            <span className="ml-2 text-xs font-mono text-[#06b6d4]">
                              {entry.schema}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-4 text-xs text-[#94a3b8]">
                          {entry.row_count != null && (
                            <span className="font-mono">{formatNumber(entry.row_count)} rows</span>
                          )}
                          {entry.column_count != null && (
                            <span className="font-mono">{entry.column_count} cols</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Ingestion Progress & Action Bar */}
              <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-[#1e293b]">
                <div>
                  <span className="text-xs font-medium text-[#94a3b8]">
                    {selectedRelations.length} of {sourceTables.length} table
                    {sourceTables.length === 1 ? '' : 's'} selected
                  </span>
                  {ingestStage && (
                    <p className="text-xs text-[#06b6d4] font-medium mt-0.5 animate-pulse">
                      {ingestStage}
                    </p>
                  )}
                </div>
                <Button
                  variant="primary"
                  size="md"
                  disabled={!canIngest}
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
              <div className="rounded-xl border border-[#1e293b] p-6 bg-[#111827] space-y-4 animate-slide-up shadow-sm">
                <div className="flex items-center gap-2.5">
                  <ShieldCheck size={18} className="text-[#10b981]" />
                  <h3 className="text-base font-semibold text-[#f8fafc]">Ingestion &amp; Verification Results</h3>
                </div>

                <div className="space-y-3">
                  {selectedRelations.map((relation) => {
                    const sourceKey = relationKey(relation);
                    const ingRes = ingestResults?.find((r) => relationKey({ schema: relation.schema, table: r.table }) === sourceKey);
                    const verRes = verifyResults?.find((r) => relationKey(resultSource(r, schema)) === sourceKey);
                    const eligible = isEligibleForSilver(verRes);
                    const bronze = verRes ? resultBronze(verRes) : null;

                    return (
                      <div
                        key={sourceKey}
                        className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4 space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-[#f8fafc] font-mono">
                            {relation.schema}.{relation.table}
                          </span>
                          {ingRes?.status === 'error' ? (
                            <Badge variant="failed">Ingestion Failed</Badge>
                          ) : verRes ? (
                            <Badge variant={eligible ? 'pass' : 'failed'}>
                              {eligible ? 'Verified (1:1 Match)' : 'Mismatch / Ineligible'}
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
                          <div className="grid grid-cols-2 gap-2 pt-2.5 text-xs text-[#94a3b8] border-t border-[#1e293b] md:grid-cols-4">
                            <div>
                              <span className="text-[#64748b]">Bronze Relation: </span>
                              <span className="font-mono text-[#f8fafc] font-semibold">
                                {bronze ? `${bronze.schema}.${bronze.table}` : '—'}
                              </span>
                            </div>
                            <div>
                              <span className="text-[#64748b]">Source Rows: </span>
                              <span className="font-mono text-[#f8fafc]">
                                {formatNumber(verRes.source_row_count)}
                              </span>
                            </div>
                            <div>
                              <span className="text-[#64748b]">Bronze Rows: </span>
                              <span className="font-mono text-[#f8fafc]">
                                {formatNumber(verRes.bronze_row_count)}
                              </span>
                            </div>
                            <div>
                              <span className="text-[#64748b]">Match Status: </span>
                              <span
                                className={`font-semibold ${
                                  verRes.match ? 'text-[#10b981]' : 'text-[#ef4444]'
                                }`}
                              >
                                {verRes.match ? 'Exact 1:1 Match' : 'Mismatch'}
                              </span>
                            </div>
                          </div>
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
            <div className="rounded-xl border border-[#1e293b] p-6 bg-[#111827] shadow-sm">
              <div className="flex items-center gap-2.5 mb-4">
                <Table size={18} className="text-[#3b82f6]" />
                <h3 className="text-base font-semibold text-[#f8fafc]">Source vs Bronze Summary</h3>
              </div>

              {verifyResults && verifyResults.length > 0 ? (
                <div className="space-y-3">
                  <p className="text-xs text-[#64748b]">
                    Select which Bronze relation to process in Silver:
                  </p>
                  {verifyResults.map((v) => {
                    const eligible = isEligibleForSilver(v);
                    const source = resultSource(v, schema);
                    const bronze = resultBronze(v);
                    const sourceKey = relationKey(source);
                    const isSelected = activePreviewKey === sourceKey;
                    return (
                      <div
                        key={sourceKey}
                        onClick={() => {
                          if (eligible && !isBusy) {
                            setActivePreviewKey(sourceKey);
                          }
                        }}
                        className={`p-3.5 rounded-xl border transition-all ${
                          eligible && !isBusy ? 'cursor-pointer select-none' : 'cursor-not-allowed opacity-75'
                        } ${
                          isSelected
                            ? 'border-[#3b82f6] bg-[#2563eb]/15 shadow-[0_0_12px_rgba(37,99,235,0.2)]'
                            : 'border-[#1e293b] bg-[#131a29] hover:bg-[#1f293d]'
                        }`}
                      >
                        <div className="flex justify-between items-center text-xs font-semibold">
                          <span className="text-[#f8fafc] font-mono">{source.schema}.{source.table}</span>
                          <span className={eligible ? 'text-[#10b981]' : 'text-[#ef4444]'}>
                            {eligible ? 'Matched' : 'Mismatch'}
                          </span>
                        </div>
                        <div className="mt-2 flex justify-between text-xs text-[#94a3b8] font-mono">
                          <span>Source: {formatNumber(v.source_row_count)}</span>
                          <span>Bronze: {formatNumber(v.bronze_row_count)}</span>
                        </div>
                        <div className="mt-1 text-[11px] text-[#06b6d4] font-mono">
                          Target: {bronze.schema}.{bronze.table}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="space-y-2.5 text-xs text-[#94a3b8]">
                  <div className="flex justify-between py-2 border-b border-[#1e293b]">
                    <span>Source Total Rows</span>
                    <span className="font-mono text-[#f8fafc]">
                      {sourceTables.length > 0
                        ? formatNumber(
                            sourceTables.reduce((acc, t) => acc + (t.row_count || 0), 0),
                          )
                        : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2 border-b border-[#1e293b]">
                    <span>Bronze Ingested Rows</span>
                    <span className="font-mono text-[#64748b]">
                      {hasLiveResults ? 'Verified' : 'Not ingested yet'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2">
                    <span>Fidelity Match</span>
                    <span className="font-mono text-[#64748b]">
                      {hasLiveResults ? '100% 1:1' : '—'}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Bronze Data Preview */}
            <div className="rounded-xl border border-[#1e293b] p-6 bg-[#111827] shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold text-[#f8fafc]">Bronze Data Preview</h3>
                {verifyResults && verifyResults.length > 1 && (
                  <select
                    className="rounded-lg border border-[#273549] bg-[#131a29] px-2.5 py-1 text-xs text-[#f8fafc] focus:outline-none"
                    value={activePreviewKey || ''}
                    disabled={isBusy}
                    onChange={(e) => {
                      const selectedItem = verifyResults.find((r) => relationKey(resultSource(r, schema)) === e.target.value);
                      if (isEligibleForSilver(selectedItem)) {
                        setActivePreviewKey(e.target.value);
                      }
                    }}
                  >
                    {verifyResults.map((v) => {
                      const eligible = isEligibleForSilver(v);
                      const source = resultSource(v, schema);
                      const sourceKey = relationKey(source);
                      return (
                        <option key={sourceKey} value={sourceKey} disabled={!eligible}>
                          {source.schema}.{source.table} {eligible ? '(Eligible)' : '(Ineligible)'}
                        </option>
                      );
                    })}
                  </select>
                )}
              </div>

              {activeVerifyItem && activeIsEligible && previewRows.length > 0 ? (
                <div>
                  <p className="text-xs text-[#94a3b8] mb-3">
                    Previewing <span className="font-mono text-[#f8fafc] font-semibold">{resultBronze(activeVerifyItem).schema}.{resultBronze(activeVerifyItem).table}</span>
                  </p>
                  <div className="overflow-x-auto max-h-[320px] rounded-lg border border-[#1e293b] scrollbar-thin">
                    <table className="w-full text-left text-xs whitespace-nowrap">
                      <thead className="sticky top-0 bg-[#131a29] border-b border-[#1e293b] text-[#94a3b8]">
                        <tr>
                          {previewColumns.map((col) => (
                            <th key={col} className="px-3 py-2 font-semibold border-r border-[#1e293b] last:border-r-0">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#1e293b] bg-[#0b0f19]">
                        {previewRows.map((row, idx) => (
                          <tr key={idx} className="hover:bg-[#131a29] transition-colors">
                            {previewColumns.map((col) => (
                              <td key={col} className="px-3 py-2 border-r border-[#1e293b] last:border-r-0 text-[#f8fafc] font-mono text-[12px]">
                                {row[col] !== null && row[col] !== undefined
                                  ? String(row[col])
                                  : <span className="text-[#64748b] italic">NULL</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-6 text-center text-xs text-[#94a3b8]">
                  {previewError
                    ? previewError
                    : verifying
                    ? 'Fetching preview sample from backend…'
                    : verifyResults && verifyResults.length > 0 && !activeIsEligible
                      ? 'No verified 1:1 matching table is available for Silver handoff.'
                      : 'Ingest and verify source tables to display real Bronze preview data.'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Footer Navigation Bar */}
      <div
        data-assistant-safe-zone="bottom-action"
        className="border-t border-[#1e293b] bg-[#0b0f19] px-6 py-4 flex items-center justify-end shadow-lg"
      >
        <Button
          variant="primary"
          size="md"
          disabled={!activeVerifyItem || !activeIsEligible || isBusy}
          rightIcon={<ArrowRight size={16} />}
          onClick={() => {
            if (activeVerifyItem && activeIsEligible) {
              const source = resultSource(activeVerifyItem, schema);
              const bronze = resultBronze(activeVerifyItem);
              const params = new URLSearchParams({
                table: bronze.table,
                bronzeSchema: bronze.schema,
                sourceSchema: source.schema,
                sourceTable: source.table,
              });
              if (connectionId) params.set('connectionId', connectionId);
              navigate(withConnectorFlowQuery(
                `/projects/${encodeURIComponent(id || '')}/silver?${params.toString()}`,
                searchParams,
              ));
            }
          }}
        >
          {activeVerifyItem && activeIsEligible
            ? `Continue to Silver (${resultBronze(activeVerifyItem).table})`
            : 'Continue to Silver'}
        </Button>
      </div>
    </div>
  );
}
