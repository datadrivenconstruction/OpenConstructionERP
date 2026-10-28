// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Market sounding: what the market said before the tender. Each entry records
// when and how the market was asked, what came back on capacity, price and
// lead time, and what the project does about a tight market. Tight capacity
// with no answer to it shows as a warning on the concept.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueries } from '@tanstack/react-query';
import { AlertTriangle, ChevronDown, ChevronRight, MessageSquare, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import type { BadgeVariant } from '@/shared/ui/Badge';

import {
  createSounding,
  deleteSounding,
  listCandidates,
  localToday,
  patchSounding,
  procurementKeys,
  type Capability,
  type CapacitySignal,
  type MarketSounding,
  type PackageView,
  type PriceSignal,
  type SoundingMethod,
} from './api';
import { useRefusalToast } from './hooks';
import { CAPACITY, METHOD, PRICE, vocab, type LabelContext } from './labels';
import { FIELD_CLASS, Field, ReasonedButton, RefusalBox, ToneBadge } from './ProcurementBits';
import { capVerdict, notApplicable, soundingReady, soundingUnmitigated, toSoundingInput, type SoundingDraft } from './rules';

const METHODS: SoundingMethod[] = ['meeting', 'survey', 'rfi', 'notice'];
const CAPACITIES: CapacitySignal[] = ['ample', 'adequate', 'tight', 'insufficient'];
const PRICES: PriceSignal[] = ['unknown', 'below_estimate', 'in_line', 'above_estimate'];

const CAPACITY_TONE: Record<CapacitySignal, BadgeVariant> = {
  ample: 'success',
  adequate: 'success',
  tight: 'warning',
  insufficient: 'error',
};

export interface MarketSoundingsProps {
  projectId: string;
  soundings: MarketSounding[];
  /** What the reader may do on the list, as the server sent it. */
  can?: Partial<Record<'create' | 'edit' | 'delete', Capability>>;
  packages: PackageView[];
  labels: LabelContext;
  onChanged: () => void;
}

export function MarketSoundings({ projectId, soundings, can, packages, labels, onChanged }: MarketSoundingsProps) {
  const v = (key: 'create' | 'edit' | 'delete') => capVerdict(can?.[key], 'permission_denied');
  const { t } = useTranslation();
  const toastRefusal = useRefusalToast();
  const [editing, setEditing] = useState<MarketSounding | 'new' | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const codes = new Map(packages.map((p) => [p.contract_package.id, p.contract_package.code]));

  const remove = useMutation({
    mutationFn: (id: string) => deleteSounding(projectId, id),
    onSuccess: () => {
      setRemoving(null);
      onChanged();
    },
    onError: toastRefusal,
  });

  const addButton = notApplicable(can?.create) ? undefined : (
    <ReasonedButton verdict={v('create')} icon={<Plus size={14} />} onClick={() => setEditing('new')} data-testid="sounding-add">
      {t('procurement_concept.ui.sounding.add', { defaultValue: 'Record a sounding' })}
    </ReasonedButton>
  );

  return (
    <div className="space-y-3" data-testid="market-soundings">
      {soundings.length === 0 ? (
        <EmptyState
          icon={<MessageSquare size={28} />}
          title={t('procurement_concept.ui.sounding.empty_title', { defaultValue: 'No market sounding recorded yet' })}
          description={t('procurement_concept.ui.sounding.empty_body', {
            defaultValue:
              'Ask the market before you tender: who has capacity, where prices stand, how long delivery takes. Record each round here so the package plan can answer it.',
          })}
          action={addButton}
        />
      ) : (
        <>
          <div className="flex justify-end">{addButton}</div>
          <ul className="space-y-2">
            {soundings.map((s) => {
              const pkgCodes = s.package_ids.map((id) => codes.get(id)).filter((c): c is string => !!c);
              return (
                <li key={s.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="sounding-entry">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-content-primary">
                      {s.trade || t('procurement_concept.ui.sounding.untitled', { defaultValue: 'Market sounding' })}
                    </span>
                    <span className="text-xs text-content-tertiary">
                      {t('procurement_concept.ui.sounding.held', {
                        defaultValue: '{{method}} on {{date}}',
                        method: vocab(labels.t, METHOD, s.method),
                        date: fmtDate(s.held_on),
                      })}
                    </span>
                    {pkgCodes.length > 0 && <span className="font-mono text-xs text-content-tertiary">{fmtList(pkgCodes)}</span>}
                    <span className="ml-auto flex items-center gap-1.5">
                      {!notApplicable(can?.edit) && (
                        <ReasonedButton quiet verdict={v('edit')} size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(s)} data-testid="sounding-edit">
                          {t('procurement_concept.ui.prequal.edit', { defaultValue: 'Change' })}
                        </ReasonedButton>
                      )}
                      {!notApplicable(can?.delete) && (
                        <ReasonedButton
                          quiet
                          verdict={v('delete')}
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={14} />}
                          aria-label={t('procurement_concept.ui.sounding.remove', { defaultValue: 'Remove this sounding' })}
                          onClick={() => setRemoving(s.id)}
                          data-testid="sounding-remove"
                        >
                          {null}
                        </ReasonedButton>
                      )}
                    </span>
                  </div>
                  <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                    <div className="flex items-center gap-1.5">
                      <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.sounding.capacity', { defaultValue: 'Capacity' })}</dt>
                      <dd>
                        <ToneBadge tone={CAPACITY_TONE[s.capacity_signal]} testId="sounding-capacity">
                          {vocab(labels.t, CAPACITY, s.capacity_signal)}
                        </ToneBadge>
                      </dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.sounding.price', { defaultValue: 'Price level' })}</dt>
                      <dd className="text-content-primary">{vocab(labels.t, PRICE, s.price_signal)}</dd>
                    </div>
                    {s.lead_time_signal_days !== null && (
                      <div className="flex items-center gap-1.5">
                        <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.sounding.lead_time', { defaultValue: 'Lead time' })}</dt>
                        <dd className="text-content-primary">
                          {t('procurement_concept.ui.days', { defaultValue: '{{count}} days', count: s.lead_time_signal_days })}
                        </dd>
                      </div>
                    )}
                  </dl>
                  {s.participant_candidate_ids.length > 0 && <Participants projectId={projectId} sounding={s} />}
                  {s.findings && <p className="mt-2 text-sm text-content-primary">{s.findings}</p>}
                  {s.mitigation && (
                    <p className="mt-1 text-sm text-content-secondary">
                      <span className="text-xs text-content-tertiary">
                        {t('procurement_concept.ui.sounding.mitigation', { defaultValue: 'What we do about it' })}
                      </span>{' '}
                      {s.mitigation}
                    </p>
                  )}
                  {s.resplit && (
                    <p className="mt-1 text-xs text-content-secondary">
                      {t('procurement_concept.ui.sounding.resplit_done', { defaultValue: 'The packages were split again in answer to this.' })}
                    </p>
                  )}
                  {s.unmitigated && (
                    <p className="mt-2 flex items-start gap-1.5 text-sm text-semantic-warning" data-testid="sounding-unmitigated">
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                      {t('procurement_concept.findings.capacity_unmitigated', { defaultValue: 'Tight market capacity without mitigation' })}
                    </p>
                  )}
                  {removing === s.id && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-surface-secondary p-2">
                      <span className="text-xs text-content-primary">
                        {t('procurement_concept.ui.sounding.remove_confirm', { defaultValue: 'Remove this sounding from the record?' })}
                      </span>
                      <Button size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutate(s.id)} data-testid="sounding-remove-yes">
                        {t('procurement_concept.ui.remove', { defaultValue: 'Remove' })}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(null)}>
                        {t('procurement_concept.ui.keep', { defaultValue: 'Not now' })}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {editing && (
        <SoundingDialog
          open
          onClose={() => setEditing(null)}
          projectId={projectId}
          sounding={editing === 'new' ? null : editing}
          packages={packages}
          labels={labels}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}

/** How many companies were asked, and on demand who: the candidates are read only when the reader opens the list. */
function Participants({ projectId, sounding }: { projectId: string; sounding: MarketSounding }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const qs = useQueries({
    queries: sounding.package_ids.map((id) => ({
      queryKey: procurementKeys.candidates(projectId, id),
      queryFn: () => listCandidates(projectId, id),
      enabled: open,
    })),
  });
  const names = new Map(qs.flatMap((q) => q.data?.items ?? []).map((c) => [c.id, c.name]));
  const loading = qs.some((q) => q.isLoading);
  const failed = qs.some((q) => q.isError);
  const ids = sounding.participant_candidate_ids;
  return (
    <div className="mt-2 text-sm" data-testid="sounding-participants">
      <button
        type="button"
        className="inline-flex items-center gap-1 text-content-primary hover:text-oe-blue"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        data-testid="sounding-participants-toggle"
      >
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        {t('procurement_concept.ui.sounding.participants_count', { defaultValue: 'Companies asked: {{n}}', n: ids.length })}
      </button>
      {open &&
        (loading ? (
          <p className="mt-1 text-xs text-content-tertiary">
            {t('procurement_concept.ui.sounding.participants_loading', { defaultValue: 'Looking up the candidates of these packages' })}
          </p>
        ) : (
          <ul className="mt-1 flex flex-wrap gap-1.5" data-testid="sounding-participant-names">
            {ids.map((id) => (
              <li key={id} className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-primary">
                {names.get(id) ??
                  (failed
                    ? t('procurement_concept.ui.sounding.participant_unread', { defaultValue: 'Name could not be read' })
                    : t('procurement_concept.ui.sounding.participant_gone', { defaultValue: 'A company no longer among the candidates' }))}
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

function SoundingDialog({
  open,
  onClose,
  projectId,
  sounding,
  packages,
  labels,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  sounding: MarketSounding | null;
  packages: PackageView[];
  labels: LabelContext;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<SoundingDraft>({
    package_ids: sounding?.package_ids ?? [],
    trade: sounding?.trade ?? '',
    held_on: sounding?.held_on ?? localToday(),
    method: sounding?.method ?? 'meeting',
    findings: sounding?.findings ?? '',
    capacity_signal: sounding?.capacity_signal ?? 'adequate',
    price_signal: sounding?.price_signal ?? 'unknown',
    lead_time_signal_days: sounding?.lead_time_signal_days == null ? '' : String(sounding.lead_time_signal_days),
    mitigation: sounding?.mitigation ?? '',
    resplit: sounding?.resplit ?? false,
    participant_candidate_ids: sounding?.participant_candidate_ids ?? [],
  });
  const set = <K extends keyof SoundingDraft>(key: K, value: SoundingDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const togglePackage = (id: string) =>
    set('package_ids', draft.package_ids.includes(id) ? draft.package_ids.filter((x) => x !== id) : [...draft.package_ids, id]);
  const planned = packages.filter((p) => p.award);
  const stored = sounding?.participant_candidate_ids ?? [];
  const picked = draft.participant_candidate_ids ?? [];
  const toggleParticipant = (id: string) =>
    set('participant_candidate_ids', picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  // The companies that can have taken part are the candidates of the packages the sounding concerns.
  const candidateQs = useQueries({
    queries: draft.package_ids.map((id) => ({
      queryKey: procurementKeys.candidates(projectId, id),
      queryFn: () => listCandidates(projectId, id),
    })),
  });
  const candidates = candidateQs.flatMap((q) => q.data?.items ?? []);
  const loadingCandidates = candidateQs.some((q) => q.isLoading);
  // Named before, and not among the candidates listed now: kept until the reader takes it off.
  const unlisted = picked.filter((id) => !candidates.some((c) => c.id === id));

  const save = useMutation({
    mutationFn: () =>
      sounding ? patchSounding(projectId, sounding.id, toSoundingInput(draft, stored)) : createSounding(projectId, toSoundingInput(draft)),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="sounding-dialog"
      title={
        sounding
          ? t('procurement_concept.ui.sounding.edit_title', { defaultValue: 'Market sounding' })
          : t('procurement_concept.ui.sounding.add', { defaultValue: 'Record a sounding' })
      }
      subtitle={t('procurement_concept.ui.sounding.subtitle', {
        defaultValue: 'What the market answered, and what the project does about it.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={!soundingReady(draft)} onClick={() => save.mutate()} data-testid="sounding-save">
            {t('procurement_concept.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t('procurement_concept.ui.sounding.trade', { defaultValue: 'Trade or subject' })} htmlFor="ms-trade">
            <input id="ms-trade" className={FIELD_CLASS} value={draft.trade} onChange={(e) => set('trade', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.sounding.held_on', { defaultValue: 'Held on' })} htmlFor="ms-date">
            <input id="ms-date" type="date" className={FIELD_CLASS} value={draft.held_on} onChange={(e) => set('held_on', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.sounding.method', { defaultValue: 'How the market was asked' })} htmlFor="ms-method">
            <select id="ms-method" className={FIELD_CLASS} value={draft.method} onChange={(e) => set('method', e.target.value as SoundingMethod)}>
              {METHODS.map((m) => (
                <option key={m} value={m}>
                  {vocab(labels.t, METHOD, m)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {planned.length > 0 && (
          <fieldset>
            <legend className="mb-1 text-xs font-medium text-content-secondary">
              {t('procurement_concept.ui.sounding.packages', { defaultValue: 'Packages it concerns' })}
            </legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {planned.map((p) => (
                <label key={p.contract_package.id} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    checked={draft.package_ids.includes(p.contract_package.id)}
                    onChange={() => togglePackage(p.contract_package.id)}
                  />
                  <span className="font-mono text-xs">{p.contract_package.code}</span> {p.contract_package.title}
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <fieldset data-testid="sounding-participant-picker">
          <legend className="mb-1 text-xs font-medium text-content-secondary">
            {t('procurement_concept.ui.sounding.participants', { defaultValue: 'Companies asked' })}
          </legend>
          {candidates.length === 0 && unlisted.length === 0 ? (
            <p className="text-xs text-content-tertiary" data-testid="sounding-participants-none">
              {loadingCandidates
                ? t('procurement_concept.ui.sounding.participants_loading', { defaultValue: 'Looking up the candidates of these packages' })
                : draft.package_ids.length === 0
                  ? t('procurement_concept.ui.sounding.participants_pick_package', {
                      defaultValue: 'Choose the packages the sounding concerns to name the companies that took part.',
                    })
                  : t('procurement_concept.ui.sounding.participants_none', {
                      defaultValue: 'These packages have no candidates yet. Add the companies on the Prequalification tab first.',
                    })}
            </p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {candidates.map((c) => (
                <label key={c.id} className="inline-flex items-center gap-1.5 text-sm text-content-primary" data-testid="sounding-participant">
                  <input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggleParticipant(c.id)} />
                  {c.name}
                </label>
              ))}
              {unlisted.map((id) => (
                <label key={id} className="inline-flex items-center gap-1.5 text-sm text-content-secondary" data-testid="sounding-participant-kept">
                  <input type="checkbox" checked onChange={() => toggleParticipant(id)} />
                  {t('procurement_concept.ui.sounding.participant_kept', { defaultValue: 'A company named before' })}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t('procurement_concept.ui.sounding.capacity', { defaultValue: 'Capacity' })} htmlFor="ms-capacity">
            <select
              id="ms-capacity"
              className={FIELD_CLASS}
              value={draft.capacity_signal}
              onChange={(e) => set('capacity_signal', e.target.value as CapacitySignal)}
            >
              {CAPACITIES.map((c) => (
                <option key={c} value={c}>
                  {vocab(labels.t, CAPACITY, c)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('procurement_concept.ui.sounding.price', { defaultValue: 'Price level' })} htmlFor="ms-price">
            <select id="ms-price" className={FIELD_CLASS} value={draft.price_signal} onChange={(e) => set('price_signal', e.target.value as PriceSignal)}>
              {PRICES.map((p) => (
                <option key={p} value={p}>
                  {vocab(labels.t, PRICE, p)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('procurement_concept.ui.sounding.lead_time_days', { defaultValue: 'Lead time heard, in days' })} htmlFor="ms-lead">
            <input
              id="ms-lead"
              inputMode="numeric"
              className={FIELD_CLASS}
              value={draft.lead_time_signal_days}
              onChange={(e) => set('lead_time_signal_days', e.target.value)}
            />
          </Field>
        </div>
        <Field label={t('procurement_concept.ui.sounding.findings', { defaultValue: 'What the market said' })} htmlFor="ms-findings">
          <textarea id="ms-findings" rows={3} className={FIELD_CLASS} value={draft.findings} onChange={(e) => set('findings', e.target.value)} />
        </Field>
        <Field label={t('procurement_concept.ui.sounding.mitigation', { defaultValue: 'What we do about it' })} htmlFor="ms-mitigation">
          <textarea id="ms-mitigation" rows={2} className={FIELD_CLASS} value={draft.mitigation} onChange={(e) => set('mitigation', e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input type="checkbox" checked={draft.resplit} onChange={(e) => set('resplit', e.target.checked)} />
          {t('procurement_concept.ui.sounding.resplit', { defaultValue: 'The packages are split again in answer to this' })}
        </label>
        {soundingUnmitigated(draft) && (
          <p className="flex items-start gap-1.5 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-xs text-content-primary" role="note" data-testid="sounding-warning">
            <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden />
            {t('procurement_concept.ui.sounding.unmitigated_hint', {
              defaultValue: 'Capacity is tight. Say what the project does about it, or the concept carries a warning.',
            })}
          </p>
        )}
      </div>
    </WideModal>
  );
}
