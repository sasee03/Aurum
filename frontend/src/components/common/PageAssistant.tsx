import { AurumAssistantButton } from '@/components/aurum-assistant/AurumAssistantButton';
import type { AssistantLayer, AssistantPage } from '@/lib/aurumApi';

interface Props {
  page: AssistantPage;
  layer?: AssistantLayer;
  runId?: string;
  selectedCheckId?: string;
}

/** Floating Aurum Assistant — mount on report-driven pages. */
export function PageAssistant({ page, layer, runId, selectedCheckId }: Props) {
  return (
    <AurumAssistantButton
      page={page}
      layer={layer}
      runId={runId}
      selectedCheckId={selectedCheckId}
    />
  );
}
