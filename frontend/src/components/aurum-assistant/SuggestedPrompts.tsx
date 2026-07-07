import type { AssistantPage } from "../../lib/aurumAssistantApi";

const PROMPTS: Record<AssistantPage, string[]> = {
  dashboard: [
    "Summarize this failure.",
    "What is the business impact?",
    "Compare this run with history.",
    "Draft stakeholder mail.",
  ],
  validation: [
    "Why did this layer fail?",
    "Explain the business impact.",
    "What should I fix first?",
    "Draft stakeholder mail.",
  ],
  bronze: [
    "Explain Bronze validation status.",
    "Are there schema issues?",
    "Explain primary key issues.",
    "Explain freshness issues.",
  ],
  silver: [
    "Why did Silver fail?",
    "What changed from Bronze to Silver?",
    "Did transformation remove records?",
    "Add a custom Silver check.",
  ],
  gold: [
    "Why is Gold impacted?",
    "Explain revenue impact.",
    "Is the Gold output trusted?",
    "Show top 5 states by revenue.",
  ],
  history: [
    "Compare this run with history.",
    "What changed from previous run?",
    "Is this drop normal?",
    "What was expected in this run?",
  ],
  custom_checks: [
    "Help me create a Silver check.",
    "Suggest checks for this table.",
    "Explain this custom rule.",
    "Run this custom check.",
  ],
  failure: [
    "Summarize this failure.",
    "Draft stakeholder email.",
    "What is the next action?",
    "Who should fix this?",
  ],
  query: [
    "Show top 5 states by revenue.",
    "Compare this run with history.",
    "Explain the business impact.",
    "Draft stakeholder mail.",
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
