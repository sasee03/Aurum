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
      {text && <p>{text}</p>}
      {error && <p className="aa-error">{error}</p>}
      {response && <AurumAssistantResponseRenderer response={response} />}
    </div>
  );
}
