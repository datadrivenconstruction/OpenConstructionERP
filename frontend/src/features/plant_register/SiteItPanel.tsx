// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the site needs to run, beside the permanent plant: the IT services of
// the construction phase (network, access control, CDE access) and the site
// plant positions (cranes, hoists, temporary power). The IT services are kept
// here; the site plant positions are placed in site logistics and only read.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { WideModal, WideModalSection } from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import {
  createItService,
  deleteItService,
  transitionItService,
  updateItService,
  type FrameSummary,
  type ItService,
  type PlantCatalogue,
} from './api';
import { IT_STATE, catalogueName, vocab, type LabelContext } from './labels';
import { DialogFooter, Field, IT_TONE, Refusal, Section, ToneBadge, WriteButton, fieldClass } from './PlantBits';
import { itServiceChanges, itServiceProblems, toItServiceInput, type ItServiceDraft } from './rules';

interface ItServiceDialogProps {
  onClose: () => void;
  projectId: string;
  service: ItService | null;
  catalogue: PlantCatalogue;
  labels: LabelContext;
  onSaved: () => void;
}

export function ItServiceDialog({ onClose, projectId, service, catalogue, labels, onSaved }: ItServiceDialogProps) {
  const { t } = useTranslation();
  const [original] = useState<ItServiceDraft>(() => ({
    kind: service?.kind ?? '',
    description: service?.description ?? '',
    responsible_party: service?.responsible_party ?? '',
    needed_from: service?.needed_from ?? '',
    needed_until: service?.needed_until ?? '',
  }));
  const [draft, setDraft] = useState<ItServiceDraft>(original);
  const [tried, setTried] = useState(false);
  const problems = itServiceProblems(draft);
  const set = <K extends keyof ItServiceDraft>(key: K, value: ItServiceDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      service
        ? updateItService(projectId, service.id, itServiceChanges(original, draft))
        : createItService(projectId, toItServiceInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };
  // Choosing a service proposes the party the catalogue names for it.
  const chooseKind = (kind: string) => {
    const preset = catalogue.it_service_kinds.find((k) => k.code === kind)?.responsible_party ?? '';
    setDraft((d) => ({ ...d, kind, responsible_party: d.responsible_party || preset }));
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-it-dialog"
      title={
        service
          ? t('plant.it.edit_title', { defaultValue: 'Edit the IT service' })
          : t('plant.it.add_title', { defaultValue: 'Add an IT service' })
      }
      subtitle={t('plant.it.subtitle', {
        defaultValue: 'A service the site needs during construction, who provides it and for how long.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={
            service ? t('plant.common.save', { defaultValue: 'Save' }) : t('plant.it.add_submit', { defaultValue: 'Add service' })
          }
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />
        <WideModalSection columns={2}>
          <Field label={t('plant.it.kind', { defaultValue: 'Service' })} required>
            {(id) => (
              <select id={id} className={fieldClass} value={draft.kind} onChange={(e) => chooseKind(e.target.value)}>
                <option value="">{t('plant.common.choose', { defaultValue: 'Choose' })}</option>
                {catalogue.it_service_kinds.map((k) => (
                  <option key={k.code} value={k.code}>
                    {catalogueName(labels, catalogue, 'it_service_kinds', k.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.it.responsible', { defaultValue: 'Provided by' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.responsible_party}
                onChange={(e) => set('responsible_party', e.target.value)}
              >
                <option value="">{t('plant.common.not_set', { defaultValue: 'Not set' })}</option>
                {catalogue.parties.map((party) => (
                  <option key={party.code} value={party.code}>
                    {catalogueName(labels, catalogue, 'parties', party.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.it.needed_from', { defaultValue: 'Needed from' })}>
            {(id) => (
              <input id={id} type="date" className={fieldClass} value={draft.needed_from} onChange={(e) => set('needed_from', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.it.needed_until', { defaultValue: 'Needed until' })}>
            {(id) => (
              <input
                id={id}
                type="date"
                className={fieldClass}
                value={draft.needed_until}
                onChange={(e) => set('needed_until', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.item.description', { defaultValue: 'Description' })} className="sm:col-span-2">
            {(id) => (
              <textarea id={id} rows={2} className={fieldClass} value={draft.description} onChange={(e) => set('description', e.target.value)} />
            )}
          </Field>
        </WideModalSection>
      </div>
    </WideModal>
  );
}

export interface SiteItPanelProps {
  projectId: string;
  services: ItService[];
  sitePlant: FrameSummary['site_plant'];
  catalogue: PlantCatalogue;
  labels: LabelContext;
  onChanged: () => void;
}

export function SiteItPanel({ projectId, services, sitePlant, catalogue, labels, onChanged }: SiteItPanelProps) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<{ service: ItService | null } | null>(null);
  const confirmState = useConfirm();
  const { confirm } = confirmState;
  const run = useMutation({
    mutationFn: (call: () => Promise<unknown>) => call(),
    onSuccess: onChanged,
  });
  const dash = t('plant.common.none', { defaultValue: 'Not set' });
  const period = (from: string | null, to: string | null) =>
    from && to
      ? t('plant.common.date_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(from), to: fmtDate(to) })
      : from
        ? t('plant.common.from_date', { defaultValue: 'From {{date}}', date: fmtDate(from) })
        : dash;

  return (
    <div className="space-y-4" data-testid="plant-site-it">
      <ConfirmDialog {...confirmState} />
      <Section
        title={t('plant.it.section', { defaultValue: 'IT services during construction' })}
        hint={t('plant.it.section_hint', {
          defaultValue: 'Network, access control, time recording and access to the shared data environment for everybody on site.',
        })}
        action={
          <WriteButton size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ service: null })} data-testid="it-add">
            {t('plant.it.add_submit', { defaultValue: 'Add service' })}
          </WriteButton>
        }
      >
        <Refusal error={run.error} className="mb-3" />
        {services.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="it-empty">
            {t('plant.it.empty', {
              defaultValue: 'No IT service planned yet. Start with the site network and access to the shared data environment.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {services.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm" data-testid="it-row">
                <ToneBadge tone={IT_TONE[s.status]}>{vocab(t, IT_STATE, s.status)}</ToneBadge>
                <span className="min-w-0 flex-1 text-content-primary">
                  {catalogueName(labels, catalogue, 'it_service_kinds', s.kind)}
                  {s.description && <span className="block text-xs text-content-tertiary">{s.description}</span>}
                </span>
                <span className="text-xs text-content-secondary">
                  {s.responsible_party ? catalogueName(labels, catalogue, 'parties', s.responsible_party) : dash}
                </span>
                <span className="text-xs text-content-secondary">{period(s.needed_from, s.needed_until)}</span>
                {s.status !== 'retired' && (
                  <span className="flex flex-wrap gap-1">
                    <WriteButton
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        run.mutate(() => transitionItService(projectId, s.id, s.status === 'planned' ? 'provisioned' : 'retired'))
                      }
                    >
                      {s.status === 'planned'
                        ? t('plant.it.provision', { defaultValue: 'Mark as provided' })
                        : t('plant.it.retire', { defaultValue: 'Mark as retired' })}
                    </WriteButton>
                    <WriteButton
                      size="sm"
                      variant="ghost"
                      icon={<Pencil size={14} />}
                      aria-label={t('plant.it.edit_title', { defaultValue: 'Edit the IT service' })}
                      onClick={() => setDialog({ service: s })}
                    />
                    {s.status === 'planned' && (
                      <WriteButton
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={14} />}
                        aria-label={t('plant.it.delete', { defaultValue: 'Delete the IT service' })}
                        onClick={async () => {
                          if (
                            await confirm({
                              title: t('plant.it.delete_confirm_title', { defaultValue: 'Delete this IT service?' }),
                              message: t('plant.it.delete_confirm', {
                                defaultValue: 'The IT service is removed from the plan. This cannot be undone.',
                              }),
                            })
                          ) {
                            run.mutate(() => deleteItService(projectId, s.id));
                          }
                        }}
                      />
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title={t('plant.site.section', { defaultValue: 'Site plant' })}
        hint={t('plant.site.section_hint', {
          defaultValue: 'Cranes, hoists and temporary supplies as they are placed on the site logistics plan.',
        })}
      >
        {sitePlant.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="site-plant-empty">
            {t('plant.site.empty', {
              defaultValue: 'No site plant placed yet. Positions are added on the site logistics plan and appear here.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {sitePlant.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm" data-testid="site-plant-row">
                <span className="min-w-0 flex-1 text-content-primary">
                  {p.name || catalogueName(labels, catalogue, 'site_plant_kinds', p.kind)}
                  <span className="block text-xs text-content-tertiary">{catalogueName(labels, catalogue, 'site_plant_kinds', p.kind)}</span>
                </span>
                {p.reach_m !== null && (
                  <span className="text-xs text-content-secondary">
                    {t('plant.site.reach', { defaultValue: 'Reach {{value}} m', value: fmtNumber(p.reach_m, 1) })}
                  </span>
                )}
                {p.max_load_t !== null && (
                  <span className="text-xs text-content-secondary">
                    {t('plant.site.load', { defaultValue: 'Load {{value}} t', value: fmtNumber(p.max_load_t, 1) })}
                  </span>
                )}
                <span className="text-xs text-content-secondary">{period(p.from_date, p.to_date)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {dialog && (
        <ItServiceDialog
          onClose={() => setDialog(null)}
          projectId={projectId}
          service={dialog.service}
          catalogue={catalogue}
          labels={labels}
          onSaved={() => {
            setDialog(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
