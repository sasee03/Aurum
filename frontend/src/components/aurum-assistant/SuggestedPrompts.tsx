import type { AssistantPage } from "../../lib/aurumAssistantApi";

const PROMPTS: Record<AssistantPage, string[]> = {
  dashboard: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  validation: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  bronze: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  silver: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  gold: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  history: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  custom_checks: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  failure: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
  query: [
    "What dataset am I working with?",
    "What happened in Silver?",
    "What did Gold calculate?",
    "What is the current Gold status?",
    "Why should I trust this result?",
  ],
};

interface Props {
  page: AssistantPage;
  onSelect: (prompt: string) => void;
}

export function SuggestedPrompts({ page, onSelect }: Props) {
  const prompts = PROMPTS[page] ?? PROMPTS.validation;

  return (
    <div className="aa-prompts">
      <span className="aa-prompts-label">Suggested prompts</span>
      <div className="aa-prompts-list">
        {prompts.map((prompt) => (
          <button key={prompt} type="button" className="aa-prompt-chip" onClick={() => onSelect(prompt)}>
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
