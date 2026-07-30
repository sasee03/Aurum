import { useCallback, useState } from "react";
import { Loader2, LockKeyhole, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import type { AssistantLayer, AssistantPage, AssistantResponse } from "../../lib/aurumAssistantApi";
import { postAssistantChat } from "../../lib/aurumAssistantApi";
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
}

function contextLabel(page: AssistantPage, layer?: AssistantLayer, runId?: string) {
  const pageLabel = page.replace(/_/g, " ");
  const layerLabel = layer ? ` / ${layer.charAt(0).toUpperCase()}${layer.slice(1)}` : "";
  const runLabel = runId ? ` / Run: ${runId}` : " / No Run Context";
  return `Context: ${pageLabel}${layerLabel}${runLabel}`;
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

export function AurumAssistantDrawer({
  open,
  onClose,
  page,
  runId,
  layer,
}: AurumAssistantButtonProps & { open: boolean; onClose: () => void }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);

  const suggestedPrompts = getSuggestedPrompts(layer, page);

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!question.trim() || loading) return;
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
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-e`,
            role: "assistant",
            error:
              "Aurum Assistant is temporarily unavailable. Please try again.",
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [loading, runId],
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
            <p className="aa-subtitle">{contextLabel(page, layer, runId)}</p>
            <p className="aa-helper">Ask about your current Aurum pipeline.</p>
          </div>
          <button type="button" className="aa-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="aa-chat-area">
          {messages.length === 0 && (
            <div>
              <p className="aa-empty">
                Aurum Assistant explains current pipeline facts returned by the backend. It cannot approve,
                execute, promote, or modify pipeline state from chat.
              </p>
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
            </div>
          )}
          {messages.map((m) => (
            <AurumAssistantMessage
              key={m.id}
              role={m.role}
              text={m.text}
              response={m.response}
              error={m.error}
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
            placeholder="Ask Aurum Assistant…"
            disabled={loading}
          />
          <button type="submit" className="aa-btn" disabled={loading || !input.trim()}>
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
