import type { AssistantResponse } from "../../lib/aurumAssistantApi";
import { AurumAssistantResponseRenderer } from "./AurumAssistantResponseRenderer";

interface Props {
  role: "user" | "assistant";
  text?: string;
  response?: AssistantResponse;
  error?: string;
  canRetry?: boolean;
  onRetry?: () => void;
}

export function AurumAssistantMessage({ role, text, response, error, canRetry, onRetry }: Props) {
  return (
    <div className={`aa-message aa-message--${role}`}>
      <div className="aa-message-label">{role === "user" ? "You" : "Aurum Assistant"}</div>
      {text && <p className="aa-message-text">{text}</p>}
      {error && (
        <div className="aa-state-card aa-state-card--error">
          <strong>{canRetry ? "Assistant temporarily unavailable" : "Assistant could not answer"}</strong>
          <p>{error}</p>
          {canRetry && onRetry && (
            <button type="button" className="aa-btn aa-btn--small" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
      {response && <AurumAssistantResponseRenderer response={response} />}
    </div>
  );
}
