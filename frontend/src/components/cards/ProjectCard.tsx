import { useNavigate } from 'react-router-dom';
import type { Project } from '@/types';
import type { LayerStatus } from '@/types/report';
import { VerdictBadge, Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { Database, Clock } from 'lucide-react';

/** Olist demo project — status comes from latest report, not mock JSON. */
export const OLIST_DEMO_PROJECT_ID = 'proj-001';

export interface ProjectReportStatus {
  final_verdict: string;
  layer_status: LayerStatus;
}

interface ProjectCardProps {
  project: Project;
  /** When set, overrides mock project.status for the demo project card. */
  reportStatus?: ProjectReportStatus | null;
  /** True when live + fixture report could not be loaded. */
  reportUnavailable?: boolean;
}

export function ProjectCard({
  project,
  reportStatus,
  reportUnavailable,
}: ProjectCardProps) {
  const navigate = useNavigate();
  const isDemoProject = project.id === OLIST_DEMO_PROJECT_ID;

  function renderStatus() {
    if (!isDemoProject) {
      return (
        <Badge variant="secondary" className="normal-case tracking-normal">
          Preview project
        </Badge>
      );
    }
    if (reportUnavailable) {
      return (
        <Badge variant="secondary" className="normal-case tracking-normal">
          Latest report unavailable
        </Badge>
      );
    }
    if (reportStatus) {
      const ls = reportStatus.layer_status;
      return (
        <div className="flex flex-col gap-1">
          <VerdictBadge verdict={reportStatus.final_verdict} />
          <span className="text-[10px] text-[#6b7280] font-mono">
            B {ls.bronze} · S {ls.silver} · G {ls.gold}
          </span>
        </div>
      );
    }
    return null;
  }

  return (
    <Card
      hoverable
      onClick={() => navigate(`/projects/${project.id}/dashboard`)}
      role="button"
      tabIndex={0}
      aria-label={`Open project: ${project.name}`}
      className="group"
    >
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-[#f1f5f9] group-hover:text-white truncate transition-colors">
          {project.name}
        </h3>
        <div className="flex items-center gap-3 text-xs text-[#6b7280]">
          <span className="flex items-center gap-1">
            <Clock size={11} />
            {project.lastOpened}
          </span>
          <span className="flex items-center gap-1">
            <Database size={11} />
            {project.datasetCount} tables
          </span>
        </div>
        <div className="flex items-center justify-between">
          {renderStatus()}
          <span className="text-[10px] text-[#4b5563] font-medium">{project.environment}</span>
        </div>
      </div>
    </Card>
  );
}
