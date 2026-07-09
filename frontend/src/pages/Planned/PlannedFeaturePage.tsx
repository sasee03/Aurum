import { PageAssistant } from '@/components/common/PageAssistant';
import { ProjectSubNav } from '@/components/layout/ProjectSubNav';

interface Props {
  title: string;
  detail: string;
  assistantPage?: 'validation' | 'history' | 'failure';
}

export function PlannedFeaturePage({
  title,
  detail,
  assistantPage = 'validation',
}: Props) {
  return (
    <div className="flex h-full flex-col overflow-hidden animate-fade-in relative">
      <ProjectSubNav />
      <PageAssistant page={assistantPage} />

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <h2 className="text-xl font-bold text-[#f1f5f9]">{title}</h2>
        <p className="text-sm text-[#6b7280]">{detail}</p>
      </div>
    </div>
  );
}
