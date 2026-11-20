// Design module (ERP side of the design editor link).
/**
 * Right after a model upload is ready in the BIM upload: "Make this model a project revision?".
 * Nothing is wrapped without the click; "Not now" just closes the question (the revisions page still offers it).
 * Not asked of people without design rights, nor for a model that cannot be wrapped.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useModuleStore } from '@/stores/useModuleStore';
import { useBIMUploadStore } from '@/stores/useBIMUploadStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchImportedModels, importModel } from './api';
import { fetchRights } from './draftApi';
import { MODULE_KEY } from './data/offer';
import { tr } from './BriefFields';

export function ImportAsk({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const enabled = useModuleStore((s) => s.enabledModules[MODULE_KEY] === true);
  const jobs = useBIMUploadStore((s) => s.jobs);
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [added, setAdded] = useState<string | null>(null);

  const job = enabled && projectId
    ? [...jobs.values()].find((j) => j.projectId === projectId && j.status === 'ready' && j.modelId && !closed.has(j.modelId))
    : undefined;
  const modelId = job?.modelId ?? null;

  const rights = useQuery({ queryKey: ['design-rights', projectId], queryFn: () => fetchRights(projectId), enabled: !!modelId, retry: false });
  const models = useQuery({ queryKey: ['design-imported', projectId, modelId], queryFn: () => fetchImportedModels(projectId), enabled: !!modelId && rights.data?.can_edit === true, retry: false });
  const add = useMutation({
    mutationFn: (id: string) => importModel(projectId, id),
    onSuccess: (_rev, id) => {
      setAdded(id);
      qc.invalidateQueries({ queryKey: ['design-imported', projectId] });
      qc.invalidateQueries({ queryKey: ['design-revisions', projectId] });
    },
  });

  const close = (id: string) => setClosed((prev) => new Set(prev).add(id));

  if (added) {
    return (
      <div role="status" data-testid="import-ask-done" className="fixed bottom-4 right-4 z-40 max-w-sm rounded-lg border border-border-light bg-surface-primary p-4 text-sm shadow-lg">
        <p>{tr(t, 'design.import_ask.done')} <Link className="text-oe-blue-text underline" to="/design/revisions">{tr(t, 'design.import_ask.go')}</Link></p>
        <button type="button" className="mt-2 text-content-secondary underline" onClick={() => { close(added); setAdded(null); }}>{tr(t, 'design.import_ask.close')}</button>
      </div>
    );
  }
  if (!modelId || rights.data?.can_edit !== true) return null;
  const model = models.data?.find((m) => m.bim_model_id === modelId);
  if (!model) return null;

  return (
    <div role="dialog" aria-label={tr(t, 'design.import_ask.question')} data-testid="import-ask" className="fixed bottom-4 right-4 z-40 max-w-sm rounded-lg border border-border-light bg-surface-primary p-4 shadow-lg">
      <p className="font-medium">{tr(t, 'design.import_ask.question')}</p>
      <p className="mt-1 text-sm text-content-secondary">{tr(t, 'design.import_ask.hint', { name: model.name })}</p>
      {add.isError && <p role="alert" className="mt-2 text-sm text-semantic-error">{getErrorMessage(add.error)}</p>}
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={add.isPending} className="rounded bg-oe-blue px-3 py-1.5 text-sm text-white disabled:opacity-60" onClick={() => add.mutate(modelId)}>
          {tr(t, 'design.import_ask.yes')}
        </button>
        <button type="button" disabled={add.isPending} className="rounded px-3 py-1.5 text-sm text-content-secondary underline" onClick={() => close(modelId)}>
          {tr(t, 'design.import_ask.no')}
        </button>
      </div>
    </div>
  );
}
