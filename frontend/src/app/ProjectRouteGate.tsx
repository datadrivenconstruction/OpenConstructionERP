import { useEffect, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '@/shared/lib/api';
import { EmptyState, Button } from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/**
 * Stands in front of a page under ``/projects/:projectId/...``.
 *
 * A bookmark or an old link to a deleted project, or one the user lost access
 * to (the server answers 404 for both), used to open the module page anyway,
 * and every panel on it failed on its own. When the project lookup answers
 * 404 this renders one clear message with a way back to the project list, and
 * drops the id from the active-project store if it is the one stored there.
 * Every other outcome, loading included, renders the page as before, so a slow
 * or failing lookup never hides a page that works.
 *
 * Shares the ``['project', id]`` query with the project page, so the lookup
 * is made once.
 */
export function ProjectRouteGate({ projectId, children }: { projectId: string; children: ReactNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { error } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
    retry: (count, err) => {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
      return count < 1;
    },
  });
  const gone = error instanceof ApiError && error.status === 404;

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const clearProject = useProjectContextStore((s) => s.clearProject);
  useEffect(() => {
    if (gone && activeProjectId === projectId) clearProject();
  }, [gone, activeProjectId, projectId, clearProject]);

  if (!gone) return <>{children}</>;
  return (
    <div className="w-full">
      <EmptyState
        title={t('projects.not_found', { defaultValue: 'Project not found' })}
        description={t('projects.not_found_route_desc', {
          defaultValue: 'This project does not exist or you no longer have access to it.',
        })}
        action={
          <Button variant="primary" onClick={() => navigate('/projects')}>
            {t('projects.browse_projects', { defaultValue: 'Browse projects' })}
          </Button>
        }
      />
    </div>
  );
}
