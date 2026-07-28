import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  Code,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Layers,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';
import { DataSourceBadge } from '@/components/common/DataSourceBadge';
import { PageAssistant } from '@/components/common/PageAssistant';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import {
  transformGetRules,
  transformSaveRules,
  transformGenerate,
  transformReview,
  transformExecute,
  getLiveTablePreview,
  type TransformReviewResponse,
  type TransformExecuteResponse,
  type LiveTablePreview,
} from '@/lib/aurumApi';
import { calmApiMessage } from '@/utils/apiErrors';
import {
  formatSilverRule,
  parseSilverRuleInput,
} from '@/utils/silverRules';

export function SilverValidationPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const selectedTableParam = searchParams.get('table');
  const connectionId = searchParams.get('connectionId');
  const sourceSchema = searchParams.get('sourceSchema');
  const sourceTable = searchParams.get('sourceTable');
  const connectorContext =
    connectionId && sourceSchema && sourceTable
      ? { connectionId, source: { schema: sourceSchema, table: sourceTable } }
      : undefined;
  const connectorContextIncomplete = Boolean(connectionId) && !connectorContext;

  // Per-operation async ownership and stale-response protection refs
  const activeTableRef = useRef<string | null>(selectedTableParam);
  const mountedRef = useRef<boolean>(true);
  const loadTokenRef = useRef<number>(0);
  const saveTokenRef = useRef<number>(0);
  const generateTokenRef = useRef<number>(0);
  const executeTokenRef = useRef<number>(0);
  const ruleVersionRef = useRef<number>(0);

  // Sync selected table ref on every render
  activeTableRef.current = selectedTableParam;

  // Rules state
  const [rules, setRules] = useState<string[]>([]);
  const [savedRules, setSavedRules] = useState<string[] | null>(null);
  const [savedRuleRevision, setSavedRuleRevision] = useState<string | null>(null);
  const [loadingRules, setLoadingRules] = useState<boolean>(false);
  const [savingRules, setSavingRules] = useState<boolean>(false);
  const [rulesDirty, setRulesDirty] = useState<boolean>(false);
  const [rulesError, setRulesError] = useState<string | null>(null);

  const runIdParam = searchParams.get('runId') ?? undefined;

  // Generation & Review state
  const [generating, setGenerating] = useState<boolean>(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generatorUnavailable, setGeneratorUnavailable] = useState<boolean>(false);
  const [runId, setRunId] = useState<string | null>(null);

  const [loadingReview, setLoadingReview] = useState<boolean>(false);
  const [reviewData, setReviewData] = useState<TransformReviewResponse | null>(null);
  const [reviewedRuleRevision, setReviewedRuleRevision] = useState<string | null>(null);

  // Execution state
  const [executing, setExecuting] = useState<boolean>(false);
  const [executeResult, setExecuteResult] = useState<TransformExecuteResponse | null>(null);
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [silverPreview, setSilverPreview] = useState<LiveTablePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  function resetRunState() {
    setRunId(null);
    setReviewData(null);
    setExecuteResult(null);
    setExecuteError(null);
    setGenerateError(null);
    setGeneratorUnavailable(false);
    setReviewedRuleRevision(null);
    setSilverPreview(null);
    setPreviewError(null);
  }

  function validateRulesInput(inputRules: string[]): string[] | null {
    setRulesError(null);

    if (inputRules.length === 0) {
      setRulesError('At least one transformation rule must be specified.');
      return null;
    }

    const trimmed: string[] = [];
    const seen = new Set<string>();

    for (let i = 0; i < inputRules.length; i++) {
      const raw = inputRules[i];
      const norm = raw.trim();

      if (!norm) {
        setRulesError(`Rule #${i + 1} cannot be empty. Please enter rule text or remove it.`);
        return null;
      }

      const lower = norm.toLowerCase();
      if (seen.has(lower)) {
        setRulesError(`Duplicate rule detected at #${i + 1}: "${norm}". Each rule must be unique.`);
        return null;
      }

      seen.add(lower);
      trimmed.push(norm);
    }

    return trimmed;
  }

  useEffect(() => {
    mountedRef.current = true;
    activeTableRef.current = selectedTableParam;

    const loadToken = ++loadTokenRef.current;
    saveTokenRef.current += 1;
    generateTokenRef.current += 1;
    executeTokenRef.current += 1;

    setLoadingRules(false);
    setSavingRules(false);
    setGenerating(false);
    setLoadingReview(false);
    setExecuting(false);

    const reqTable = selectedTableParam;

    async function loadRules() {
      if (!reqTable) return;
      setLoadingRules(true);
      setRulesError(null);
      setSavedRules(null);
      setSavedRuleRevision(null);
      resetRunState();

      try {
        const res = await transformGetRules(reqTable);
        if (!mountedRef.current || activeTableRef.current !== reqTable || loadTokenRef.current !== loadToken) return;
        const fetched = (res.rules || []).map(formatSilverRule);
        setRules(fetched);
        setSavedRules(fetched);
        setSavedRuleRevision(res.rule_revision ?? null);
        setRulesDirty(false);
      } catch (err: any) {
        if (!mountedRef.current || activeTableRef.current !== reqTable || loadTokenRef.current !== loadToken) return;
        setRulesError(calmApiMessage(err, 'Failed to load saved transformation rules for this table.'));
        setRules([]);
        setSavedRules(null);
        setSavedRuleRevision(null);
      } finally {
        if (mountedRef.current && activeTableRef.current === reqTable && loadTokenRef.current === loadToken) {
          setLoadingRules(false);
        }
      }
    }

    void loadRules();
    return () => {
      mountedRef.current = false;
    };
  }, [selectedTableParam]);

  function markRulesChanged() {
    ruleVersionRef.current += 1;
    setRulesDirty(true);
    resetRunState();
  }

  function handleAddRule() {
    setRules((prev) => [...prev, '']);
    markRulesChanged();
  }

  function handleUpdateRule(index: number, val: string) {
    setRules((prev) => {
      const next = [...prev];
      next[index] = val;
      return next;
    });
    markRulesChanged();
  }

  function handleDeleteRule(index: number) {
    setRules((prev) => prev.filter((_, i) => i !== index));
    markRulesChanged();
  }

  function handleMoveRule(index: number, direction: 'up' | 'down') {
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= rules.length) return;
    setRules((prev) => {
      const next = [...prev];
      const temp = next[index];
      next[index] = next[targetIndex];
      next[targetIndex] = temp;
      return next;
    });
    markRulesChanged();
  }

  async function handleManualReload() {
    if (!selectedTableParam || isBusy) return;
    const loadToken = ++loadTokenRef.current;
    const reqTable = selectedTableParam;

    setLoadingRules(true);
    setRulesError(null);
    resetRunState();

    try {
      const res = await transformGetRules(selectedTableParam);
      if (!mountedRef.current || activeTableRef.current !== reqTable || loadTokenRef.current !== loadToken) return;
      const fetched = (res.rules || []).map(formatSilverRule);
      setRules(fetched);
      setSavedRules(fetched);
      setSavedRuleRevision(res.rule_revision ?? null);
      setRulesDirty(false);
    } catch (err: any) {
      if (!mountedRef.current || activeTableRef.current !== reqTable || loadTokenRef.current !== loadToken) return;
      setRulesError(calmApiMessage(err, 'Failed to reload saved rules.'));
    } finally {
      if (mountedRef.current && activeTableRef.current === reqTable && loadTokenRef.current === loadToken) {
        setLoadingRules(false);
      }
    }
  }

  interface SaveRulesResult {
    saved: boolean;
    ruleRevision?: string | null;
    table?: string;
    submittedRuleVersion?: number;
  }

  async function handleSaveRules(): Promise<SaveRulesResult> {
    if (!selectedTableParam || savingRules) return { saved: false };

    const validated = validateRulesInput(rules);
    if (!validated) return { saved: false };

    const saveToken = ++saveTokenRef.current;
    const reqTable = selectedTableParam;
    const reqVersion = ruleVersionRef.current;

    setSavingRules(true);
    setRulesError(null);

    try {
      const formattedRules = validated.map(parseSilverRuleInput);
      const saveRes = await transformSaveRules(selectedTableParam, formattedRules);
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        saveTokenRef.current !== saveToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return { saved: false };
      }
      setRules(validated);
      setSavedRules(validated);
      const newRev = saveRes.rule_revision ?? null;
      setSavedRuleRevision(newRev);
      setRulesDirty(false);
      resetRunState();
      return {
        saved: true,
        ruleRevision: newRev,
        table: reqTable,
        submittedRuleVersion: reqVersion,
      };
    } catch (err: any) {
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        saveTokenRef.current !== saveToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return { saved: false };
      }
      setRulesError(calmApiMessage(err, 'Failed to save rules to backend.'));
      return { saved: false };
    } finally {
      if (
        mountedRef.current &&
        activeTableRef.current === reqTable &&
        saveTokenRef.current === saveToken
      ) {
        setSavingRules(false);
      }
    }
  }

  async function handleGenerate() {
    if (!selectedTableParam || generating || executing) return;
    if (connectorContextIncomplete) {
      setGenerateError('Connector context is incomplete. Return to Bronze and verify the selected source relation again.');
      return;
    }

    const validated = validateRulesInput(rules);
    if (!validated) return;

    const reqTable = selectedTableParam;
    const reqVersion = ruleVersionRef.current;

    if (rulesDirty) {
      const saveRes = await handleSaveRules();
      if (
        !saveRes.saved ||
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }
    }

    if (
      !mountedRef.current ||
      activeTableRef.current !== reqTable ||
      ruleVersionRef.current !== reqVersion
    ) {
      return;
    }

    const genToken = ++generateTokenRef.current;

    setGenerating(true);
    setGenerateError(null);
    setGeneratorUnavailable(false);
    resetRunState();

    try {
      const genRes = await transformGenerate(reqTable, connectorContext);
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        generateTokenRef.current !== genToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }

      const newRunId = genRes.run_id;
      setRunId(newRunId);

      setLoadingReview(true);
      const revRes = await transformReview(newRunId);
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        generateTokenRef.current !== genToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }

      setReviewData(revRes);
      setReviewedRuleRevision(revRes.rule_revision ?? null);
    } catch (err: any) {
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        generateTokenRef.current !== genToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }

      if (
        err?.httpStatus === 503 ||
        err?.errorCode === 'GENERATOR_UNAVAILABLE' ||
        err?.userMessage?.includes('generator')
      ) {
        setGeneratorUnavailable(true);
        setGenerateError('SQL Generator Unavailable — Automated transformation SQL generation will be available when generic LLM integration is complete.');
      } else {
        setGenerateError(calmApiMessage(err, 'Failed to generate transformation SQL.'));
      }
    } finally {
      if (
        mountedRef.current &&
        activeTableRef.current === reqTable &&
        generateTokenRef.current === genToken
      ) {
        setGenerating(false);
        setLoadingReview(false);
      }
    }
  }

  async function handleExecute() {
    if (!runId || !reviewData || executing || executeResult) return;
    if (
      reviewData.table_name !== selectedTableParam ||
      reviewData.run_id !== runId ||
      rulesDirty ||
      reviewData.executed ||
      !reviewData.executable ||
      reviewedRuleRevision === null ||
      reviewedRuleRevision !== savedRuleRevision
    ) {
      return;
    }

    const execToken = ++executeTokenRef.current;
    const reqTable = selectedTableParam;
    const reqVersion = ruleVersionRef.current;

    setExecuting(true);
    setExecuteError(null);

    try {
      const execRes = await transformExecute(runId);
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        executeTokenRef.current !== execToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }
      setExecuteResult(execRes);
      setPreviewError(null);

      try {
        const preview = await getLiveTablePreview(
          reqTable,
          execRes.target.schema,
        );
        setSilverPreview(preview);
      } catch (err: unknown) {
        setPreviewError(
          calmApiMessage(
            err,
            'Silver promotion succeeded, but the live preview could not be loaded.',
          ),
        );
      }
    } catch (err: any) {
      if (
        !mountedRef.current ||
        activeTableRef.current !== reqTable ||
        executeTokenRef.current !== execToken ||
        ruleVersionRef.current !== reqVersion
      ) {
        return;
      }
      setExecuteError(calmApiMessage(err, 'Transformation execution or promotion failed.'));
    } finally {
      if (
        mountedRef.current &&
        activeTableRef.current === reqTable &&
        executeTokenRef.current === execToken
      ) {
        setExecuting(false);
      }
    }
  }

  const isBusy = loadingRules || savingRules || generating || loadingReview || executing;

  const silverComplete = Boolean(
    !executing &&
    !executeError &&
    executeResult?.status === 'success'
  );

  const canExecute = Boolean(
    selectedTableParam &&
    runId &&
    reviewData &&
    reviewData.run_id === runId &&
    reviewData.table_name === selectedTableParam &&
    reviewData.status === 'PENDING' &&
    reviewData.executable === true &&
    !reviewData.executed &&
    !rulesDirty &&
    reviewedRuleRevision !== null &&
    reviewedRuleRevision === savedRuleRevision &&
    !executing &&
    !executeResult &&
    !isBusy
  );

  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav />
      <PageAssistant page="silver" layer="silver" runId={runId || runIdParam} selectedTable={selectedTableParam || sourceTable || undefined} />

      {/* Header */}
      <div className="px-6 py-6 border-b border-[#252637]">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-[#f1f5f9]">Silver Layer</h2>
          {silverComplete ? (
            <DataSourceBadge mode="live" />
          ) : (
            <Badge variant="secondary">Ready</Badge>
          )}
          {executeResult ? (
            <Badge variant="pass">Promoted to Silver</Badge>
          ) : reviewData && reviewData.executable ? (
            <Badge variant="warning">Review Pending Approval</Badge>
          ) : reviewData ? (
            <Badge variant="secondary">Untrusted Review</Badge>
          ) : savedRules && savedRules.length > 0 ? (
            <Badge variant="secondary">{savedRules.length} Rules Saved</Badge>
          ) : (
            <Badge variant="secondary">Rule Configuration</Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[#6b7280]">
          Clean and transform Bronze table data using user-defined ordered rules.
        </p>
      </div>

      {/* Content Body */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#090a10] scrollbar-thin">
        {!selectedTableParam ? (
          /* Honest Empty State when ?table= query parameter is missing */
          <div className="max-w-xl mx-auto my-12 rounded-xl border border-[#f59e0b]/30 bg-[#451a03]/30 p-6 space-y-4 text-center">
            <AlertCircle size={28} className="mx-auto text-[#f59e0b]" />
            <h3 className="text-base font-semibold text-[#fef3c7]">No Bronze Table Selected</h3>
            <p className="text-xs text-[#fcd34d] leading-relaxed">
              Please return to the Bronze layer, discover source tables, ingest, and verify a table before configuring Silver cleaning rules.
            </p>
            <div className="pt-2">
              <Button
                variant="primary"
                onClick={() => navigate(`/projects/${encodeURIComponent(id || '')}/bronze`)}
              >
                Return to Bronze Layer
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column: Table Context, Rule Editor, & Action Bar */}
            <div className="lg:col-span-2 space-y-5">
              {/* Selected Bronze Table Banner */}
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14]">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-widest text-[#6b7280]">
                      Selected Bronze Table
                    </h3>
                    <div className="mt-1 text-base font-bold font-mono text-[#f1f5f9]">
                      {selectedTableParam}
                    </div>
                  </div>
                  <Badge variant="secondary">Source Context</Badge>
                </div>
              </div>

              {/* Rule Editor Panel */}
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Layers size={17} className="text-[#6366f1]" />
                    <h3 className="text-sm font-semibold text-[#f1f5f9]">Transformation Rules (Ordered)</h3>
                  </div>
                  <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleAddRule}
                    disabled={isBusy}
                    className="flex items-center gap-1 text-xs text-[#6366f1] hover:text-[#818cf8] font-medium transition-colors disabled:opacity-40"
                  >
                    <Plus size={14} /> Add Rule
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleManualReload()}
                    disabled={isBusy}
                    className="p-1 text-[#6b7280] hover:text-[#f1f5f9] transition-colors disabled:opacity-40"
                    title="Reload saved rules"
                  >
                    <RefreshCw size={14} className={loadingRules ? 'animate-spin' : ''} />
                  </button>
                </div>
              </div>

                {loadingRules ? (
                  <LoadingSkeleton count={3} className="h-14" />
                ) : rulesError ? (
                  <div className="rounded-lg border border-[#ef4444]/30 bg-[#450a0a]/30 p-4 text-xs text-[#fca5a5] space-y-2">
                    <div className="flex items-center gap-2 font-semibold text-[#ef4444]">
                      <AlertCircle size={16} />
                      Rules Validation Error
                    </div>
                    <p>{rulesError}</p>
                  </div>
                ) : rules.length === 0 ? (
                  <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#94a3b8] space-y-2">
                    <p>No transformation rules defined yet for <span className="font-mono text-[#f1f5f9]">{selectedTableParam}</span>.</p>
                    <p className="text-[#6b7280]">Click &quot;Add Rule&quot; above to specify cleanings such as removing nulls or filtering rows.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {rules.map((ruleText, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-3 p-3 rounded-lg border border-[#252637] bg-[#13141e] group"
                      >
                        <span className="text-xs font-bold text-[#6366f1] w-6 shrink-0">
                          #{idx + 1}
                        </span>
                        <input
                          type="text"
                          value={formatSilverRule(ruleText)}
                          placeholder="Enter cleaning rule (e.g. record_id is not null)"
                          disabled={isBusy}
                          onChange={(e) => handleUpdateRule(idx, e.target.value)}
                          className="flex-1 bg-transparent text-xs text-[#f1f5f9] focus:outline-none focus:border-b border-[#6366f1] py-1 disabled:opacity-50"
                        />
                        <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                          <button
                            type="button"
                            onClick={() => handleMoveRule(idx, 'up')}
                            disabled={idx === 0 || isBusy}
                            className="p-1 text-[#6b7280] hover:text-[#f1f5f9] disabled:opacity-30"
                            title="Move up"
                          >
                            <ArrowUp size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleMoveRule(idx, 'down')}
                            disabled={idx === rules.length - 1 || isBusy}
                            className="p-1 text-[#6b7280] hover:text-[#f1f5f9] disabled:opacity-30"
                            title="Move down"
                          >
                            <ArrowDown size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteRule(idx)}
                            disabled={isBusy}
                            className="p-1 text-[#6b7280] hover:text-[#ef4444] disabled:opacity-30"
                            title="Delete rule"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Rules Action Bar */}
                <div className="flex items-center justify-between pt-3 border-t border-[#252637]">
                  <div className="text-xs text-[#94a3b8]">
                    {rulesDirty ? (
                      <span className="text-[#f59e0b]">Unsaved rule edits</span>
                    ) : savedRules && savedRules.length > 0 ? (
                      <span className="text-[#22c55e]">Rules saved to backend</span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-3">
                    {rulesDirty && (
                      <Button
                        variant="secondary"
                        size="sm"
                        isLoading={savingRules}
                        disabled={isBusy || rules.length === 0}
                        onClick={() => void handleSaveRules()}
                      >
                        Save Rules
                      </Button>
                    )}
                    <Button
                      variant="primary"
                      size="sm"
                      isLoading={generating || loadingReview}
                      disabled={rules.length === 0 || isBusy}
                      onClick={() => void handleGenerate()}
                    >
                      {generating ? 'Generating SQL…' : loadingReview ? 'Loading Review…' : 'Generate Transformation SQL'}
                    </Button>
                  </div>
                </div>
              </div>

              {/* Generation / Validation Errors / Generator Unavailable State */}
              {generateError && (
                <div className={`rounded-xl border p-4 text-xs space-y-2 ${generatorUnavailable ? 'border-[#3b82f6]/30 bg-[#1e3a8a]/20 text-[#93c5fd]' : 'border-[#ef4444]/30 bg-[#450a0a]/30 text-[#fca5a5]'}`}>
                  <div className={`flex items-center gap-2 font-semibold ${generatorUnavailable ? 'text-[#60a5fa]' : 'text-[#ef4444]'}`}>
                    <AlertCircle size={16} />
                    {generatorUnavailable ? 'SQL Generator Status' : 'SQL Generation Failed'}
                  </div>
                  <p>{generateError}</p>
                </div>
              )}

              {/* Review Panel: Generated Transformation SQL & Planned Steps */}
              {reviewData && (
                <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4 animate-slide-up">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Code size={17} className="text-[#6366f1]" />
                      <h3 className="text-sm font-semibold text-[#f1f5f9]">Generated Transformation SQL</h3>
                    </div>
                    {executeResult || reviewData.executed ? (
                      <Badge variant="pass">Executed</Badge>
                    ) : reviewData.executable ? (
                      <Badge variant="warning">Review Pending</Badge>
                    ) : (
                      <Badge variant="secondary">Untrusted / Legacy Run</Badge>
                    )}
                  </div>

                  <p className="text-xs text-[#94a3b8] leading-relaxed">
                    {reviewData.planned_changes.summary ??
                      'Deterministic Silver transformation proposal.'}
                  </p>

                  <div className="rounded-lg border border-[#252637] bg-[#090a10] p-4 overflow-x-auto font-mono text-xs text-[#a5b4fc] scrollbar-thin">
                    <pre className="whitespace-pre">{reviewData.sql_text}</pre>
                  </div>

                  {/* Planned Steps List */}
                  {reviewData.planned_changes.rules && reviewData.planned_changes.rules.length > 0 && (
                    <div className="space-y-2 pt-2 border-t border-[#252637]">
                      <h4 className="text-xs font-semibold text-[#f1f5f9]">Planned Sequential Steps</h4>
                      <ul className="space-y-1.5 text-xs text-[#94a3b8]">
                        {reviewData.planned_changes.rules.map((step, idx) => (
                          <li key={idx} className="flex items-center gap-2">
                            <span className="h-1.5 w-1.5 rounded-full bg-[#6366f1]" />
                            <span>{formatSilverRule(step)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Human Approval Gate Action Bar */}
                  <div className="pt-4 border-t border-[#252637] flex items-center justify-between">
                    <span className="text-xs text-[#cbd5e1]">
                      {rulesDirty
                        ? 'Rule edits pending — re-generate SQL before approval.'
                        : executeResult || reviewData.executed
                          ? 'Transformation has already been executed and promoted.'
                          : !reviewData.executable
                            ? 'Run is non-executable (untrusted provenance or generator unavailable).'
                            : 'Review the generated CTE SQL above before executing promotion.'}
                    </span>
                    <Button
                      variant="primary"
                      isLoading={executing}
                      disabled={!canExecute}
                      rightIcon={<ArrowRight size={16} />}
                      onClick={handleExecute}
                    >
                      {executing
                        ? 'Executing & Promoting…'
                        : executeResult
                          ? 'Executed & Promoted'
                          : 'Approve & Execute (Silver Promotion)'}
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Execution Attribution & Silver Data Status */}
            <div className="space-y-5">
              {/* Execution Attribution Results */}
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-4">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={17} className="text-[#22c55e]" />
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">Execution Attribution Log</h3>
                </div>

                {executeError && (
                  <div className="rounded-lg border border-[#ef4444]/30 bg-[#450a0a]/30 p-3 text-xs text-[#fca5a5] space-y-1">
                    <p className="font-semibold text-[#ef4444]">Execution Error</p>
                    <p>{executeError}</p>
                  </div>
                )}

                {executeResult ? (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-[#22c55e]/30 bg-[#22c55e]/10 p-3 text-xs text-[#4ade80] space-y-1">
                      <div className="font-semibold flex items-center gap-1.5">
                        <CheckCircle2 size={15} />
                        Execution Successful
                      </div>
                      <p className="text-[#cbd5e1]">{executeResult.message}</p>
                    </div>

                    <div className="space-y-2 pt-2 border-t border-[#252637]">
                      <h4 className="text-xs font-semibold text-[#6b7280] uppercase tracking-wider">
                        Attribution Breakdown
                      </h4>
                      {executeResult.attribution_available && executeResult.attribution_log ? (
                        executeResult.attribution_log.map((logLine, idx) => (
                          <div
                            key={idx}
                            className="p-2.5 rounded border border-[#252637] bg-[#13141e] text-xs font-mono text-[#cbd5e1]"
                          >
                            {logLine}
                          </div>
                        ))
                      ) : (
                        <div className="p-2.5 rounded border border-[#252637] bg-[#13141e] text-xs font-mono text-[#94a3b8]">
                          Historical execution attribution is unavailable for this run.
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#6b7280]">
                    {executing
                      ? 'Executing candidate SQL and computing attribution…'
                      : reviewData
                        ? 'Click "Approve & Execute" to run transformation and compute attribution.'
                        : 'Define rules and generate SQL to view execution attribution.'}
                  </div>
                )}
              </div>

              {/* Silver Row Preview — Live State */}
              <div className="rounded-xl border border-[#252637] p-5 bg-[#0d0e14] space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[#f1f5f9]">Silver Data Preview</h3>
                  {silverPreview && (
                    <Badge variant="pass">{silverPreview.row_count} Rows Promoted to Silver</Badge>
                  )}
                </div>
                {silverPreview ? (
                  <div className="space-y-3">
                    <div className="text-xs text-[#94a3b8] flex gap-4">
                      <span>Columns: {silverPreview.column_count}</span>
                      <span>Table: {silverPreview.schema}.{selectedTableParam}</span>
                    </div>
                    <div className="overflow-x-auto rounded border border-[#252637] bg-[#0b0c12]">
                      <table className="w-full text-left text-xs text-[#e5e7eb]">
                        <thead className="bg-[#13141e] text-[#94a3b8] border-b border-[#252637]">
                          <tr>
                            {silverPreview.columns.map((col) => (
                              <th key={col.name} className="px-3 py-2 font-semibold font-mono">{col.name}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#252637]">
                          {silverPreview.rows.map((row, rowIndex) => (
                            <tr key={rowIndex}>
                              {silverPreview.columns.map((col) => (
                                <td key={col.name} className="px-3 py-2 font-mono text-[#cbd5e1]">
                                  {row[col.name] === null || row[col.name] === undefined
                                    ? '—'
                                    : String(row[col.name])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {silverPreview.rows.length === 0 && (
                      <p className="text-xs text-[#6b7280]">The promoted relation contains no rows.</p>
                    )}
                  </div>
                ) : previewError ? (
                  <div className="rounded-lg border border-[#ef4444]/30 bg-[#450a0a]/30 p-4 text-xs text-[#fca5a5]">
                    {previewError}
                  </div>
                ) : (
                  <div className="rounded-lg border border-[#252637] bg-[#13141e] p-6 text-center text-xs text-[#6b7280] leading-relaxed">
                    {executeResult
                      ? `Silver transformation completed for ${executeResult.target.schema}.${selectedTableParam}; loading live preview.`
                      : 'Execute transformation to promote table to Silver.'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer Navigation Bar */}
      <div className="border-t border-[#252637] bg-[#0d0e14] px-6 py-4 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => navigate(`/projects/${encodeURIComponent(id || '')}/bronze`)}
        >
          Back to Bronze
        </Button>
        <Button
          variant="primary"
          rightIcon={<ArrowRight size={16} />}
          disabled={!silverComplete}
          title={silverComplete ? undefined : 'Complete Silver promotion before continuing.'}
          onClick={() => navigate(`/projects/${encodeURIComponent(id || '')}/gold?table=${encodeURIComponent(selectedTableParam || '')}`)}
        >
          Continue to Gold
        </Button>
      </div>
    </div>
  );
}
