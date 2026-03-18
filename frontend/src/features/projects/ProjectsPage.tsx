import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { FolderPlus, ArrowRight, MoreHorizontal } from 'lucide-react';
import { Button, Card, Badge, EmptyState } from '@/shared/ui';
import { projectsApi, type Project } from './api';

export function ProjectsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  });

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('projects.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {projects?.length ?? 0} projects
          </p>
        </div>
        <Button
          variant="primary"
          icon={<FolderPlus size={16} />}
          onClick={() => navigate('/projects/new')}
        >
          {t('projects.new_project')}
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="h-32 animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<FolderPlus size={24} strokeWidth={1.5} />}
          title={t('projects.no_projects')}
          description="Create your first construction cost estimation project"
          action={
            <Button variant="primary" onClick={() => navigate('/projects/new')}>
              {t('projects.new_project')}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const navigate = useNavigate();

  const standardLabels: Record<string, string> = {
    din276: 'DIN 276',
    nrm: 'NRM',
    masterformat: 'MasterFormat',
  };

  return (
    <Card hoverable padding="none" className="cursor-pointer" onClick={() => navigate(`/projects/${project.id}`)}>
      <div className="p-5">
        <div className="flex items-start justify-between">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
            {project.name.charAt(0).toUpperCase()}
          </div>
          <button
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary"
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal size={14} />
          </button>
        </div>
        <h3 className="mt-3 text-sm font-semibold text-content-primary truncate">
          {project.name}
        </h3>
        {project.description && (
          <p className="mt-1 text-xs text-content-secondary line-clamp-2">
            {project.description}
          </p>
        )}
        <div className="mt-3 flex items-center gap-2">
          <Badge variant="blue" size="sm">
            {standardLabels[project.classification_standard] ?? project.classification_standard}
          </Badge>
          <Badge variant="neutral" size="sm">{project.currency}</Badge>
          <Badge variant="neutral" size="sm">{project.region}</Badge>
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-border-light px-5 py-2.5">
        <span className="text-2xs text-content-tertiary">
          {new Date(project.created_at).toLocaleDateString()}
        </span>
        <ArrowRight size={12} className="text-content-tertiary" />
      </div>
    </Card>
  );
}
