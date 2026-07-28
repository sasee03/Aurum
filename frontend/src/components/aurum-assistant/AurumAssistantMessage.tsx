import type { AssistantResponse } from "../../lib/aurumAssistantApi";
import { AurumAssistantResponseRenderer } from "./AurumAssistantResponseRenderer";

interface Props {
  role: "user" | "assistant";
  text?: string;
  response?: AssistantResponse;
  error?: string;
}

export function AurumAssistantMessage({ role, text, response, error }: Props) {
  return (
    <div className={`aa-message aa-message--${role}`}>
      <div className="aa-message-label">{role === "user" ? "You" : "Aurum Assistant"}</div>
      {text && <p className="aa-message-text">{text}</p>}
      {error && (
        <div className="aa-state-card aa-state-card--error">
          <strong>Aurum Assistant is unavailable.</strong>
          <p>{error}</p>
        </div>
      )}
      {response && <AurumAssistantResponseRenderer response={response} />}
    </div>
  );
}
