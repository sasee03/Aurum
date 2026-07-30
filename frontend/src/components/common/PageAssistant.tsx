import { useEffect } from 'react';
import { AurumAssistantButton } from '@/components/aurum-assistant/AurumAssistantButton';
import type { AssistantLayer, AssistantPage } from '@/lib/aurumApi';

interface Props {
  page: AssistantPage;
  layer?: AssistantLayer;
  runId?: string;
  selectedCheckId?: string;
  selectedTable?: string;
}

const SAFE_ZONE_SELECTOR = '[data-assistant-safe-zone="bottom-action"]';

function updateAssistantSafeZone() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  let safeBottom = 0;
  document.querySelectorAll<HTMLElement>(SAFE_ZONE_SELECTOR).forEach((element) => {
    const style = window.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return;

    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || rect.bottom <= 0 || rect.top >= window.innerHeight) return;

    safeBottom = Math.max(safeBottom, window.innerHeight - rect.top + 16);
  });

  document.documentElement.style.setProperty('--aa-safe-bottom', `${Math.ceil(safeBottom)}px`);
}

/** Floating Aurum Assistant — mount on report-driven pages. */
export function PageAssistant({ page, layer, runId, selectedCheckId, selectedTable }: Props) {
  useEffect(() => {
    updateAssistantSafeZone();

    const observer = new ResizeObserver(updateAssistantSafeZone);
    document.querySelectorAll<HTMLElement>(SAFE_ZONE_SELECTOR).forEach((element) => {
      observer.observe(element);
    });

    window.addEventListener('resize', updateAssistantSafeZone);
    window.addEventListener('scroll', updateAssistantSafeZone, true);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateAssistantSafeZone);
      window.removeEventListener('scroll', updateAssistantSafeZone, true);
      document.documentElement.style.removeProperty('--aa-safe-bottom');
    };
  }, []);

  return (
    <AurumAssistantButton
      page={page}
      layer={layer}
      runId={runId}
      selectedCheckId={selectedCheckId}
      selectedTable={selectedTable}
    />
  );
}
