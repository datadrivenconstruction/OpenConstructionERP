// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Opens a project on the page this person chose for the project's setup role
 * (Settings > General > Start and calendar). With nothing chosen it goes to the
 * project page without any extra request, exactly as before.
 */
import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { hasProjectStart, projectStartFor } from '@/shared/lib/workPrefs';
import { projectsApi } from './api';

export function useOpenProject(): (id: string, name: string) => Promise<void> {
  const navigate = useNavigate();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  return useCallback(
    async (id: string, name: string) => {
      if (hasProjectStart()) {
        try {
          const result = await projectsApi.getProfile(id);
          const page = projectStartFor(result.profile?.role);
          if (page !== 'overview') {
            setActiveProject(id, name);
            navigate(`/${page}`);
            return;
          }
        } catch {
          /* no profile or offline: the project page is always a safe landing */
        }
      }
      navigate(`/projects/${id}`);
    },
    [navigate, setActiveProject],
  );
}
