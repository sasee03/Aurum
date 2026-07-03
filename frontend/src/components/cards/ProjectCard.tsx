import { useNavigate } from 'react-router-dom';
import type { Project } from '@/types';
import { StatusBadge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { Database, Clock } from 'lucide-react';

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  const navigate = useNavigate();

  return (
    <Card
      hoverable
      onClick={() => navigate(`/projects/${project.id}/connect`)}
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
          <StatusBadge status={project.status} />
          <span className="text-[10px] text-[#4b5563] font-medium">{project.environment}</span>
        </div>
      </div>
    </Card>
  );
}
