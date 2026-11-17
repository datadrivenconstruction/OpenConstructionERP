// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiPost } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

/** The survey course project; its install also seeds points, surfaces and V-001. */
export const SURVEY_DEMO_ID = 'survey-riverside-yard';

/** "Open demo project": install Riverside Yard (or reuse it), make it active and stay on this page. */
export function useOpenSurveyDemo(path: string) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const [busy, setBusy] = useState(false);

  const open = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await apiPost<{ project_id: string; project_name?: string }>(`/demo/install/${SURVEY_DEMO_ID}`, undefined, {
        longRunning: true,
      });
      setActiveProject(res.project_id, res.project_name ?? 'Riverside Yard (survey demo)');
      await qc.invalidateQueries();
      navigate(path);
    } catch {
      addToast({ type: 'error', title: t('onboarding.demo_install_error', { defaultValue: 'Failed to install demo project' }) });
    } finally {
      setBusy(false);
    }
  };
  return { open, busy };
}
