import { useCallback, useState } from "react";
import { Loader2, LockKeyhole, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import type { AssistantLayer, AssistantPage, AssistantResponse } from "../../lib/aurumAssistantApi";
import { postAssistantChat } from "../../lib/aurumAssistantApi";
import { ApiError, API_UNAVAILABLE } from "../../utils/apiErrors";
import { AurumAssistantMessage } from "./AurumAssistantMessage";
import "./aurum-assistant.css";

export interface AurumAssistantButtonProps {
  page: AssistantPage;
  runId?: string;
  layer?: AssistantLayer;
  selectedCheckId?: string;
  selectedTable?: string;
}

interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  text?: string;
  response?: AssistantResponse;
  error?: string;
  canRetry?: boolean;
  retryQuestion?: string;
}

function formatLayerName(layer?: AssistantLayer): string {
  return layer ? layer.charAt(0).toUpperCase() + layer.slice(1) : "Aurum";
}

function formatPageName(page: AssistantPage): string {
  return page.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function ContextLabel({ page, layer, runId, selectedTable }: { page: AssistantPage; layer?: AssistantLayer; runId?: string; selectedTable?: string }) {
  if (runId) {
    const layerName = formatLayerName(layer);
    const displayName = selectedTable || `${formatPageName(page)} context`;
    return (
      <div className="flex flex-col gap-1 mt-1">
        <span className="font-semibold text-white">{layerName} run selected</span>
        <span className="text-[#06b6d4]">{displayName}</span>
        <span className="text-xs text-slate-400 font-mono">{runId}</span>
      </div>
    );
  }
  const layerName = formatLayerName(layer);
  return (
    <div className="aa-context-banner">
      <strong>No {layerName} run selected</strong>
      <span>{formatPageName(page)} needs an exact run before run-specific Assistant answers.</span>
    </div>
  );
}

function getSuggestedPrompts(layer?: AssistantLayer, page?: AssistantPage): string[] {
  if (layer === 'silver' || page === 'silver') {
    return [
      "What changed in this Silver run?",
      "What rules were applied?",
      "How many rows were retained?",
    ];
  }
  if (layer === 'gold' || page === 'gold') {
    return [
      "What KPI did Aurum create?",
      "How was this Gold result calculated?",
      "What does this Gold result show?",
    ];
  }
  if (layer === 'bronze' || page === 'bronze') {
    return [
      "What is the status of Bronze ingestion?",
      "What source relation was ingested?",
      "Are source rows matched 1-to-1?",
    ];
  }
  return [
    "What PostgreSQL tables were discovered?",
    "What is the status of this dataset pipeline?",
    "How does the Medallion transformation work?",
  ];
}

function noRunGuidance(layer?: AssistantLayer): string {
  const layerName = formatLayerName(layer);
  return `No ${layerName} run is selected yet. Complete ${layerName} ingestion or open an existing run to ask grounded questions.`;
}

function isServiceFailure(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.httpStatus === undefined || error.httpStatus >= 500;
  }
  return true;
}

function serviceFailureDetail(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.userMessage === API_UNAVAILABLE) {
      return "Backend unreachable. Check that the local Aurum API is running, then retry.";
    }
    if (error.userMessage === "ASSISTANT_GEMINI_UNAVAILABLE" || error.errorCode === "ASSISTANT_GEMINI_UNAVAILABLE") {
      return "Assistant provider unavailable or not configured.";
    }
    if (error.httpStatus) {
      return `Assistant service returned HTTP ${error.httpStatus}.`;
    }
  }
  return "The Assistant service could not complete this request.";
}

export function AurumAssistantDrawer({
  open,
  onClose,
  page,
  runId,
  layer,
  selectedTable,
}: AurumAssistantButtonProps & { open: boolean; onClose: () => void }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);

  const hasRunContext = Boolean(runId);
  const suggestedPrompts = getSuggestedPrompts(layer, page);

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!question.trim() || loading) return;
      if (!hasRunContext) return;
      const userEntry: ChatEntry = { id: `${Date.now()}-u`, role: "user", text: question };
      setMessages((prev) => [...prev, userEntry]);
      setInput("");
      setLoading(true);
      try {
        const response = await postAssistantChat({
          message: question,
          run_id: runId || undefined,
        });

        setMessages((prev) => [
          ...prev,
          { id: `${Date.now()}-a`, role: "assistant", response },
        ]);
      } catch (err: any) {
        const canRetry = isServiceFailure(err);
        const errorMsg = canRetry
          ? serviceFailureDetail(err)
          : err?.userMessage || err?.message || "Assistant could not answer with the current context.";
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-e`,
            role: "assistant",
            error: errorMsg,
            canRetry,
            retryQuestion: question,
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [hasRunContext, loading, runId],
  );

  if (!open) return null;

  return (
    <div className="aa-drawer-backdrop" onClick={onClose}>
      <div className="aa-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="aa-drawer-header">
          <div>
            <h2>Aurum Assistant</h2>
            <div className="aa-state-pills" aria-label="Assistant state">
              <span className="aa-state-pill">
                <LockKeyhole size={12} />
                Read-only
              </span>
            </div>
            <div className="aa-subtitle">
              <ContextLabel page={page} layer={layer} runId={runId} selectedTable={selectedTable} />
            </div>
            <p className="aa-helper">Ask about your current Aurum pipeline.</p>
          </div>
          <button type="button" className="aa-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="aa-chat-area">
          {messages.length === 0 && (
            <div>
              <div className="aa-empty">
                {hasRunContext ? (
                  <p>
                    Aurum Assistant explains current pipeline facts returned by the backend. It cannot approve,
                    execute, promote, or modify pipeline state from chat.
                  </p>
                ) : (
                  <div className="aa-state-card aa-state-card--context">
                    <strong>No {formatLayerName(layer)} run selected</strong>
                    <p>{noRunGuidance(layer)}</p>
                  </div>
                )}
              </div>
              {hasRunContext && (
                <div className="aa-suggested-prompts">
                  <span className="aa-suggested-title flex items-center gap-1.5">
                    <Sparkles size={12} className="text-[#06b6d4]" />
                    Suggested Questions
                  </span>
                  {suggestedPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="aa-suggested-chip"
                      onClick={() => sendQuestion(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((m) => (
            <AurumAssistantMessage
              key={m.id}
              role={m.role}
              text={m.text}
              response={m.response}
              error={m.error}
              canRetry={m.canRetry}
              onRetry={m.canRetry && m.retryQuestion ? () => sendQuestion(m.retryQuestion as string) : undefined}
            />
          ))}
          {loading && (
            <div className="aa-loading">
              <Loader2 size={14} />
              Aurum Assistant is thinking…
            </div>
          )}
        </div>

        <form
          className="aa-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            sendQuestion(input);
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={hasRunContext ? "Ask Aurum Assistant…" : "Select a run to ask grounded questions"}
            disabled={loading || !hasRunContext}
          />
          <button type="submit" className="aa-btn" disabled={loading || !hasRunContext || !input.trim()}>
            <Send size={14} />
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

export function AurumAssistantButton(props: AurumAssistantButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" className="aa-fab" onClick={() => setOpen(true)}>
        <ShieldCheck size={15} />
        Aurum Assistant
      </button>
      <AurumAssistantDrawer {...props} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
