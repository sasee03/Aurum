import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, FolderOpen, Clock, FileText, Zap } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { ProjectCard, OLIST_DEMO_PROJECT_ID } from '@/components/cards/ProjectCard';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import { listProjects, type ApiProject } from '@/lib/aurumApi';
import projectsData from '@/mocks/projects.json';
import type { Environment, Project } from '@/types';

const olistDemoProject = (projectsData as Project[]).find((p) => p.id === OLIST_DEMO_PROJECT_ID)!;

function toProjectCard(api: ApiProject): Project {
  return {
    id: api.id,
    name: api.name,
    businessDomain: '',
    description: api.description,
    environment: api.environment as Environment,
    lastOpened: new Date(api.updated_at).toLocaleDateString(),
    datasetCount: 0,
    status: 'PASS',
  };
}

export function LandingPage() {
  const navigate = useNavigate();
  const { displayMode, isResolved } = useAppMode();
  const { data: reportData, isLoading: reportLoading } = useReport();
  const { data: projectsResponse, isLoading: projectsLoading, isError: projectsError } = useQuery({
    queryKey: ['aurum', 'projects'],
    queryFn: listProjects,
    staleTime: 10_000,
    retry: 1,
  });

  const savedProjects = projectsResponse?.projects.map(toProjectCard) ?? [];

  const reportStatus = reportData?.report
    ? {
        final_verdict: reportData.report.final_verdict,
        layer_status: reportData.report.layer_status,
      }
    : null;

  const cardsLoading = !isResolved || reportLoading || projectsLoading;

  function openExistingProject() {
    if (savedProjects.length > 0) {
      navigate(`/projects/${savedProjects[0].id}/dashboard`);
      return;
    }
    toast('No saved projects yet — opening the verified Olist demo walkthrough.', { icon: 'ℹ️' });
    navigate(`/projects/${OLIST_DEMO_PROJECT_ID}/dashboard`);
  }

  return (
    <div className="min-h-full flex flex-col">
      <section className="flex flex-col items-center justify-center px-6 py-16 md:py-24 text-center animate-fade-in">
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-[#6366f1] shadow-[0_0_40px_rgba(99,102,241,0.35)]">
          <Zap size={28} className="text-white" />
        </div>

        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#6b7280]">
          Enterprise Data Quality Operating System
        </p>

        <h1 className="mb-3 text-5xl font-black tracking-[-0.02em] text-[#f1f5f9] md:text-6xl">
          AURUM
        </h1>

        <p className="mb-10 text-sm text-[#6b7280] max-w-sm">
          Autonomous End-to-End Data Correctness &amp; Business Trust Engine
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <Button
            variant="primary"
            size="lg"
            leftIcon={<Plus size={16} />}
            onClick={() => navigate('/projects/new')}
          >
            New Project
          </Button>
          <Button
            variant="secondary"
            size="lg"
            leftIcon={<FolderOpen size={16} />}
            onClick={openExistingProject}
          >
            Open Existing Project
          </Button>
          <Button
            variant="secondary"
            size="lg"
            leftIcon={<Clock size={16} />}
            onClick={() => navigate('/history')}
          >
            Recent Runs
          </Button>
          <Button
            variant="ghost"
            size="lg"
            leftIcon={<FileText size={16} />}
            onClick={() => navigate('/documentation')}
          >
            Documentation
          </Button>
        </div>
      </section>

      <section className="flex-1 px-6 pb-10 animate-slide-up" aria-label="Recent projects">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#6b7280]">
            Saved Projects
          </h2>
          <button
            className="text-xs text-[#6366f1] hover:text-[#4f46e5] transition-colors focus:outline-none focus:underline"
            onClick={() => navigate(`/projects/${OLIST_DEMO_PROJECT_ID}/dashboard`)}
          >
            Open Olist verified demo
          </button>
        </div>

        {projectsError && (
          <p className="mb-4 text-sm text-[#94a3b8] rounded-lg border border-[#252637] bg-[#13141e] px-4 py-3">
            Could not load saved projects from the API. The Olist demo walkthrough is still available.
          </p>
        )}

        {cardsLoading ? (
          <LoadingSkeleton count={4} className="h-24" />
        ) : savedProjects.length > 0 ? (
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
            {savedProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                reportStatus={null}
                displayMode={displayMode}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title="No Saved Projects Yet"
            description="Create a project to begin onboarding. The verified Olist demo remains available via the link above."
            actionLabel="Create Project"
            onAction={() => navigate('/projects/new')}
          />
        )}

        <div className="mt-8">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#6b7280] mb-3">
            Verified Demo Walkthrough
          </h3>
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 max-w-sm">
            <ProjectCard
              project={olistDemoProject}
              reportStatus={reportStatus}
              displayMode={displayMode}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
