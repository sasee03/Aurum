import { useCallback, useState } from "react";
import type { AssistantLayer, AssistantPage, AssistantResponse } from "../../lib/aurumAssistantApi";
import { postAssistantChat } from "../../lib/aurumAssistantApi";
import { AurumAssistantMessage } from "./AurumAssistantMessage";
import { SuggestedPrompts } from "./SuggestedPrompts";
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
  const pageLabel = page.replace("_", " ");
  const layerLabel = layer ? ` / ${layer.charAt(0).toUpperCase()}${layer.slice(1)}` : "";
  const runLabel = runId ? ` / ${runId}` : " / Latest Run";
  return `Context: ${pageLabel}${layerLabel}${runLabel}`;
}

export function AurumAssistantDrawer({
  open,
  onClose,
  page,
  runId,
  layer,
  selectedCheckId,
  selectedTable,
}: AurumAssistantButtonProps & { open: boolean; onClose: () => void }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!question.trim() || loading) return;
      const userEntry: ChatEntry = { id: `${Date.now()}-u`, role: "user", text: question };
      setMessages((prev) => [...prev, userEntry]);
      setInput("");
      setLoading(true);
      try {
        const response = await postAssistantChat({
          page,
          run_id: runId || "latest",
          layer: layer ?? null,
          question,
          context: {
            selected_check_id: selectedCheckId,
            selected_table: selectedTable,
          },
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
              "Aurum Assistant is temporarily unavailable. Validation results in the report are unchanged.",
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [loading, page, runId, layer, selectedCheckId, selectedTable],
  );

  if (!open) return null;

  return (
    <div className="aa-drawer-backdrop" onClick={onClose}>
      <div className="aa-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="aa-drawer-header">
          <div>
            <h2>Aurum Assistant</h2>
            <p className="aa-subtitle">{contextLabel(page, layer, runId)}</p>
          </div>
          <button type="button" className="aa-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="aa-chat-area">
          {messages.length === 0 && (
            <p className="aa-empty">
              Ask about validation results, history, sample queries, or custom checks. Aurum Assistant
              explains — it does not decide the final trust verdict.
            </p>
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
          {loading && <p className="aa-loading">Thinking…</p>}
        </div>

        <SuggestedPrompts page={page} onSelect={sendQuestion} />

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
        Aurum Assistant
      </button>
      <AurumAssistantDrawer {...props} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
