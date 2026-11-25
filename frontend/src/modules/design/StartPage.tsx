// Design module (ERP side of the design editor link).
/** /design/start: the project start screen on its own, reachable at any time (also after the first model). */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FolderOpen } from 'lucide-react';
import { EmptyState } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { tr } from './BriefFields';
import { fetchOverview } from './linksApi';
import { ProjectStart } from './ProjectStart';
import { QuickMassing } from './QuickMassing';
import { projectsApi } from '@/features/projects/api';
import { useProjectFromUrl } from './useProjectFromUrl';

export default function StartPage() {
  const { t } = useTranslation();
  useProjectFromUrl();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const q = useQuery({ queryKey: ['design-overview', projectId], queryFn: () => fetchOverview(projectId!), enabled: !!projectId });
  const project = useQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId!), enabled: !!projectId });
  if (!projectId) {
    return <EmptyState icon={<FolderOpen size={28} aria-hidden />} title={tr(t, 'design.brief.no_project')}
      description={tr(t, 'design.brief.no_project_hint')} />;
  }
  return (
    <div className="flex flex-col gap-5 animate-fade-in">
      <h1 className="sr-only">{tr(t, 'design.start.title')}</h1>
      <ProjectStart key={projectId} projectId={projectId} steps={q.data?.steps ?? []} />
      <QuickMassing projectId={projectId} country={project.data?.country_code} />
    </div>
  );
}
