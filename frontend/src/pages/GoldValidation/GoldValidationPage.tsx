import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Circle,
  ClipboardCheck,
  Code2,
  Database,
  FileCheck2,
  Layers,
  LockKeyhole,
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
  if (value === null || value === undefined || value === '') return 'Not returned';
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
  return fallback || 'Not returned';
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
    <div className="flex items-start justify-between gap-3 border-b border-[#252637] py-2 last:border-b-0">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[#6b7280]">
        {label}
      </span>
      <span
        className={`max-w-[68%] text-right text-xs text-[#e5e7eb] ${
          mono ? 'font-mono whitespace-pre-wrap break-words' : ''
        }`}
      >
        {displayValue(value)}
      </span>
    </div>
  );
}

function FlowStep({
  label,
  detail,
  complete,
  active,
}: {
  label: string;
  detail: string;
  complete: boolean;
  active?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        complete
          ? 'border-[#22c55e]/30 bg-[#22c55e]/10'
          : active
            ? 'border-[#6366f1]/35 bg-[#6366f1]/10'
            : 'border-[#252637] bg-[#0b0c12]'
      }`}
    >
      <div className="flex items-center gap-2">
        {complete ? (
          <CheckCircle2 size={15} className="text-[#22c55e]" />
        ) : (
          <Circle size={15} className={active ? 'text-[#6366f1]' : 'text-[#4b5563]'} />
        )}
        <span className="text-xs font-semibold text-[#f1f5f9]">{label}</span>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-[#6b7280]">{detail}</p>
    </div>
  );
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
      setGeneratedGold(generated);
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
    : targetTableName || 'Not returned';
  const generatorFamily = generatedFamily(generatedGold, review);
  const generatorModel = generatedModel(generatedGold, review);
  const flowSteps = [
    {
      label: 'Business requirement',
      detail: review ? 'Accepted into the backend proposal.' : 'Enter the requirement before generation.',
      complete: Boolean(review),
      active: !review,
    },
    {
      label: 'Gemini interpretation',
      detail: interpretation ? 'Backend returned interpretation fields.' : 'Shown only when backend returns it.',
      complete: Boolean(interpretation),
      active: generating,
    },
    {
      label: 'Aurum deterministic plan',
      detail: review ? 'Structured plan and SQL are loaded for review.' : 'Waiting for reviewed plan.',
      complete: Boolean(review),
    },
    {
      label: 'Review',
      detail: review ? review.status : 'No reviewed run yet.',
      complete: Boolean(review),
    },
    {
      label: 'Approve',
      detail: approval ? approval.status : 'Requires the reviewed revision.',
      complete: Boolean(approval),
    },
    {
      label: 'Execute',
      detail: execution ? execution.status : 'Requires approval.',
      complete: Boolean(execution),
    },
    {
      label: 'Promote',
      detail: promotion ? promotion.status : 'Requires executed candidate.',
      complete: Boolean(promotion),
    },
    {
      label: 'Result',
      detail: liveVerified ? 'Live Gold discovery and preview loaded.' : 'Live result not verified yet.',
      complete: liveVerified,
    },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={runIdParam} />
      <PageAssistant page="gold" layer="gold" runId={runIdParam} selectedTable={selectedSilverTable || targetTableName || tableParam || undefined} />

      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Gold Layer</h2>
          {liveVerified ? (
            <DataSourceBadge mode="live" />
          ) : (
            <Badge variant="secondary">Ready</Badge>
          )}
          <Badge variant={promotion ? 'pass' : 'secondary'}>{workflowStatus}</Badge>
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Turn an approved Silver relation into a reviewed, approved, executed, and promoted Gold result.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto bg-[#090a10] p-6 scrollbar-thin">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-5">
            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                    <Layers size={16} className="text-[#6366f1]" />
                    Gold Request
                  </h3>
                  <p className="mt-1 text-xs text-[#6b7280]">
                    Select the approved Silver input, name the Gold target, and describe the result.
                  </p>
                </div>
                <Badge variant={review ? 'pass' : 'secondary'} dot={Boolean(review)}>
                  {review ? 'Backend reviewed' : 'Not generated'}
                </Badge>
              </div>

              {sourceError && (
                <div className="mb-4 rounded border border-[#ef4444]/30 bg-[#450a0a]/30 p-3 text-xs text-[#fca5a5]">
                  {sourceError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="block text-xs font-semibold text-[#94a3b8]">
                  Source Silver Relation
                  <select
                    className="mt-1.5 w-full rounded-lg border border-[#252637] bg-[#0b0c12] p-2.5 font-mono text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
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
                  Target Gold Relation
                  <input
                    className="mt-1.5 w-full rounded-lg border border-[#252637] bg-[#0b0c12] p-2.5 font-mono text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
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
                Business Requirement
                <textarea
                  className="mt-1.5 min-h-28 w-full resize-y rounded-lg border border-[#252637] bg-[#0b0c12] p-3 text-sm leading-relaxed text-[#e5e7eb] focus:border-[#6366f1] focus:outline-none"
                  value={businessRequirement}
                  onChange={(event) => {
                    setBusinessRequirement(event.target.value);
                    resetGeneratedState();
                  }}
                />
              </label>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-[#6b7280]">
                  {businessRequirement.trim().length.toLocaleString()} characters sent to the backend.
                </span>
                <Button
                  variant="primary"
                  isLoading={generating}
                  rightIcon={<ArrowRight size={15} />}
                  disabled={
                    generating ||
                    !selectedSilverTable ||
                    !targetTableName.trim() ||
                    !businessRequirement.trim()
                  }
                  onClick={() => void handleGenerate()}
                >
                  Generate and Review
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                  <ClipboardCheck size={16} className="text-[#6366f1]" />
                  Lifecycle
                </h3>
                <Badge variant={promotion ? 'pass' : review ? 'primary' : 'secondary'}>
                  {workflowStatus}
                </Badge>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                {flowSteps.map((step) => (
                  <FlowStep key={step.label} {...step} />
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                    <BrainCircuit size={16} className="text-[#a78bfa]" />
                    What Aurum Understood
                  </h3>
                  <p className="mt-1 text-xs text-[#6b7280]">
                    Gemini interpretation is shown separately from the deterministic execution plan.
                  </p>
                </div>
                <Badge variant={interpretation ? 'primary' : 'secondary'}>
                  {interpretation ? 'Interpretation returned' : 'Interpretation pending'}
                </Badge>
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="rounded-lg border border-[#312e81]/45 bg-[#141224] p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <Sparkles size={15} className="text-[#a78bfa]" />
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-[#c4b5fd]">
                      Gemini interpretation
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
                    <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-4 text-xs leading-relaxed text-[#94a3b8]">
                      No Gemini interpretation fields were returned by the current backend response.
                    </div>
                  )}
                </div>

                <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <Target size={15} className="text-[#6366f1]" />
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">
                      Aurum deterministic execution plan
                    </h4>
                  </div>
                  <DetailRow label="Source" value={plannedSource} mono />
                  <DetailRow label="Dimension" value={review?.planned_changes.dimension} mono />
                  <DetailRow label="Aggregation" value={plannedMetric?.aggregation} mono />
                  <DetailRow label="Expression" value={expressionLabel(plannedMetric?.expression)} mono />
                  <DetailRow label="Alias" value={plannedMetric?.alias} mono />
                  <DetailRow label="Target" value={plannedTarget} mono />
                  <DetailRow label="Generator family" value={generatorFamily} mono />
                  <DetailRow label="Generator model" value={generatorModel} mono />
                  <DetailRow label="Provenance" value={review?.generator_provenance} mono />
                </div>
              </div>
            </div>

            {review && (
              <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                      <FileCheck2 size={16} className="text-[#6366f1]" />
                      Review and Approval
                    </h3>
                    <p className="mt-1 text-xs text-[#6b7280]">
                      Review revision and SQL are backend-returned. Approval binds this exact revision.
                    </p>
                  </div>
                  <Badge variant={approval ? 'pass' : 'warning'}>
                    {approval ? 'Approved' : 'Review loaded'}
                  </Badge>
                </div>

                <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                    <DetailRow label="Run" value={review.run_id} mono />
                    <DetailRow label="Review status" value={review.status} mono />
                    <DetailRow label="Executable" value={review.executable ? 'Yes' : 'No'} mono />
                  </div>
                  <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                    <DetailRow label="Revision" value={review.review_revision} mono />
                    <DetailRow
                      label="Target mode"
                      value={targetExists ? 'Existing target overwrite requested' : 'Create new target'}
                    />
                    <DetailRow label="Purpose" value={plannedPurpose(review)} />
                  </div>
                </div>

                <div className="h-[360px] overflow-hidden rounded-xl border border-[#252637]">
                  <SQLViewer title="CONTROLLED GOLD SQL" code={review.sql_text} />
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-4 border-t border-[#252637] pt-4">
                  <p className="max-w-xl text-xs leading-relaxed text-[#94a3b8]">
                    {targetExists
                      ? 'The target exists; approval authorizes overwrite only for the reviewed run.'
                      : 'The target was absent when checked; approval authorizes create-only execution.'}
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
              <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                      <Code2 size={16} className="text-[#6366f1]" />
                      Execute and Promote
                    </h3>
                    <p className="mt-1 text-xs text-[#6b7280]">
                      Execution creates the candidate. Promotion is the separate controlled final stage.
                    </p>
                  </div>
                  <Badge variant={promotion ? 'pass' : execution ? 'primary' : 'secondary'}>
                    {workflowStatus}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-4">
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">
                      Candidate execution
                    </h4>
                    <DetailRow label="Status" value={execution?.status} mono />
                    <DetailRow label="Claim" value={execution?.execution_claim_id} mono />
                    <Button
                      className="mt-3 w-full"
                      variant="secondary"
                      isLoading={executing}
                      disabled={executing || Boolean(execution)}
                      onClick={() => void handleExecute()}
                    >
                      {execution ? 'Candidate Executed' : 'Execute Approved Candidate'}
                    </Button>
                  </div>

                  <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-4">
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">
                      Gold promotion
                    </h4>
                    <DetailRow label="Status" value={promotion?.status} mono />
                    <DetailRow label="Claim" value={promotion?.promotion_claim_id} mono />
                    <Button
                      className="mt-3 w-full"
                      variant="primary"
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

            {workflowError && (
              <div className="flex items-start gap-2 rounded-xl border border-[#ef4444]/30 bg-[#450a0a]/30 p-4 text-xs text-[#fca5a5]">
                <AlertCircle size={15} className="mt-0.5 flex-shrink-0" />
                <span>{workflowError}</span>
              </div>
            )}
          </div>

          <aside className="space-y-5">
            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                <LockKeyhole size={16} className="text-[#22c55e]" />
                Why should I trust this?
              </h3>
              <div className="space-y-2 text-xs leading-relaxed text-[#94a3b8]">
                <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                  Gemini interprets the requirement when the backend returns an interpretation.
                </div>
                <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                  Aurum validates a structured proposal before review state is shown.
                </div>
                <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                  Execution uses the controlled SQL returned in the review.
                </div>
                <div className="rounded-lg border border-[#252637] bg-[#0b0c12] p-3">
                  Approval happens before execution, and promotion is a separate controlled stage.
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#f1f5f9]">
                <Database size={16} className="text-[#6366f1]" />
                Gold Result
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

            <div className="rounded-xl border border-[#252637] bg-[#0d0e14] p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-[#f1f5f9]">Live Preview</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!promotion || loadingLiveData}
                  onClick={() => promotion && void loadLiveGoldData(promotion)}
                  aria-label="Refresh live Gold preview"
                >
                  <RefreshCw size={14} className={loadingLiveData ? 'animate-spin' : ''} />
                </Button>
              </div>

              {liveDataError && (
                <div className="mb-3 rounded border border-[#ef4444]/30 bg-[#450a0a]/30 p-3 text-xs text-[#fca5a5]">
                  {liveDataError}
                </div>
              )}

              {goldPreview ? (
                <div className="space-y-3">
                  <div className="text-xs text-[#94a3b8]">
                    {goldPreview.column_count} columns · {goldPreview.row_count.toLocaleString()} rows
                  </div>
                  <div className="max-h-[360px] overflow-auto rounded-lg border border-[#252637] bg-[#0b0c12]">
                    <table className="w-full text-left text-xs text-[#e5e7eb]">
                      <thead className="sticky top-0 border-b border-[#252637] bg-[#13141e] text-[#94a3b8]">
                        <tr>
                          {goldPreview.columns.map((column) => (
                            <th key={column.name} className="px-2.5 py-2 font-mono font-semibold">
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
                                  ? '-'
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
                    ? 'Loading live discovery, metadata, and rows...'
                    : 'Promote the candidate to load live Gold rows.'}
                </div>
              )}
            </div>
          </aside>
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
