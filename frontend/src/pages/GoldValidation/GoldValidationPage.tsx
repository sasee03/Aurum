import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileCheck2,
  RefreshCw,
  Sparkles,
  Target,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { SQLViewer } from '@/components/common/SQLViewer';
import {
  canSubmitGoldGenerate,
  goldGenerateButtonLabel,
  goldWorkflowError,
} from './goldValidationUx';
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
  type GenerateGoldResponse,
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

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value, null, 2);
}

function relationLabel(value: unknown, fallback?: string): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map((item) => relationLabel(item)).join(', ');
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const schema = typeof record.schema === 'string' ? record.schema : '';
    const table =
      typeof record.table === 'string'
        ? record.table
        : typeof record.relation === 'string'
          ? record.relation
          : '';
    if (schema && table) return `${schema}.${table}`;
    if (table) return table;
  }
  return fallback || '—';
}

function expressionLabel(value: unknown): string {
  if (!value || typeof value !== 'object') return displayValue(value);
  const expression = value as Record<string, unknown>;
  if (expression.type === 'column' && typeof expression.column === 'string') {
    return expression.column;
  }
  return displayValue(value);
}

function generatedFamily(
  generated: GenerateGoldResponse | null,
  review: ReviewGoldResponse | null,
): string {
  return displayValue(review?.generator_family ?? generated?.generator_family);
}

function generatedModel(
  generated: GenerateGoldResponse | null,
  review: ReviewGoldResponse | null,
): string {
  return displayValue(review?.generator_model ?? generated?.generator_model);
}

function understoodInterpretation(generated: GenerateGoldResponse | null) {
  const interpretation = generated?.ai_interpretation;
  if (!interpretation || typeof interpretation !== 'object') return null;
  const record = interpretation as Record<string, any>;
  return record.definition && typeof record.definition === 'object'
    ? record.definition as Record<string, unknown>
    : record;
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: unknown;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-[#1e293b] py-2.5 last:border-b-0">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[#64748b]">
        {label}
      </span>
      <span
        className={`max-w-[68%] text-right text-xs text-[#f8fafc] ${
          mono ? 'font-mono whitespace-pre-wrap break-words' : ''
        }`}
      >
        {displayValue(value)}
      </span>
    </div>
  );
}

export function GoldValidationPage() {
  const { id: _id } = useParams<{ id: string }>();
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
  const [generationPhase, setGenerationPhase] = useState<string | null>(null);
  const [generatedGold, setGeneratedGold] = useState<GenerateGoldResponse | null>(null);
  const [review, setReview] = useState<ReviewGoldResponse | null>(null);
  const [targetExists, setTargetExists] = useState(false);
  const [approval, setApproval] = useState<ApproveGoldResponse | null>(null);
  const [approving, setApproving] = useState(false);
  const [execution, setExecution] = useState<ExecuteGoldResponse | null>(null);
  const [executing, setExecuting] = useState(false);
  const [promotion, setPromotion] = useState<PromoteGoldResponse | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [workflowErrorDetail, setWorkflowErrorDetail] = useState<string | null>(null);
  const reviewSectionRef = useRef<HTMLDivElement | null>(null);

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
    setGeneratedGold(null);
    setReview(null);
    setApproval(null);
    setExecution(null);
    setPromotion(null);
    setTargetExists(false);
    setWorkflowError(null);
    setWorkflowErrorDetail(null);
    setGenerationPhase(null);
    setGoldTables([]);
    setGoldMetadata(null);
    setGoldPreview(null);
    setLiveDataError(null);
  }

  useEffect(() => {
    if (!review || !reviewSectionRef.current) return;
    reviewSectionRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    reviewSectionRef.current.focus({ preventScroll: true });
  }, [review]);

  async function handleGenerate() {
    const target = targetTableName.trim();
    const purpose = businessRequirement.trim();
    if (!selectedSilverTable || !target || !purpose || generating) return;

    resetGeneratedState();
    setGenerating(true);
    setGenerationPhase('Checking Gold target name...');
    try {
      const nameCheck = await checkGoldName(target);
      if (!nameCheck.is_valid_identifier) {
        setWorkflowError(nameCheck.message);
        setWorkflowErrorDetail(null);
        return;
      }
      const overwrite = !nameCheck.is_available;
      setTargetExists(overwrite);

      setGenerationPhase('Understanding requirement...');
      const generated = await generateGoldSql({
        target_table_name: target,
        silver_table_names: [selectedSilverTable],
        business_requirement: purpose,
      });
      setGeneratedGold(generated);
      setGenerationPhase('Preparing review...');
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
      const described = goldWorkflowError(
        error,
        'Failed to generate and review the controlled Gold proposal.',
      );
      setWorkflowError(described.message);
      setWorkflowErrorDetail(described.detail ?? null);
    } finally {
      setGenerating(false);
      setGenerationPhase(null);
    }
  }

  async function handleApprove() {
    if (!review || approval || approving) return;
    setApproving(true);
    setWorkflowError(null);
    setWorkflowErrorDetail(null);
    try {
      const response = await approveGoldSql(review.run_id, {
        review_revision: review.review_revision,
        overwrite: targetExists,
      });
      setApproval(response);
    } catch (error: unknown) {
      const described = goldWorkflowError(error, 'Failed to approve the reviewed Gold proposal.');
      setWorkflowError(described.message);
      setWorkflowErrorDetail(described.detail ?? null);
    } finally {
      setApproving(false);
    }
  }

  async function handleExecute() {
    if (!review || !approval || execution || executing) return;
    setExecuting(true);
    setWorkflowError(null);
    setWorkflowErrorDetail(null);
    try {
      const response = await executeGoldSql(review.run_id, {
        overwrite: approval.overwrite_authorized,
      });
      setExecution(response);
    } catch (error: unknown) {
      const described = goldWorkflowError(error, 'Failed to execute the approved Gold candidate.');
      setWorkflowError(described.message);
      setWorkflowErrorDetail(described.detail ?? null);
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
    setWorkflowErrorDetail(null);
    try {
      const response = await promoteGoldSql(review.run_id);
      setPromotion(response);
      await loadLiveGoldData(response);
    } catch (error: unknown) {
      const described = goldWorkflowError(error, 'Failed to promote the executed Gold candidate.');
      setWorkflowError(described.message);
      setWorkflowErrorDetail(described.detail ?? null);
    } finally {
      setPromoting(false);
    }
  }

  const sources = plannedSources(review);
  const actualTarget = promotion?.target;
  const workflowStatus = promotion
    ? 'Gold Table Live'
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
  const interpretation = understoodInterpretation(generatedGold);
  const plannedMetric =
    review?.planned_changes.metric && typeof review.planned_changes.metric === 'object'
      ? review.planned_changes.metric as Record<string, unknown>
      : null;
  const plannedSource = relationLabel(
    review?.planned_changes.source ?? sources[0],
    selectedSilverTable,
  );
  const plannedTarget = review
    ? relationLabel(
        review.planned_changes.target,
        `${actualTarget?.schema ?? 'gold'}.${review.table_name}`,
      )
    : targetTableName || '—';
  const _generatorFamily = generatedFamily(generatedGold, review);
  const generatorModel = generatedModel(generatedGold, review);

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runIdParam} />
      <PageAssistant page="gold" layer="gold" runId={review?.run_id || generatedGold?.run_id || runIdParam} selectedTable={selectedSilverTable || targetTableName || tableParam || undefined} />

      {/* Header */}
      <div className="px-6 py-5 border-b border-[#1e293b] bg-[#0b0f19]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Gold Business Layer</h2>
          {liveVerified ? (
            <DataSourceBadge mode="live" />
          ) : (
            <Badge variant="secondary">Curation Engine</Badge>
          )}
          <Badge variant={promotion ? 'pass' : 'secondary'}>{workflowStatus}</Badge>
        </div>
        <p className="mt-1 text-sm text-[#94a3b8]">
          Turn an approved Silver relation into a reviewed, approved, executed, and promoted Gold business asset.
        </p>
      </div>

      {/* Content Body */}
      <div className="flex-1 overflow-y-auto bg-[#0b0f19] p-6 scrollbar-thin">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-5">
            {/* 1. Business Question / Request */}
            <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="flex items-center gap-2.5 text-base font-semibold text-[#f8fafc]">
                    <Target size={18} className="text-[#3b82f6]" />
                    Business Requirement
                  </h3>
                  <p className="mt-1 text-xs text-[#94a3b8]">
                    Select the approved Silver input, name the Gold target, and describe the desired output.
                  </p>
                </div>
                <Badge variant={review ? 'pass' : 'secondary'} dot={Boolean(review)}>
                  {review ? 'Backend reviewed' : 'Not generated'}
                </Badge>
              </div>

              {sourceError && (
                <div className="mb-4 rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4 text-xs text-[#ef4444]">
                  {sourceError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="block text-xs font-semibold text-[#94a3b8]">
                  Source Silver Relation
                  <select
                    className="mt-1.5 w-full rounded-lg border border-[#273549] bg-[#131a29] p-2.5 font-mono text-xs text-[#f8fafc] focus:border-[#3b82f6] focus:outline-none"
                    value={selectedSilverTable}
                    disabled={loadingSources || silverTables.length === 0}
                    onChange={(event) => {
                      setSelectedSilverTable(event.target.value);
                      resetGeneratedState();
                    }}
                  >
                    {silverTables.length === 0 ? (
                      <option value="">
                        {loadingSources ? 'Loading live relations...' : 'No Silver relations available'}
                      </option>
                    ) : (
                      silverTables.map((table) => (
                        <option key={table} value={table}>
                          {table}
                        </option>
                      ))
                    )}
                  </select>
                </label>

                <label className="block text-xs font-semibold text-[#94a3b8]">
                  Target Gold Relation Name
                  <input
                    className="mt-1.5 w-full rounded-lg border border-[#273549] bg-[#131a29] p-2.5 font-mono text-xs text-[#f8fafc] focus:border-[#3b82f6] focus:outline-none"
                    value={targetTableName}
                    placeholder="curated_output"
                    onChange={(event) => {
                      setTargetTableName(event.target.value);
                      resetGeneratedState();
                    }}
                  />
                </label>
              </div>

              <label className="mt-4 block text-xs font-semibold text-[#94a3b8]">
                Business Intent &amp; Rules
                <textarea
                  className="mt-1.5 min-h-24 w-full resize-y rounded-lg border border-[#273549] bg-[#131a29] p-3 text-xs leading-relaxed text-[#f8fafc] focus:border-[#3b82f6] focus:outline-none"
                  value={businessRequirement}
                  onChange={(event) => {
                    setBusinessRequirement(event.target.value);
                    resetGeneratedState();
                  }}
                />
              </label>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[#1e293b]">
                <span className="text-xs text-[#64748b]">
                  {businessRequirement.trim().length.toLocaleString()} characters sent to backend engine.
                </span>
                <Button
                  variant="primary"
                  size="md"
                  isLoading={generating}
                  rightIcon={<ArrowRight size={15} />}
                  disabled={
                    !canSubmitGoldGenerate({
                      generating,
                      selectedSilverTable,
                      targetTableName,
                      businessRequirement,
                    })
                  }
                  onClick={() => void handleGenerate()}
                >
                  {goldGenerateButtonLabel(generating, generationPhase)}
                </Button>
              </div>
              {generating && (
                <div className="mt-3 rounded-xl border border-[#3b82f6]/30 bg-[#2563eb]/10 p-3 text-xs font-medium text-[#93c5fd]">
                  {generationPhase ?? 'Understanding requirement...'}
                </div>
              )}
              {workflowError && (
                <div className="mt-3 rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4 text-xs text-[#ef4444] space-y-2">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertCircle size={16} />
                    Gold action failed
                  </div>
                  <p>{workflowError}</p>
                  {workflowErrorDetail && (
                    <details className="text-[#fca5a5]">
                      <summary className="cursor-pointer font-semibold">Technical details</summary>
                      <p className="mt-2 font-mono text-[11px] break-words">{workflowErrorDetail}</p>
                    </details>
                  )}
                </div>
              )}
            </div>

            {/* 2. What Aurum Understood */}
            <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2.5 text-base font-semibold text-[#f8fafc]">
                    <BrainCircuit size={18} className="text-[#06b6d4]" />
                    What Aurum Understood
                  </h3>
                  <p className="mt-1 text-xs text-[#94a3b8]">
                    Gemini interpretation vs. Aurum&apos;s deterministic execution plan.
                  </p>
                </div>
                <Badge variant={interpretation ? 'accent' : 'secondary'}>
                  {interpretation ? 'AI Interpretation Returned' : 'Pending Generation'}
                </Badge>
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-[#06b6d4]/30 bg-[#06b6d4]/5 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <Sparkles size={15} className="text-[#06b6d4]" />
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-[#06b6d4]">
                      AI Interpretation
                    </h4>
                  </div>
                  {interpretation ? (
                    <div>
                      <DetailRow label="Dimension" value={interpretation.dimension} mono />
                      <DetailRow label="Aggregation" value={interpretation.aggregation} mono />
                      <DetailRow label="Expression" value={expressionLabel(interpretation.expression)} mono />
                      <DetailRow label="Alias" value={interpretation.alias} mono />
                      <DetailRow label="Verdict" value={generatedGold?.verdict} mono />
                    </div>
                  ) : (
                    <div className="rounded-lg border border-[#1e293b] bg-[#131a29] p-4 text-xs leading-relaxed text-[#94a3b8]">
                      No AI interpretation returned yet. Click &quot;Generate and Review&quot; above.
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <Target size={15} className="text-[#3b82f6]" />
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-[#3b82f6]">
                      Deterministic Plan
                    </h4>
                  </div>
                  <DetailRow label="Source" value={plannedSource} mono />
                  <DetailRow label="Dimension" value={review?.planned_changes.dimension} mono />
                  <DetailRow label="Aggregation" value={plannedMetric?.aggregation} mono />
                  <DetailRow label="Expression" value={expressionLabel(plannedMetric?.expression)} mono />
                  <DetailRow label="Alias" value={plannedMetric?.alias} mono />
                  <DetailRow label="Target" value={plannedTarget} mono />
                  <DetailRow label="Generator Model" value={generatorModel} mono />
                </div>
              </div>
            </div>

            {/* 3. Review and Approval */}
            {review && (
              <div
                ref={reviewSectionRef}
                tabIndex={-1}
                className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm space-y-4 focus:outline-none focus:ring-2 focus:ring-[#3b82f6]/60"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2.5 text-base font-semibold text-[#f8fafc]">
                      <FileCheck2 size={18} className="text-[#3b82f6]" />
                      Review &amp; Approval Gate
                    </h3>
                    <p className="mt-1 text-xs text-[#94a3b8]">
                      Review SQL proposal before authorizing candidate creation.
                    </p>
                  </div>
                  <Badge variant={approval ? 'pass' : 'warning'}>
                    {approval ? 'Approved' : 'Review Pending'}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-[#1e293b] bg-[#131a29] p-3.5">
                    <DetailRow label="Run ID" value={review.run_id} mono />
                    <DetailRow label="Review Status" value={review.status} mono />
                    <DetailRow label="Executable" value={review.executable ? 'Yes' : 'No'} mono />
                  </div>
                  <div className="rounded-lg border border-[#1e293b] bg-[#131a29] p-3.5">
                    <DetailRow label="Revision" value={review.review_revision} mono />
                    <DetailRow
                      label="Target Mode"
                      value={targetExists ? 'Overwrite existing table' : 'Create new table'}
                    />
                    <DetailRow label="Purpose" value={plannedPurpose(review)} />
                  </div>
                </div>

                <div className="h-[320px] overflow-hidden rounded-xl border border-[#1e293b]">
                  <SQLViewer title="CONTROLLED GOLD SQL" code={review.sql_text} />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[#1e293b] pt-4">
                  <p className="max-w-xl text-xs leading-relaxed text-[#94a3b8]">
                    {targetExists
                      ? 'Target relation exists; approval authorizes overwrite only for this reviewed run.'
                      : 'Target relation is clear; approval authorizes create execution.'}
                  </p>
                  <Button
                    variant="primary"
                    size="md"
                    isLoading={approving}
                    disabled={approving || Boolean(approval)}
                    onClick={() => void handleApprove()}
                  >
                    {approval ? 'Approved' : 'Approve Reviewed Revision'}
                  </Button>
                </div>
              </div>
            )}

            {/* 4. Controlled Build & Publish */}
            {approval && review && (
              <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2.5 text-base font-semibold text-[#f8fafc]">
                      <Database size={18} className="text-[#10b981]" />
                      Controlled Build &amp; Publish
                    </h3>
                    <p className="mt-1 text-xs text-[#94a3b8]">
                      Execution creates candidate; promotion publishes live Gold dataset.
                    </p>
                  </div>
                  <Badge variant={promotion ? 'pass' : execution ? 'accent' : 'secondary'}>
                    {workflowStatus}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4 space-y-3">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-[#94a3b8]">
                      1. Candidate Execution
                    </h4>
                    <DetailRow label="Status" value={execution?.status} mono />
                    <DetailRow label="Claim ID" value={execution?.execution_claim_id} mono />
                    <Button
                      className="w-full mt-2"
                      variant="secondary"
                      size="sm"
                      isLoading={executing}
                      disabled={executing || Boolean(execution)}
                      onClick={() => void handleExecute()}
                    >
                      {execution ? 'Candidate Executed' : 'Execute Approved Candidate'}
                    </Button>
                  </div>

                  <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-4 space-y-3">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-[#94a3b8]">
                      2. Gold Promotion
                    </h4>
                    <DetailRow label="Status" value={promotion?.status} mono />
                    <DetailRow label="Claim ID" value={promotion?.promotion_claim_id} mono />
                    <Button
                      className="w-full mt-2"
                      variant="primary"
                      size="sm"
                      isLoading={promoting}
                      disabled={!execution || promoting || Boolean(promotion)}
                      onClick={() => void handlePromote()}
                    >
                      {promotion ? 'Promoted to Gold' : 'Promote Executed Candidate'}
                    </Button>
                  </div>
                </div>
              </div>
            )}

          </div>

          {/* Right Column: Live Result Preview & Metadata */}
          <aside className="space-y-5">
            <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-[#f8fafc]">Live Gold Preview</h3>
                <button
                  type="button"
                  disabled={!promotion || loadingLiveData}
                  onClick={() => promotion && void loadLiveGoldData(promotion)}
                  className="p-1 text-[#64748b] hover:text-[#f8fafc] transition-colors disabled:opacity-40 cursor-pointer"
                  title="Refresh live Gold preview"
                >
                  <RefreshCw size={14} className={loadingLiveData ? 'animate-spin' : ''} />
                </button>
              </div>

              {liveDataError && (
                <div className="mb-3 rounded-lg border border-[#ef4444]/30 bg-[#ef4444]/10 p-3 text-xs text-[#ef4444]">
                  {liveDataError}
                </div>
              )}

              {goldPreview ? (
                <div className="space-y-3">
                  <div className="text-xs text-[#94a3b8] font-mono">
                    {goldPreview.column_count} cols · {goldPreview.row_count.toLocaleString()} rows
                  </div>
                  <div className="max-h-[320px] overflow-auto rounded-lg border border-[#1e293b] bg-[#0b0f19] scrollbar-thin">
                    <table className="w-full text-left text-xs whitespace-nowrap">
                      <thead className="sticky top-0 border-b border-[#1e293b] bg-[#131a29] text-[#94a3b8]">
                        <tr>
                          {goldPreview.columns.map((column) => (
                            <th key={column.name} className="px-3 py-2 font-mono font-semibold border-r border-[#1e293b] last:border-r-0">
                              {column.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#1e293b]">
                        {goldPreview.rows.map((row, rowIndex) => (
                          <tr key={rowIndex} className="hover:bg-[#131a29] transition-colors">
                            {goldPreview.columns.map((column) => (
                              <td key={column.name} className="px-3 py-2 font-mono text-[#f8fafc] text-[12px] border-r border-[#1e293b] last:border-r-0">
                                {row[column.name] === null || row[column.name] === undefined
                                  ? <span className="text-[#64748b] italic">NULL</span>
                                  : String(row[column.name])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {goldPreview.rows.length === 0 && (
                    <p className="text-xs text-[#94a3b8] italic">The promoted relation contains 0 rows.</p>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-[#1e293b] bg-[#131a29] p-6 text-center text-xs text-[#94a3b8]">
                  {loadingLiveData
                    ? 'Loading live discovery, metadata, and rows...'
                    : 'Promote candidate to view live Gold data.'}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-sm">
              <h3 className="mb-3 flex items-center gap-2 text-base font-semibold text-[#f8fafc]">
                <Database size={18} className="text-[#3b82f6]" />
                Gold Dataset Summary
              </h3>
              <div className="space-y-1 text-xs text-[#94a3b8]">
                <DetailRow label="Source" value={plannedSource} mono />
                <DetailRow
                  label="Target"
                  value={
                    actualTarget
                      ? `${String(actualTarget.schema)}.${String(actualTarget.table)}`
                      : plannedTarget
                  }
                  mono
                />
                <DetailRow
                  label="Discovery"
                  value={
                    promotion
                      ? goldTables.includes(String(promotion.target.table))
                        ? 'Discovered'
                        : 'Not verified'
                      : 'Not promoted'
                  }
                />
                <DetailRow
                  label="Rows"
                  value={goldMetadata ? goldMetadata.row_count.toLocaleString() : undefined}
                  mono
                />
                <DetailRow
                  label="Columns"
                  value={goldMetadata ? goldMetadata.column_count.toLocaleString() : undefined}
                  mono
                />
              </div>
            </div>
          </aside>
        </div>
      </div>

      {/* Footer Navigation Bar */}
      <div
        data-assistant-safe-zone="bottom-action"
        className="border-t border-[#1e293b] bg-[#0b0f19] px-6 py-4 flex items-center justify-end shadow-lg"
      >
        {liveVerified && promotion ? (
          <span className="text-xs text-[#10b981] font-semibold flex items-center gap-1.5">
            <CheckCircle2 size={16} />
            Live Gold promotion verified: {sources[0]} → {String(promotion.target.schema)}.{String(promotion.target.table)}
          </span>
        ) : (
          <span className="text-xs text-[#94a3b8]">
            Gold curation pipeline complete
          </span>
        )}
      </div>
    </div>
  );
}
