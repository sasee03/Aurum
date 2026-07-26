import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle2,
  Layers,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import {
  approveGoldSql,
  checkGoldName,
  executeGoldSql,
  generateGoldSql,
  getLiveTablePreview,
  getMetadataTable,
  listGoldTables,
  listSilverTables,
  promoteGoldSql,
  reviewGoldSql,
  type ApproveGoldResponse,
  type ExecuteGoldResponse,
  type LiveTablePreview,
  type MetadataTableDetailResponse,
  type PromoteGoldResponse,
  type ReviewGoldResponse,
} from '@/lib/aurumApi';
import { calmApiMessage } from '@/utils/apiErrors';

type TableMetadata = MetadataTableDetailResponse['tables'][number];

function plannedSources(review: ReviewGoldResponse | null): string[] {
  const sources = review?.planned_changes.sources;
  return Array.isArray(sources)
    ? sources.filter((value): value is string => typeof value === 'string')
    : [];
}

function plannedPurpose(review: ReviewGoldResponse | null): string {
  const purpose = review?.planned_changes.business_requirement;
  return typeof purpose === 'string' ? purpose : '';
}

export function GoldValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runIdParam = searchParams.get('runId') ?? undefined;
  const tableParam = searchParams.get('table') ?? '';

  const [silverTables, setSilverTables] = useState<string[]>([]);
  const [selectedSilverTable, setSelectedSilverTable] = useState('');
  const [targetTableName, setTargetTableName] = useState(tableParam);
  const [businessRequirement, setBusinessRequirement] = useState(
    'Promote the selected approved Silver relation into the Gold layer.',
  );
  const [loadingSources, setLoadingSources] = useState(true);
  const [sourceError, setSourceError] = useState<string | null>(null);

  const [generating, setGenerating] = useState(false);
  const [review, setReview] = useState<ReviewGoldResponse | null>(null);
  const [targetExists, setTargetExists] = useState(false);
  const [approval, setApproval] = useState<ApproveGoldResponse | null>(null);
  const [approving, setApproving] = useState(false);
  const [execution, setExecution] = useState<ExecuteGoldResponse | null>(null);
  const [executing, setExecuting] = useState(false);
  const [promotion, setPromotion] = useState<PromoteGoldResponse | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  const [goldTables, setGoldTables] = useState<string[]>([]);
  const [goldMetadata, setGoldMetadata] = useState<TableMetadata | null>(null);
  const [goldPreview, setGoldPreview] = useState<LiveTablePreview | null>(null);
  const [loadingLiveData, setLoadingLiveData] = useState(false);
  const [liveDataError, setLiveDataError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadSources() {
      setLoadingSources(true);
      setSourceError(null);
      try {
        const response = await listSilverTables();
        if (!active) return;
        const names = response.tables.map((table) => table.name);
        const selected =
          tableParam && names.includes(tableParam) ? tableParam : names[0] ?? '';
        setSilverTables(names);
        setSelectedSilverTable(selected);
        setTargetTableName((current) => current || selected);
      } catch (error: unknown) {
        if (!active) return;
        setSilverTables([]);
        setSelectedSilverTable('');
        setSourceError(
          calmApiMessage(
            error,
            'Could not load live Silver relations for Gold selection.',
          ),
        );
      } finally {
        if (active) setLoadingSources(false);
      }
    }
    void loadSources();
    return () => {
      active = false;
    };
  }, [tableParam]);

  function resetGeneratedState() {
    setReview(null);
    setApproval(null);
    setExecution(null);
    setPromotion(null);
    setTargetExists(false);
    setWorkflowError(null);
    setGoldTables([]);
    setGoldMetadata(null);
    setGoldPreview(null);
    setLiveDataError(null);
  }

  async function handleGenerate() {
    const target = targetTableName.trim();
    const purpose = businessRequirement.trim();
    if (!selectedSilverTable || !target || !purpose || generating) return;

    resetGeneratedState();
    setGenerating(true);
    try {
      const nameCheck = await checkGoldName(target);
      if (!nameCheck.is_valid_identifier) {
        setWorkflowError(nameCheck.message);
        return;
      }
      const overwrite = !nameCheck.is_available;
      setTargetExists(overwrite);

      const generated = await generateGoldSql({
        target_table_name: target,
        silver_table_names: [selectedSilverTable],
        business_requirement: purpose,
      });
      const reviewed = await reviewGoldSql(generated.run_id);
      if (
        reviewed.run_id !== generated.run_id ||
        reviewed.review_revision !== generated.review_revision ||
        reviewed.generator_provenance !== generated.generator_provenance
      ) {
        throw new Error('Gold review did not match the generated proposal.');
      }
      setReview(reviewed);
    } catch (error: unknown) {
      setWorkflowError(
        calmApiMessage(
          error,
          'Failed to generate and review the controlled Gold proposal.',
        ),
      );
    } finally {
      setGenerating(false);
    }
  }

  async function handleApprove() {
    if (!review || approval || approving) return;
    setApproving(true);
    setWorkflowError(null);
    try {
      const response = await approveGoldSql(review.run_id, {
        review_revision: review.review_revision,
        overwrite: targetExists,
      });
      setApproval(response);
    } catch (error: unknown) {
      setWorkflowError(
        calmApiMessage(error, 'Failed to approve the reviewed Gold proposal.'),
      );
    } finally {
      setApproving(false);
    }
  }

  async function handleExecute() {
    if (!review || !approval || execution || executing) return;
    setExecuting(true);
    setWorkflowError(null);
    try {
      const response = await executeGoldSql(review.run_id, {
        overwrite: approval.overwrite_authorized,
      });
      setExecution(response);
    } catch (error: unknown) {
      setWorkflowError(
        calmApiMessage(error, 'Failed to execute the approved Gold candidate.'),
      );
    } finally {
      setExecuting(false);
    }
  }

  async function loadLiveGoldData(promoted: PromoteGoldResponse) {
    setLoadingLiveData(true);
    setLiveDataError(null);
    try {
      const [discovery, metadata, preview] = await Promise.all([
        listGoldTables(),
        getMetadataTable(promoted.target.table as string, promoted.target.schema as string),
        getLiveTablePreview(
          promoted.target.table as string,
          promoted.target.schema as string,
        ),
      ]);
      const discoveredNames = discovery.tables.map((table) => table.name);
      if (!discoveredNames.includes(promoted.target.table as string)) {
        throw new Error('Promoted Gold relation was not present in live discovery.');
      }
      const metadataTable = metadata.tables?.[0];
      if (!metadataTable) {
        throw new Error('Promoted Gold metadata was not available.');
      }
      setGoldTables(discoveredNames);
      setGoldMetadata(metadataTable);
      setGoldPreview(preview);
    } catch (error: unknown) {
      setLiveDataError(
        calmApiMessage(
          error,
          'Gold promotion succeeded, but live discovery, metadata, or preview could not be verified.',
        ),
      );
    } finally {
      setLoadingLiveData(false);
    }
  }

  async function handlePromote() {
    if (!review || !execution || promotion || promoting) return;
    setPromoting(true);
    setWorkflowError(null);
    try {
      const response = await promoteGoldSql(review.run_id);
      setPromotion(response);
      await loadLiveGoldData(response);
    } catch (error: unknown) {
      setWorkflowError(
        calmApiMessage(error, 'Failed to promote the executed Gold candidate.'),
      );
    } finally {
      setPromoting(false);
    }
  }

  const sources = plannedSources(review);
  const actualTarget = promotion?.target;
  const workflowStatus = promotion
    ? 'Promoted'
    : execution
      ? 'Executed'
      : approval
        ? 'Approved'
        : review
          ? 'Reviewed'
          : 'Ready';
  const liveVerified = Boolean(
    promotion && goldMetadata && goldPreview && !liveDataError,
  );

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runIdParam} />
      <PageAssistant page="gold" layer="gold" runId={runIdParam} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Gold Layer</h2>
          <DataSourceBadge mode={liveVerified ? 'live' : 'planned'} />
          <Badge variant={promotion ? 'pass' : 'secondary'}>{workflowStatus}</Badge>
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Generate, review, approve, execute, and promote a controlled non-LLM Gold projection.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 bg-[#090a10] scrollbar-thin">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-5">
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4">
              <h3 className="text-sm font-semibold text-[#f1f5f9] flex items-center gap-2">
                <Layers size={16} className="text-[#6366f1]" />
                1. Select Silver Source and Gold Target
              </h3>

              {sourceError && (
                <div className="rounded border border-[#ef4444]/30 bg-[#450a0a]/30 p-3 text-xs text-[#fca5a5]">
                  {sourceError}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="block text-xs font-semibold text-[#94a3b8]">
                  Source Silver Relation
                  <select
                    className="mt-1.5 w-full rounded border border-[#252637] p-2.5 bg-[#0b0c12] text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
                    value={selectedSilverTable}
                    disabled={loadingSources || silverTables.length === 0}
                    onChange={(event) => {
                      setSelectedSilverTable(event.target.value);
                      resetGeneratedState();
                    }}
                  >
                    {silverTables.length === 0 ? (
                      <option value="">
                        {loadingSources ? 'Loading live relations…' : 'No Silver relations available'}
                      </option>
                    ) : (
                      silverTables.map((table) => (
                        <option key={table} value={table}>{table}</option>
                      ))
                    )}
                  </select>
                </label>

                <label className="block text-xs font-semibold text-[#94a3b8]">
                  Target Gold Relation
                  <input
                    className="mt-1.5 w-full rounded border border-[#252637] p-2.5 bg-[#0b0c12] text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none font-mono"
                    value={targetTableName}
                    placeholder="e.g. curated_output"
                    onChange={(event) => {
                      setTargetTableName(event.target.value);
                      resetGeneratedState();
                    }}
                  />
                </label>
              </div>

              <label className="block text-xs font-semibold text-[#94a3b8]">
                Business Purpose
                <textarea
                  className="mt-1.5 w-full rounded border border-[#252637] p-2.5 bg-[#0b0c12] text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
                  rows={2}
                  value={businessRequirement}
                  onChange={(event) => {
                    setBusinessRequirement(event.target.value);
                    resetGeneratedState();
                  }}
                />
              </label>

              <div className="flex justify-end">
                <Button
                  variant="primary"
                  isLoading={generating}
                  disabled={
                    generating ||
                    !selectedSilverTable ||
                    !targetTableName.trim() ||
                    !businessRequirement.trim()
                  }
                  onClick={() => void handleGenerate()}
                >
                  Generate and Load Review
                </Button>
              </div>
            </div>

            {review && (
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">
                    2. Reviewed Gold Proposal
                  </h3>
                  <Badge variant={approval ? 'pass' : 'warning'}>
                    {approval ? 'Approved' : 'Review Loaded'}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-[#94a3b8]">
                  <div>Run: <span className="font-mono text-[#cbd5e1]">{review.run_id}</span></div>
                  <div>Status: <span className="font-mono text-[#cbd5e1]">{review.status}</span></div>
                  <div className="md:col-span-2 break-all">
                    Revision: <span className="font-mono text-[#cbd5e1]">{review.review_revision}</span>
                  </div>
                  <div className="md:col-span-2">
                    Provenance: <span className="font-mono text-emerald-400">{review.generator_provenance}</span>
                  </div>
                  <div className="md:col-span-2">
                    Purpose: <span className="text-[#cbd5e1]">{plannedPurpose(review)}</span>
                  </div>
                </div>

                <div className="rounded border border-[#252637] p-4 bg-[#0b0c12] font-mono text-xs text-[#cbd5e1] overflow-x-auto">
                  <pre>{review.sql_text}</pre>
                </div>

                <div className="flex items-center justify-between gap-4 pt-2 border-t border-[#252637]">
                  <p className="text-xs text-[#94a3b8]">
                    {targetExists
                      ? 'The target exists; approval will bind exact overwrite authorization and identity.'
                      : 'The target was absent when checked; approval will bind create-only authority.'}
                  </p>
                  <Button
                    variant="primary"
                    isLoading={approving}
                    disabled={approving || Boolean(approval)}
                    onClick={() => void handleApprove()}
                  >
                    {approval ? 'Approved' : 'Approve Reviewed Revision'}
                  </Button>
                </div>
              </div>
            )}

            {approval && review && (
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">
                    3. Execute Candidate and Promote
                  </h3>
                  <Badge variant={promotion ? 'pass' : 'secondary'}>{workflowStatus}</Badge>
                </div>
                <p className="text-xs text-[#94a3b8]">
                  Execution creates the bound candidate first. Promotion remains a separate safeguarded action.
                </p>
                <div className="flex flex-wrap justify-end gap-3">
                  <Button
                    variant="secondary"
                    isLoading={executing}
                    disabled={executing || Boolean(execution)}
                    onClick={() => void handleExecute()}
                  >
                    {execution ? 'Candidate Executed' : 'Execute Approved Candidate'}
                  </Button>
                  <Button
                    variant="primary"
                    isLoading={promoting}
                    disabled={!execution || promoting || Boolean(promotion)}
                    onClick={() => void handlePromote()}
                  >
                    {promotion ? 'Promoted to Gold' : 'Promote Executed Candidate'}
                  </Button>
                </div>
              </div>
            )}

            {workflowError && (
              <div className="rounded-xl border border-[#ef4444]/30 bg-[#450a0a]/30 p-4 text-xs text-[#fca5a5] flex items-center gap-2">
                <AlertCircle size={15} />
                <span>{workflowError}</span>
              </div>
            )}
          </div>

          <div className="space-y-5">
            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-3">
              <h3 className="text-sm font-semibold text-[#f1f5f9]">Live Gold State</h3>
              <div className="space-y-2 text-xs text-[#94a3b8]">
                <div className="flex justify-between gap-3 border-b border-[#252637] py-1.5">
                  <span>Source</span>
                  <span className="font-mono text-right text-[#cbd5e1]">
                    {sources[0] || selectedSilverTable || '—'}
                  </span>
                </div>
                <div className="flex justify-between gap-3 border-b border-[#252637] py-1.5">
                  <span>Target</span>
                  <span className="font-mono text-right text-[#cbd5e1]">
                    {actualTarget
                      ? `${String(actualTarget.schema)}.${String(actualTarget.table)}`
                      : targetTableName || '—'}
                  </span>
                </div>
                <div className="flex justify-between gap-3 border-b border-[#252637] py-1.5">
                  <span>Discovery</span>
                  <span className="text-right text-[#cbd5e1]">
                    {promotion
                      ? goldTables.includes(String(promotion.target.table))
                        ? 'Discovered'
                        : 'Not verified'
                      : 'Not promoted'}
                  </span>
                </div>
                <div className="flex justify-between gap-3 py-1.5">
                  <span>Row Count</span>
                  <span className="font-semibold text-[#f1f5f9]">
                    {goldMetadata ? goldMetadata.row_count.toLocaleString() : '—'}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Live Gold Preview</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!promotion || loadingLiveData}
                  onClick={() => promotion && void loadLiveGoldData(promotion)}
                >
                  <RefreshCw size={14} className={loadingLiveData ? 'animate-spin' : ''} />
                </Button>
              </div>

              {liveDataError && (
                <div className="rounded border border-[#ef4444]/30 bg-[#450a0a]/30 p-3 text-xs text-[#fca5a5]">
                  {liveDataError}
                </div>
              )}

              {goldPreview ? (
                <div className="space-y-3">
                  <div className="text-xs text-[#94a3b8]">
                    {goldPreview.column_count} columns · {goldPreview.row_count.toLocaleString()} rows
                  </div>
                  <div className="overflow-x-auto rounded border border-[#252637] bg-[#0b0c12]">
                    <table className="w-full text-left text-xs text-[#e5e7eb]">
                      <thead className="bg-[#13141e] text-[#94a3b8] border-b border-[#252637]">
                        <tr>
                          {goldPreview.columns.map((column) => (
                            <th key={column.name} className="px-2.5 py-2 font-semibold font-mono">
                              {column.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#252637]">
                        {goldPreview.rows.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {goldPreview.columns.map((column) => (
                              <td key={column.name} className="px-2.5 py-2 font-mono text-[#cbd5e1]">
                                {row[column.name] === null || row[column.name] === undefined
                                  ? '—'
                                  : String(row[column.name])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {goldPreview.rows.length === 0 && (
                    <p className="text-xs text-[#6b7280]">The promoted relation contains no rows.</p>
                  )}
                </div>
              ) : (
                <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#6b7280]">
                  {loadingLiveData
                    ? 'Loading live discovery, metadata, and rows…'
                    : 'Promote the candidate to load live Gold rows.'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() =>
            navigate(
              `/projects/${encodeURIComponent(id || '')}/silver?table=${encodeURIComponent(selectedSilverTable)}`,
            )
          }
        >
          Back to Silver
        </Button>
        {liveVerified && promotion && (
          <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1.5">
            <CheckCircle2 size={16} />
            Live promotion verified: {sources[0]} → {String(promotion.target.schema)}.{String(promotion.target.table)}
          </span>
        )}
      </div>
    </div>
  );
}
