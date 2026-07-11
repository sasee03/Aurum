import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  CheckCircle2,
  ExternalLink,
  Info,
  PlayCircle,
  Settings2,
  TriangleAlert,
  XCircle,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { PipelineStepper } from '@/components/common/PipelineStepper';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useReport, withRunIdQuery } from '@/hooks/useReport';
import type { CheckResult } from '@/types/report';
import { formatExpected, formatObserved } from '@/utils/reportFormat';
import { cn } from '@/utils/cn';

type LayerId = 'bronze' | 'silver' | 'gold';

interface RuleDefinition {
  key: string;
  label: string;
  configuredValue: string;
  why: string;
  checkId?: string;
  mappingNote?: string;
}

const STAGES = [
  { id: 'bronze', name: 'Bronze', subtitle: 'Raw Ingestion' },
  { id: 'silver', name: 'Silver', subtitle: 'Transformed' },
  { id: 'gold', name: 'Gold', subtitle: 'KPI / Reports' },
];

const RULES: Record<LayerId, RuleDefinition[]> = {
  bronze: [
    {
      key: 'schema_check',
      label: 'Required schema',
      configuredValue: 'Strict schema: all required columns must be present',
      why: 'Stops malformed source data before it enters the pipeline.',
      checkId: 'B4',
    },
    {
      key: 'null_check',
      label: 'Mandatory values',
      configuredValue: 'Required identifiers and business fields cannot be null',
      why: 'Protects joins, grouping, and downstream calculations from incomplete records.',
      checkId: 'B6',
    },
    {
      key: 'pk_check',
      label: 'Primary-key uniqueness',
      configuredValue: 'Business keys must be unique',
      why: 'Prevents one source record from being counted more than once.',
      checkId: 'B8',
    },
    {
      key: 'duplicate_threshold',
      label: 'Duplicate check',
      configuredValue: 'Max 0.5% duplicate records allowed',
      why: 'Highlights repeat ingestion and accidental record multiplication.',
      checkId: 'B8',
      mappingNote: 'The current report exposes one shared duplicate and key-uniqueness result.',
    },
    {
      key: 'freshness_sla',
      label: 'Freshness window',
      configuredValue: 'Data freshness SLA: 4 hours',
      why: 'Data older than this is flagged stale to surface pipeline delays early.',
    },
    {
      key: 'volume_drift',
      label: 'Volume drift',
      configuredValue: 'Expected row volume may vary by up to 10%',
      why: 'Catches unexpected source growth or data loss before transformation.',
      checkId: 'B2',
    },
  ],
  silver: [
    {
      key: 'join',
      label: 'Customer join',
      configuredValue: 'Join orders to customers',
      why: 'Ensures enrichment uses the intended relationship between source tables.',
    },
    {
      key: 'filter',
      label: 'Record filter',
      configuredValue: "Exclude records where status is 'void'",
      why: 'Prevents an over-broad filter from silently removing valid business records.',
      checkId: 'S10',
    },
    {
      key: 'derived',
      label: 'Net total calculation',
      configuredValue: 'Derive net_total using the configured revenue formula',
      why: 'Keeps the core revenue measure valid before aggregation.',
    },
    {
      key: 'agg_check',
      label: 'Daily revenue aggregation',
      configuredValue: 'Validate the daily_revenue aggregate',
      why: 'Confirms transformed records roll up into the intended reporting grain.',
    },
    {
      key: 'row_delta_tolerance',
      label: 'Row-count change',
      configuredValue: 'Max 0.1% unexpected row-count delta',
      why: 'Makes unexplained record loss between Bronze and Silver visible.',
      checkId: 'S2',
    },
  ],
  gold: [
    {
      key: 'kpi',
      label: 'Business KPI reconciliation',
      configuredValue: 'Validate revenue, margin, and order KPIs',
      why: 'Confirms reported business metrics reconcile with transformed data.',
      checkId: 'G1',
      mappingNote: 'Revenue reconciliation is the representative KPI check in this report.',
    },
    {
      key: 'margin_threshold',
      label: 'Margin threshold',
      configuredValue: 'Minimum acceptable margin: 12%',
      why: 'Surfaces business results that fall below the expected operating margin.',
    },
    {
      key: 'revenue_tolerance',
      label: 'Revenue tolerance',
      configuredValue: 'Revenue may vary by up to 5% from the expected baseline',
      why: 'Separates normal variation from a material upstream revenue impact.',
      checkId: 'G5',
    },
    {
      key: 'report_binding',
      label: 'Report destination',
      configuredValue: 'Publish validated metrics to exec_dashboard',
      why: 'Documents which reporting surface consumes the Gold output.',
    },
  ],
};

function statusPresentation(status: CheckResult['status']) {
  if (status === 'PASS') {
    return { badge: 'pass' as const, icon: CheckCircle2, label: 'Within rule', color: 'text-[#22c55e]' };
  }
  if (status === 'WARN' || status === 'IMPACTED' || status === 'SKIPPED') {
    return {
      badge: 'warning' as const,
      icon: TriangleAlert,
      label: status === 'IMPACTED' ? 'Impacted' : 'Needs attention',
      color: 'text-[#f59e0b]',
    };
  }
  return { badge: 'failed' as const, icon: XCircle, label: 'Outside rule', color: 'text-[#ef4444]' };
}

function CurrentResult({ check, mappingNote }: { check: CheckResult; mappingNote?: string }) {
  const presentation = statusPresentation(check.status);
  const StatusIcon = presentation.icon;

  return (
    <div className="flex gap-3">
      <StatusIcon size={18} className={cn('mt-0.5 shrink-0', presentation.color)} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={presentation.badge}>{check.status}</Badge>
          <span className={cn('text-xs font-semibold', presentation.color)}>{presentation.label}</span>
        </div>
        <p className="mt-2 break-words text-xs text-[#cbd5e1]">
          Current run: <span className="font-semibold text-[#f1f5f9]">{formatObserved(check.observed)}</span>
        </p>
        <p className="mt-1 break-words text-xs text-[#6b7280]">Expected: {formatExpected(check.expected)}</p>
        <p className="mt-2 text-xs leading-relaxed text-[#94a3b8]">{check.detail}</p>
        {mappingNote && <p className="mt-2 text-[11px] leading-relaxed text-[#6b7280]">{mappingNote}</p>}
      </div>
    </div>
  );
}

function RuleCard({ rule, check, onOpen }: { rule: RuleDefinition; check?: CheckResult; onOpen?: () => void }) {
  const content = (
    <>
      <div className="min-w-0 flex-1 text-left">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold text-[#f1f5f9]">{rule.label}</h4>
          <span className="font-mono text-[10px] text-[#6b7280]">{rule.key}</span>
        </div>
        <p className="mt-2 text-sm text-[#cbd5e1]">{rule.configuredValue}</p>
        <p className="mt-2 text-xs leading-relaxed text-[#6b7280]">{rule.why}</p>
      </div>
      <div className="w-full border-t border-[#252637] pt-4 text-left md:w-[42%] md:border-l md:border-t-0 md:pl-5 md:pt-0">
        {check ? (
          <CurrentResult check={check} mappingNote={rule.mappingNote} />
        ) : (
          <div className="flex gap-3">
            <Settings2 size={18} className="mt-0.5 shrink-0 text-[#94a3b8]" />
            <div>
              <Badge variant="default">Configuration only</Badge>
              <p className="mt-2 text-xs leading-relaxed text-[#6b7280]">
                The current report has no corresponding check result for this rule.
              </p>
            </div>
          </div>
        )}
      </div>
      {check && <ExternalLink size={16} className="shrink-0 text-[#6b7280]" aria-hidden="true" />}
    </>
  );
  const className = cn(
    'flex w-full flex-col gap-4 rounded-lg border border-[#252637] bg-[#11121b] p-5 md:flex-row md:items-start',
    check && 'transition-colors hover:border-[#6366f1]/60 hover:bg-[#151622] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6366f1]'
  );

  return check ? (
    <button type="button" className={className} onClick={onOpen} aria-label={`Open ${check.check_id} details for ${rule.label}`}>
      {content}
    </button>
  ) : (
    <article className={className}>{content}</article>
  );
}

export function PipelineConfigPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('runId') ?? undefined;
  const { data, isLoading } = useReport();
  const report = data?.report;
  const activeRunId = runId ?? report?.run_id;
  const [activeStageId, setActiveStageId] = useState<LayerId>('bronze');
  const layerChecks = report?.checks[activeStageId] ?? [];
  const checksById = new Map(layerChecks.map((check) => [check.check_id, check]));

  const openCheck = (checkId: string) => {
    const target = withRunIdQuery(`/projects/${id}/validate/${activeStageId}`, activeRunId);
    navigate(`${target}#${encodeURIComponent(checkId)}`);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in">
      <ProjectSubNav runId={activeRunId} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b border-[#252637] px-6 py-6">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Pipeline Configuration</h2>
          <p className="mt-1 text-sm text-[#6b7280]">
            Understand each validation rule and how the current run performed against it.
          </p>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto p-6 scrollbar-thin">
          <div className="flex gap-3 rounded-lg border border-[#6366f1]/25 bg-[#6366f1]/10 px-4 py-3">
            <Info size={18} className="mt-0.5 shrink-0 text-[#818cf8]" />
            <div>
              <p className="text-sm font-semibold text-[#e0e7ff]">Rules are read-only</p>
              <p className="mt-1 text-xs leading-relaxed text-[#a5b4fc]">
                These rules are not editable in Aurum today. You can see how your current data performed against each rule below.
              </p>
            </div>
          </div>

          <div className="overflow-x-auto pb-1 scrollbar-thin">
            <div className="flex min-w-max justify-center py-2">
              <PipelineStepper
                stages={STAGES}
                activeStageId={activeStageId}
                onSelectStage={(stageId) => setActiveStageId(stageId as LayerId)}
              />
            </div>
          </div>

          <section aria-labelledby={`${activeStageId}-rules-heading`}>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase text-[#22c55e]">{activeStageId} layer</p>
                <h3 id={`${activeStageId}-rules-heading`} className="mt-1 text-lg font-semibold text-[#f1f5f9]">
                  {activeStageId[0].toUpperCase() + activeStageId.slice(1)} validation rules
                </h3>
              </div>
              <p className="text-xs text-[#6b7280]">
                {layerChecks.length > 0 ? `Results from run ${activeRunId ?? report?.run_id}` : 'No run results available'}
              </p>
            </div>

            {isLoading ? (
              <LoadingSkeleton count={4} className="h-36" />
            ) : (
              <div className="space-y-3">
                {RULES[activeStageId].map((rule) => {
                  const check = rule.checkId ? checksById.get(rule.checkId) : undefined;
                  return (
                    <RuleCard
                      key={rule.key}
                      rule={rule}
                      check={check}
                      onOpen={check ? () => openCheck(check.check_id) : undefined}
                    />
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-[#252637] bg-[#0d0e14] px-6 py-4">
          <Button variant="ghost" onClick={() => navigate(withRunIdQuery(`/projects/${id}/connect`, activeRunId))}>
            Back to Connect
          </Button>
          <Button
            variant="primary"
            rightIcon={<PlayCircle size={16} />}
            onClick={() => navigate(withRunIdQuery(`/projects/${id}/validate/execution`, activeRunId))}
          >
            Start Validation
          </Button>
        </div>
      </div>
    </div>
  );
}
