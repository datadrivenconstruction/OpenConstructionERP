// Design module (ERP side of the design editor link).
/**
 * Workspace settings behind one button: background load of the editor, the editor's AI (default: the ERP's) and, for
 * project managers, who may edit the design of this project. Escape or a click outside closes it.
 */
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Settings2 } from 'lucide-react';
import { fetchAiSettings } from './api';
import { fetchAiChoice, putAiChoice, putRights, type DesignRights } from './draftApi';
import { aiServices } from './data/workspace';
import { BackgroundLoadToggle, LoadHint } from './BackgroundLoad';
import { tr } from './BriefFields';
import { WebEditorPanel } from './WebEditorPanel';

function AiChoiceForm() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const choice = useQuery({ queryKey: ['design-ai-choice'], queryFn: fetchAiChoice, staleTime: 60_000 });
  const settings = useQuery({ queryKey: ['ai-settings'], queryFn: fetchAiSettings, staleTime: 60_000 });
  const services = aiServices(settings.data);
  const [own, setOwn] = useState(false);
  const [service, setService] = useState('');
  const [model, setModel] = useState('');
  useEffect(() => {
    if (!choice.data) return;
    setOwn(!choice.data.same_as_erp);
    setService(choice.data.preferred_model ?? '');
    setModel(choice.data.model ?? '');
  }, [choice.data]);
  const save = useMutation({
    mutationFn: () => putAiChoice(own ? { preferred_model: service || null, model: model.trim() || null } : { preferred_model: null, model: null }),
    onSuccess: (c) => qc.setQueryData(['design-ai-choice'], c),
  });
  const changed = choice.data && (own !== !choice.data.same_as_erp || (own && (service !== (choice.data.preferred_model ?? '') || model !== (choice.data.model ?? ''))));
  return (
    <fieldset className="flex flex-col gap-1.5" data-testid="ai-choice">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">{tr(t, 'design.workspace.ai_choice.title')}</legend>
      <label className="flex items-center gap-2"><input type="radio" name="ai-choice" checked={!own} onChange={() => setOwn(false)} />{tr(t, 'design.workspace.ai_choice.same')}</label>
      <label className="flex items-center gap-2"><input type="radio" name="ai-choice" checked={own} onChange={() => setOwn(true)} disabled={services.length === 0} />{tr(t, 'design.workspace.ai_choice.own')}</label>
      {services.length === 0 && <p className="text-xs text-content-tertiary">{tr(t, 'design.workspace.ai_choice.none')}</p>}
      {own && (
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5 ps-6">
          <label htmlFor="ai-service" className="text-xs text-content-secondary">{tr(t, 'design.workspace.ai_choice.service')}</label>
          <select id="ai-service" className="rounded border border-border bg-surface-primary px-2 py-1" value={service} onChange={(e) => setService(e.target.value)}>
            <option value="" />
            {services.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <label htmlFor="ai-model" className="text-xs text-content-secondary">{tr(t, 'design.workspace.ai_choice.model')}</label>
          <input id="ai-model" className="rounded border border-border bg-surface-primary px-2 py-1" value={model} maxLength={200} onChange={(e) => setModel(e.target.value)} />
        </div>
      )}
      {changed && (
        <button type="button" className="self-start rounded-md bg-oe-blue px-3 py-1 text-sm text-white disabled:opacity-50"
          disabled={save.isPending || (own && !service)} onClick={() => save.mutate()}>
          {tr(t, 'design.workspace.ai_choice.save')}
        </button>
      )}
    </fieldset>
  );
}

function RightsForm({ projectId, rights }: { projectId: string; rights: DesignRights }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const set = useMutation({
    mutationFn: (edit: DesignRights['edit']) => putRights(projectId, edit),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['design-rights', projectId] }),
  });
  return (
    <fieldset className="flex flex-col gap-1.5" data-testid="rights">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">{tr(t, 'design.workspace.rights.title')}</legend>
      {(['members', 'managers'] as const).map((v) => (
        <label key={v} className="flex items-center gap-2">
          <input type="radio" name="design-rights" checked={rights.edit === v} disabled={set.isPending} onChange={() => set.mutate(v)} />
          {tr(t, `design.workspace.rights.${v}`)}
        </label>
      ))}
      <p className="text-xs text-content-tertiary">{tr(t, 'design.workspace.rights.note')}</p>
    </fieldset>
  );
}

export function WorkspaceSettings({ projectId, rights }: { projectId: string; rights: DesignRights | undefined }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('keydown', key);
    document.addEventListener('mousedown', click);
    return () => { document.removeEventListener('keydown', key); document.removeEventListener('mousedown', click); };
  }, [open]);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-expanded={open} aria-haspopup="dialog" data-testid="workspace-settings"
        aria-label={tr(t, 'design.workspace.settings')} title={tr(t, 'design.workspace.settings')}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-content-secondary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
        onClick={() => setOpen((o) => !o)}>
        <Settings2 size={16} aria-hidden />
      </button>
      {open && (
        <div role="dialog" aria-label={tr(t, 'design.workspace.settings')}
          className="absolute end-0 top-10 z-30 flex w-[min(340px,calc(100vw-2rem))] flex-col gap-4 rounded-lg border border-border-light bg-surface-primary p-4 text-sm shadow-lg">
          <div className="flex flex-col gap-1"><BackgroundLoadToggle /><LoadHint /></div>
          <WebEditorPanel />
          <AiChoiceForm />
          {rights?.can_accept && <RightsForm projectId={projectId} rights={rights} />}
        </div>
      )}
    </div>
  );
}
