import { useNavigate } from 'react-router-dom';
import { Plus, FolderOpen, Clock, FileText, Zap } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ProjectCard, OLIST_DEMO_PROJECT_ID } from '@/components/cards/ProjectCard';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSkeleton } from '@/components/common/LoadingSkeleton';
import { useAppMode } from '@/context/AppModeContext';
import { useReport } from '@/hooks/useReport';
import projectsData from '@/mocks/projects.json';
import type { Project } from '@/types';

const projects = projectsData as Project[];

export function LandingPage() {
  const navigate = useNavigate();
  const { displayMode, isResolved } = useAppMode();
  const { data, isLoading } = useReport();

  const reportStatus = data?.report
    ? {
        final_verdict: data.report.final_verdict,
        layer_status: data.report.layer_status,
      }
    : null;

  const reportLoading = !isResolved || isLoading;

  function openExistingProject() {
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
            + New Project
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
          <Button variant="ghost" size="lg" leftIcon={<FileText size={16} />}>
            Documentation
          </Button>
        </div>
      </section>

      <section className="flex-1 px-6 pb-10 animate-slide-up" aria-label="Recent projects">
        {projects.length > 0 ? (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#6b7280]">
                Recent Projects
              </h2>
              <button
                className="text-xs text-[#6366f1] hover:text-[#4f46e5] transition-colors focus:outline-none focus:underline"
                onClick={openExistingProject}
              >
                Open Retail Analytics
              </button>
            </div>
            {reportLoading ? (
              <LoadingSkeleton count={4} className="h-24" />
            ) : (
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
                {projects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    reportStatus={reportStatus}
                    displayMode={displayMode}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          <EmptyState
            title="No Existing Projects"
            description="Create your first project to begin validating data."
            actionLabel="Create Project"
            onAction={() => navigate('/projects/new')}
          />
        )}
      </section>
    </div>
  );
}
