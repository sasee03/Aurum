import type { EmailDraft } from "../../lib/aurumAssistantApi";

interface Props {
  draft: EmailDraft;
}

export function EmailDraftCard({ draft }: Props) {
  const copy = async () => {
    await navigator.clipboard.writeText(draft.copy_text);
  };

  return (
    <div className="aa-card aa-email-card">
      <div className="aa-card-header">
        <span>Email draft</span>
        <button type="button" className="aa-btn aa-btn--small" onClick={copy}>
          Copy
        </button>
      </div>
      <p className="aa-email-subject">
        <strong>Subject:</strong> {draft.subject}
      </p>
      <pre className="aa-email-body">{draft.body}</pre>
      <p className="aa-email-note">Draft only — not sent.</p>
    </div>
  );
}
