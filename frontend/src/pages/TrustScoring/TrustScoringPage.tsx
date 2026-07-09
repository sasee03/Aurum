import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight, Lock } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge, VerdictBadge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { cn } from '@/utils/cn';

/** Deterministic weights from src/engines/trust_engine.py — read-only display. */
const TRUST_WEIGHTS = [
  { status: 'FAIL', delta: -50 },
  { status: 'IMPACTED', delta: -10 },
  { status: 'WARN', delta: -5 },
  { status: 'PASS', delta: 0 },
  { status: 'SKIPPED', delta: 0 },
] as const;

const BASE_SCORE = 100;

function gaugeColor(score: number): string {
  if (score < 70) return '#ef4444';
  if (score < 100) return '#f59e0b';
  return '#22c55e';
}

function layerRingStyle(status: string): { stroke: string; badge: 'pass' | 'warning' | 'failed' | 'default' } {
  const u = status.toUpperCase();
  if (u === 'PASS') return { stroke: '#22c55e', badge: 'pass' };
  if (u === 'WARN') return { stroke: '#f59e0b', badge: 'warning' };
  if (u === 'FAIL') return { stroke: '#ef4444', badge: 'failed' };
  if (u === 'IMPACTED') return { stroke: '#f97316', badge: 'failed' };
  if (u === 'SKIPPED') return { stroke: '#6b7280', badge: 'default' };
  return { stroke: '#6b7280', badge: 'default' };
}

interface TrustScoreGaugeProps {
  score: number;
}

/** One real overall gauge — arc length = trust_score / 100 from the report. */
function TrustScoreGauge({ score }: TrustScoreGaugeProps) {
  const radius = 72;
  const stroke = 10;
  const normalizedRadius = radius - stroke / 2;
  const circumference = 2 * Math.PI * normalizedRadius;
  const progress = Math.max(0, Math.min(100, score)) / 100;
  const dashOffset = circumference * (1 - progress);
  const color = gaugeColor(score);

  return (
    <div className="flex flex-col items-center">
      <div className="relative">
        <svg width={radius * 2} height={radius * 2} className="-rotate-90">
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke="#1a1b28"
            strokeWidth={stroke}
          />
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            className="transition-all duration-700 ease-out"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-bold text-[#f1f5f9]">{score}</span>
          <span className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
            / 100
          </span>
        </div>
      </div>
      <p className="mt-3 text-xs text-[#6b7280]">Engine-computed trust_score</p>
    </div>
  );
}

interface LayerStatusRingProps {
  layer: string;
  status: string;
}

/**
 * Status-derived ring — full circle colored by layer_status verbatim.
 * No per-layer numeric score; status label is the data.
 */
function LayerStatusRing({ layer, status }: LayerStatusRingProps) {
  const radius = 52;
  const stroke = 8;
  const normalizedRadius = radius - stroke / 2;
  const circumference = 2 * Math.PI * normalizedRadius;
  const { stroke: color, badge } = layerRingStyle(status);
  const dashed = status.toUpperCase() === 'SKIPPED';

  return (
    <div className="flex flex-col items-center rounded-xl border border-[#252637] bg-[#13141e] px-5 py-4">
      <div className="relative">
        <svg width={radius * 2} height={radius * 2} className="-rotate-90">
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke="#1a1b28"
            strokeWidth={stroke}
          />
          <circle
            cx={radius}
            cy={radius}
            r={normalizedRadius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={dashed ? `${circumference * 0.12} ${circumference * 0.08}` : circumference}
            strokeDashoffset={0}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <Badge variant={badge}>{status}</Badge>
        </div>
      </div>
      <p className="mt-3 text-sm font-semibold capitalize text-[#f1f5f9]">{layer}</p>
      <p className="text-[10px] text-[#6b7280]">layer_status.{layer}</p>
    </div>
  );
}

export function TrustScoringPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { displayMode } = useAppMode();
  const { data, isLoading } = useReport();
  const report = data?.report;
  const coverage = report?.coverage;

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav runId={report?.run_id} />
      <PageAssistant page="dashboard" runId={report?.run_id} />

      <div className="px-6 py-6 border-b border-[#252637] flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Trust Scoring</h2>
        <DataSourceBadge mode={displayMode} />
        {report && <VerdictBadge verdict={report.final_verdict} />}
        {report && (
          <Badge variant="secondary">Severity: {report.severity}</Badge>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {isLoading ? (
          <LoadingSkeleton count={3} className="h-32" />
        ) : report ? (
          <>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[auto_1fr]">
              <div className="flex justify-center rounded-xl border border-[#252637] bg-[#13141e] p-6">
                <TrustScoreGauge score={report.trust_score} />
              </div>

              <div className="space-y-4">
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                    Layer status rings
                  </h3>
                  <p className="mt-1 text-xs text-[#6b7280]">
                    Color and label from layer_status — no per-layer trust percentage.
                  </p>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <LayerStatusRing layer="bronze" status={report.layer_status.bronze} />
                  <LayerStatusRing layer="silver" status={report.layer_status.silver} />
                  <LayerStatusRing layer="gold" status={report.layer_status.gold} />
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5">
              <div className="mb-4 flex items-center gap-2">
                <Lock size={14} className="text-[#6b7280]" />
                <h3 className="text-sm font-semibold text-[#f1f5f9]">
                  Deterministic scoring weights
                </h3>
                <Badge variant="secondary">Read-only</Badge>
              </div>
              <p className="mb-4 text-xs text-[#6b7280]">
                From TrustScoringEngine — base {BASE_SCORE}, then one delta per check by status.
              </p>
              <div className="overflow-hidden rounded-lg border border-[#252637]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#252637] bg-[#0d0e14] text-left text-xs uppercase tracking-widest text-[#6b7280]">
                      <th className="px-4 py-2 font-semibold">Check status</th>
                      <th className="px-4 py-2 font-semibold">Score delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-[#252637]">
                      <td className="px-4 py-2.5 font-mono text-[#94a3b8]">base_score</td>
                      <td className="px-4 py-2.5 font-semibold text-[#f1f5f9]">
                        +{BASE_SCORE}
                      </td>
                    </tr>
                    {TRUST_WEIGHTS.map(({ status, delta }) => (
                      <tr key={status} className="border-b border-[#252637] last:border-b-0">
                        <td className="px-4 py-2.5">
                          <Badge variant={layerRingStyle(status).badge}>{status}</Badge>
                        </td>
                        <td
                          className={cn(
                            'px-4 py-2.5 font-semibold',
                            delta < 0 ? 'text-[#ef4444]' : 'text-[#94a3b8]',
                          )}
                        >
                          {delta > 0 ? `+${delta}` : delta}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-[#6b7280]">
                Final score clamped to 0–100. Verdict thresholds: &lt;70 NOT TRUSTED, &lt;100
                WARNING, 100 TRUSTED.
              </p>
            </div>

            {coverage && (
              <div className="rounded-xl border border-[#252637] bg-[#13141e] p-5">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                  Check coverage (from report)
                </h3>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="default">{coverage.total_checks} total</Badge>
                  <Badge variant="pass">{coverage.passed} PASS</Badge>
                  <Badge variant="warning">{coverage.warned} WARN</Badge>
                  <Badge variant="failed">{coverage.failed} FAIL</Badge>
                  <Badge variant="failed">{coverage.impacted} IMPACTED</Badge>
                  <Badge variant="default">{coverage.skipped} SKIPPED</Badge>
                </div>
                {coverage.verdict_caveat && (
                  <p className="mt-3 text-xs text-[#f59e0b]">{coverage.verdict_caveat}</p>
                )}
              </div>
            )}

            <Badge variant="secondary">
              Narrative is explanation only — does not decide verdict
            </Badge>
            <div className="rounded-lg border border-[#252637] bg-[#13141e] p-4">
              <h3 className="text-sm font-semibold text-[#f1f5f9] mb-2">Trust Narrative</h3>
              <p className="text-sm text-[#94a3b8] whitespace-pre-wrap">
                {report.trust_narrative || 'No narrative available.'}
              </p>
            </div>
          </>
        ) : (
          <p className="text-sm text-[#94a3b8]">
            Trust scoring is not available right now. Load a validation report first.
          </p>
        )}
      </div>

      <div className="border-t border-[#252637] px-6 py-4 flex justify-end">
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          onClick={() => navigate(`/projects/${id}/report/quality`)}
        >
          Quality Report
        </Button>
      </div>
    </div>
  );
}
