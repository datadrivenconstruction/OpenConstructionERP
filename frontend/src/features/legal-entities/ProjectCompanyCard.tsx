// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project Settings card: which company and site a project belongs to.
 *
 * Hidden on single-company installs. Moving a project that already issued
 * invoices asks first: those invoices keep the old company as seller.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getErrorMessage } from '@/shared/lib/api';
import { Button, Card, ConfirmDialog } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { LEGAL_ENTITIES_KEY, legalEntitiesApi } from './api';
import { ProjectCompanyFields, type ProjectCompanyValue } from './ProjectCompanyFields';
import { useCompaniesUi } from './useCompanies';

export function ProjectCompanyCard({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const ui = useCompaniesUi();
  const key = [...LEGAL_ENTITIES_KEY, 'project', projectId];
  const entityQ = useQuery({
    queryKey: key,
    queryFn: () => legalEntitiesApi.projectEntity(projectId),
    enabled: ui.multiCompany,
  });
  const [value, setValue] = useState<ProjectCompanyValue>({ entityId: null, branchId: null });
  const [confirm, setConfirm] = useState(false);

  const savedEntity = entityQ.data?.legal_entity?.id ?? null;
  const savedBranch = entityQ.data?.legal_entity_branch_id ?? null;
  useEffect(() => {
    setValue({ entityId: savedEntity, branchId: savedBranch });
  }, [savedEntity, savedBranch]);

  const saveM = useMutation({
    mutationFn: () => legalEntitiesApi.assignProject(projectId, value.entityId, value.branchId),
    onSuccess: () => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: LEGAL_ENTITIES_KEY });
      addToast({ type: 'success', title: t('legal_entities.project_saved', { defaultValue: 'Company updated' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (!ui.multiCompany) return null;

  const dirty = value.entityId !== savedEntity || value.branchId !== savedBranch;
  const issued = entityQ.data?.issued_invoice_count ?? 0;
  const save = () => {
    if (issued > 0 && value.entityId !== savedEntity) setConfirm(true);
    else saveM.mutate();
  };

  return (
    <Card padding="lg" data-testid="project-company-card">
      <div className="grid max-w-xl grid-cols-1 gap-4 sm:grid-cols-2">
        <ProjectCompanyFields value={value} onChange={setValue} disabled={!canEdit || saveM.isPending} />
      </div>
      {canEdit && dirty && (
        <div className="mt-3">
          <Button size="sm" onClick={save} loading={saveM.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirm}
        variant="warning"
        title={t('legal_entities.move_title', { defaultValue: 'Move to another company?' })}
        message={t('legal_entities.move_body', {
          defaultValue: 'Invoices already issued ({{n}}) keep the old company as seller. New documents use the new one.',
          n: issued,
        })}
        loading={saveM.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => saveM.mutate()}
      />
    </Card>
  );
}
