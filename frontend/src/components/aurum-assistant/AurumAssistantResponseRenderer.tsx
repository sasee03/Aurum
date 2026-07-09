import type { AssistantResponse } from "../../lib/aurumAssistantApi";
import { EmailDraftCard } from "./EmailDraftCard";
import { ResultTableCard } from "./ResultTableCard";
import { SqlCard } from "./SqlCard";
import "./aurum-assistant.css";

interface Props {
  response: AssistantResponse;
}

export function AurumAssistantResponseRenderer({ response }: Props) {
  const { answer, data, confidence } = response;

  return (
    <div className="aa-response">
      <p className="aa-answer">{answer}</p>
      {confidence === "low" && (
        <p className="aa-confidence-warn">Low confidence — verify against the latest validation report.</p>
      )}
      {data.sql && <SqlCard sql={data.sql} />}
      {data.table && data.table.length > 0 && <ResultTableCard rows={data.table} />}
      {data.email_draft && <EmailDraftCard draft={data.email_draft} />}
      {data.suggested_actions && data.suggested_actions.length > 0 && (
        <div className="aa-suggested-actions">
          <strong>Suggested actions</strong>
          <ul>
            {data.suggested_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      )}
      {data.custom_check && (
        <div className="aa-custom-check-preview">
          <strong>Custom check template</strong>
          <pre>{JSON.stringify(data.custom_check, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
