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
    <div className="min-h-full p-6 animate-fade-in">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#f1f5f9]">Documentation</h2>
        <Badge variant="secondary">Repo backed</Badge>
      </div>

      <div className="max-w-3xl space-y-3">
        <p className="text-sm leading-6 text-[#94a3b8]">
          Aurum documentation describes the product contract: APIs, report shape, validation
          checks, and reliability expectations.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {docs.map((doc) => (
            <a
              key={doc.href}
              href={doc.href}
              target="_blank"
              rel="noreferrer"
              className="group rounded-lg border border-[#252637] bg-[#13141e] p-4 transition-colors hover:border-[#6366f1]/60 hover:bg-[#1a1b28] focus:outline-none focus:ring-2 focus:ring-[#6366f1]"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#6366f1]/10 text-[#818cf8]">
                  {doc.icon}
                </span>
                <ExternalLink size={15} className="text-[#6b7280] transition-colors group-hover:text-[#f1f5f9]" />
              </div>
              <h3 className="mb-1 text-sm font-semibold text-[#f1f5f9]">{doc.title}</h3>
              <p className="text-xs leading-5 text-[#6b7280]">{doc.detail}</p>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
