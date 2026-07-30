import type { ReactNode } from 'react';
import { BookOpen, FileText, ShieldCheck, Activity, ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';

interface DocLink {
  title: string;
  detail: string;
  href: string;
  icon: ReactNode;
}

const GITHUB_DOC_BASE =
  'https://github.com/sasee03/Aurum/blob/feature/react-config-integration';

const docs: DocLink[] = [
  {
    title: 'API Contract',
    detail: 'Backend endpoint shapes, request payloads, and response expectations.',
    href: `${GITHUB_DOC_BASE}/docs/API_CONTRACT.md`,
    icon: <BookOpen size={18} />,
  },
  {
    title: 'Output Contract',
    detail: 'Validation report structure, verdict fields, trust score, and business impact output.',
    href: `${GITHUB_DOC_BASE}/docs/output_contract.md`,
    icon: <FileText size={18} />,
  },
  {
    title: 'Check Catalogue',
    detail: 'Bronze, Silver, Gold, and cross-layer checks used by the validation engine.',
    href: `${GITHUB_DOC_BASE}/docs/check_catalogue.md`,
    icon: <ShieldCheck size={18} />,
  },
  {
    title: 'Integration Reliability',
    detail: 'Reliability expectations for health checks, app-state reads, and API-backed surfaces.',
    href: `${GITHUB_DOC_BASE}/docs/integration_reliability.md`,
    icon: <Activity size={18} />,
  },
];

export function DocumentationPage() {
  return (
    <div className="min-h-full p-6 space-y-5 animate-fade-in relative bg-[#0b0f19]">
      <div className="border-b border-[#1e293b] pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-[#f8fafc] tracking-tight">Documentation &amp; Standards</h2>
          <Badge variant="accent">Repo Backed</Badge>
        </div>
        <p className="mt-1 text-sm text-[#94a3b8]">
          Technical architecture, API specifications, and Medallion validation contracts.
        </p>
      </div>

      <div className="max-w-4xl space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          {docs.map((doc) => (
            <a
              key={doc.href}
              href={doc.href}
              target="_blank"
              rel="noreferrer"
              className="group rounded-xl border border-[#1e293b] bg-[#111827] p-5 transition-all hover:border-[#3b82f6]/60 hover:bg-[#131a29] shadow-sm"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#2563eb]/10 text-[#3b82f6]">
                  {doc.icon}
                </span>
                <ExternalLink size={15} className="text-[#64748b] transition-colors group-hover:text-[#f8fafc]" />
              </div>
              <h3 className="mb-1 text-sm font-semibold text-[#f8fafc] group-hover:text-[#3b82f6] transition-colors">{doc.title}</h3>
              <p className="text-xs leading-relaxed text-[#94a3b8]">{doc.detail}</p>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
