import type { AssistantResponse } from "../../lib/aurumAssistantApi";
import { EmailDraftCard } from "./EmailDraftCard";
import { ResultTableCard } from "./ResultTableCard";
import { SqlCard } from "./SqlCard";
import "./aurum-assistant.css";

interface Props {
  response: AssistantResponse;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function factLabel(path: string): string {
  return path
    .split(".")
    .map((part) => part.replace(/_/g, " "))
    .join(" ");
}

export function AurumAssistantResponseRenderer({ response }: Props) {
  const { answer, status } = response;
  const data = response.data ?? {};
  const evidence = response.evidence ?? [];
  const isReadOnlyRefusal = status === "read_only_refusal";
  const isInsufficient = status === "insufficient_information";

  return (
    <div className="aa-response">

      {isReadOnlyRefusal && (
        <div className="aa-state-card aa-state-card--readonly">
          <strong>Aurum Assistant is currently read-only.</strong>
          <p>
            I can explain the pipeline and its results, but I can't approve, execute,
            promote, or modify pipeline state from chat.
          </p>
        </div>
      )}

      {isInsufficient && (
        <div className="aa-state-card">
          <strong>Insufficient information</strong>
          <p>The backend did not return enough grounded Aurum context for this answer.</p>
        </div>
      )}

      {!isReadOnlyRefusal && <p className="aa-answer">{answer}</p>}
      {evidence.length > 0 && (
        <details className="aa-evidence-card">
          <summary>Grounding</summary>
          <dl>
            {evidence.map((fact) => (
              <div key={fact.path}>
                <dt>{factLabel(fact.path)}</dt>
                <dd>{renderValue(fact.value)}</dd>
              </div>
            ))}
          </dl>
        </details>
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
