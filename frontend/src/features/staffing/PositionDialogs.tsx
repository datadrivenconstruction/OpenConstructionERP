// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dialogs of the staffing plan: add or change a position, add the roles
// a phase needs straight from the catalogue, put a person on a position, and
// plan a handover between two people.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import {
  createFill,
  createHandover,
  createPosition,
  createPositionsFromCatalogue,
  updateHandover,
  updatePosition,
  type Handover,
  type Phase,
  type Position,
  type PositionInput,
  type RecruitingChannel,
  type StaffingCatalogue,
  type StaffingPlan,
} from './api';
import { useRoster } from './hooks';
import {
  PHASE,
  RECRUITING_CHANNEL,
  catalogueName,
  errorText,
  humanizeCode,
  positionName,
  vocab,
  whyNot,
  type LabelContext,
} from './labels';
import { datesProblem, decimalString, fteProblem, headcountProblem, liveFills, requirementTags, rolesNotPlanned } from './rules';
import { FIELD_CLASS, FormError, PeoplePickerNote, personLabel } from './StaffingBits';
import { useSubmit } from './useSubmit';

const CHANNELS = Object.keys(RECRUITING_CHANNEL) as RecruitingChannel[];

interface DialogBase {
  open: boolean;
  projectId: string;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

function Footer({
  busy,
  error,
  onClose,
  onSave,
  saveLabel,
  disabled,
  testId,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: () => void;
  saveLabel: string;
  disabled?: boolean;
  testId: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full items-center justify-end gap-2">
      <FormError message={error} />
      <Button variant="ghost" onClick={onClose} disabled={busy}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
      <Button loading={busy} disabled={disabled} onClick={onSave} data-testid={testId}>
        {saveLabel}
      </Button>
    </div>
  );
}

interface PositionDraft {
  role_code: string;
  phase: Phase;
  custom_label: string;
  organisation: string;
  title: string;
  fte: string;
  headcount: string;
  entry_date: string;
  exit_date: string;
  key_role: boolean;
  handover_role: boolean;
  required_before: string;
  recruiting_channel: RecruitingChannel | '';
  owner_user_id: string;
  notes: string;
}

function draftOf(position: Position | null, catalogue: StaffingCatalogue, phase: Phase): PositionDraft {
  if (position) {
    return {
      role_code: position.role_code,
      phase: position.phase,
      custom_label: position.custom_label ?? '',
      organisation: position.organisation ?? '',
      title: position.title ?? '',
      fte: position.fte,
      headcount: String(position.headcount),
      entry_date: position.entry_date ?? '',
      exit_date: position.exit_date ?? '',
      key_role: position.key_role,
      handover_role: position.handover_role,
      required_before: position.required_before ?? '',
      recruiting_channel: position.recruiting_channel ?? '',
      owner_user_id: position.owner_user_id ?? '',
      notes: position.notes ?? '',
    };
  }
  const role = catalogue.roles.find((r) => r.phases.includes(phase)) ?? catalogue.roles[0];
  return {
    role_code: role?.code ?? catalogue.custom_role_code,
    phase,
    custom_label: '',
    organisation: role?.organisation ?? catalogue.organisations[0]?.code ?? '',
    title: '',
    fte: role?.default_fte ?? '1',
    headcount: '1',
    entry_date: '',
    exit_date: '',
    key_role: role?.key_role ?? false,
    handover_role: role?.handover_role ?? false,
    required_before: role?.required_before ?? '',
    recruiting_channel: '',
    owner_user_id: '',
    notes: '',
  };
}

/** The first thing wrong with a position draft, as the code the server would answer with. */
export function positionProblem(
  draft: Pick<PositionDraft, 'role_code' | 'custom_label' | 'fte' | 'headcount' | 'entry_date' | 'exit_date'>,
  customRole: string,
): string | null {
  if (draft.role_code === customRole && !draft.custom_label.trim()) return 'custom_role_needs_label';
  return fteProblem(draft.fte) ?? headcountProblem(draft.headcount) ?? datesProblem(draft.entry_date, draft.exit_date);
}

export function PositionDialog({
  open,
  projectId,
  labels,
  catalogue,
  position,
  plan,
  phases,
  defaultPhase,
  onClose,
  onDone,
}: DialogBase & {
  catalogue: StaffingCatalogue;
  position: Position | null;
  plan: StaffingPlan;
  phases: Phase[];
  defaultPhase: Phase;
}) {
  const { t } = useTranslation();
  // What a gate reads of a position, and who its line manager is, follow the server's flags: on an existing
  // position its own flag, on a new one the caller's manage flag of the plan.
  const gate = position ? position.can.gate_fields : plan.can.manage;
  const mayOwner = plan.can.assign_owner;
  const [draft, setDraft] = useState<PositionDraft>(() => draftOf(position, catalogue, defaultPhase));
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setDraft(draftOf(position, catalogue, defaultPhase));
      setTried(false);
      reset();
    }
    // The draft restarts when the dialog opens, not when the lists refetch behind it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, position?.id]);

  const set = <K extends keyof PositionDraft>(key: K, value: PositionDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const chooseRole = (code: string) => {
    const role = catalogue.roles.find((r) => r.code === code);
    setDraft((d) => ({
      ...d,
      role_code: code,
      organisation: role?.organisation ?? d.organisation,
      fte: role?.default_fte ?? d.fte,
      key_role: role?.key_role ?? false,
      handover_role: role?.handover_role ?? false,
      required_before: role?.required_before ?? '',
    }));
  };

  const problem = positionProblem(draft, catalogue.custom_role_code);
  const save = () => {
    if (problem) {
      setTried(true);
      return;
    }
    const body: PositionInput = {
      role_code: draft.role_code,
      phase: draft.phase,
      custom_label: draft.custom_label.trim() || null,
      organisation: draft.organisation || null,
      title: draft.title.trim() || null,
      fte: decimalString(draft.fte),
      headcount: Number(draft.headcount),
      entry_date: draft.entry_date || null,
      exit_date: draft.exit_date || null,
      recruiting_channel: draft.recruiting_channel || null,
      notes: draft.notes.trim() || null,
    };
    // Sent only by a caller the server lets change them; otherwise the server keeps what the catalogue says.
    if (gate.allowed) {
      body.key_role = draft.key_role;
      body.handover_role = draft.handover_role;
      if (position || draft.required_before) body.required_before = draft.required_before || null;
    }
    if (mayOwner.allowed && (position || draft.owner_user_id)) body.owner_user_id = draft.owner_user_id || null;
    void run(() => (position ? updatePosition(projectId, position.id, body) : createPosition(projectId, body)));
  };

  const roles = catalogue.roles.filter((r) => r.phases.includes(draft.phase) || r.code === draft.role_code);
  const tags = requirementTags(catalogue, draft.required_before);
  const unchecked = tags.find((o) => o.tag === draft.required_before && !o.resolvable);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="lg"
      testId="position-dialog"
      title={
        position
          ? t('staffing.position.edit', { defaultValue: 'Edit position' })
          : t('staffing.position.add', { defaultValue: 'Add position' })
      }
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried && problem ? errorText(labels.t, problem) : null)}
          onClose={onClose}
          onSave={save}
          saveLabel={t('common.save', { defaultValue: 'Save' })}
          testId="position-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.position.phase', { defaultValue: 'Phase' })} htmlFor="position-phase">
          <select id="position-phase" className={FIELD_CLASS} value={draft.phase} onChange={(e) => set('phase', e.target.value as Phase)}>
            {phases.map((ph) => (
              <option key={ph} value={ph}>
                {vocab(t, PHASE, ph)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.position.role', { defaultValue: 'Role' })} htmlFor="position-role">
          <select
            id="position-role"
            className={FIELD_CLASS}
            value={draft.role_code}
            onChange={(e) => chooseRole(e.target.value)}
            data-testid="position-role"
          >
            {roles.map((r) => (
              <option key={r.code} value={r.code}>
                {catalogueName(labels, catalogue, 'role', r.code)}
              </option>
            ))}
            <option value={catalogue.custom_role_code}>{t('staffing.position.custom_role', { defaultValue: 'Another role' })}</option>
          </select>
        </WideModalField>
        {draft.role_code === catalogue.custom_role_code && (
          <WideModalField label={t('staffing.position.custom_label', { defaultValue: 'Custom role name' })} required htmlFor="position-custom">
            <input
              id="position-custom"
              className={FIELD_CLASS}
              value={draft.custom_label}
              onChange={(e) => set('custom_label', e.target.value)}
              data-testid="position-custom-label"
            />
          </WideModalField>
        )}
        <WideModalField label={t('staffing.position.organisation', { defaultValue: 'Organisation' })} htmlFor="position-organisation">
          <select
            id="position-organisation"
            className={FIELD_CLASS}
            value={draft.organisation}
            onChange={(e) => set('organisation', e.target.value)}
          >
            {catalogue.organisations.map((o) => (
              <option key={o.code} value={o.code}>
                {catalogueName(labels, catalogue, 'organisation', o.code)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('staffing.position.title', { defaultValue: 'Title' })}
          hint={t('staffing.position.title_hint', { defaultValue: 'Optional. Shown instead of the role name.' })}
          htmlFor="position-title"
        >
          <input id="position-title" className={FIELD_CLASS} value={draft.title} onChange={(e) => set('title', e.target.value)} />
        </WideModalField>
        <WideModalField
          label={t('staffing.position.fte', { defaultValue: 'FTE' })}
          hint={t('staffing.position.fte_hint', { defaultValue: 'Share of a full-time job, from 0.1 to 1.' })}
          htmlFor="position-fte"
        >
          <input
            id="position-fte"
            inputMode="decimal"
            className={FIELD_CLASS}
            value={draft.fte}
            onChange={(e) => set('fte', e.target.value)}
            data-testid="position-fte"
          />
        </WideModalField>
        <WideModalField label={t('staffing.position.headcount', { defaultValue: 'Headcount' })} htmlFor="position-headcount">
          <input
            id="position-headcount"
            inputMode="numeric"
            className={FIELD_CLASS}
            value={draft.headcount}
            onChange={(e) => set('headcount', e.target.value)}
          />
        </WideModalField>
        <WideModalField label={t('staffing.position.entry_date', { defaultValue: 'Start' })} htmlFor="position-entry">
          <input id="position-entry" type="date" className={FIELD_CLASS} value={draft.entry_date} onChange={(e) => set('entry_date', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.position.exit_date', { defaultValue: 'End' })} htmlFor="position-exit">
          <input id="position-exit" type="date" className={FIELD_CLASS} value={draft.exit_date} onChange={(e) => set('exit_date', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.position.recruiting_channel', { defaultValue: 'Recruiting channel' })} htmlFor="position-channel">
          <select
            id="position-channel"
            className={FIELD_CLASS}
            value={draft.recruiting_channel}
            onChange={(e) => set('recruiting_channel', e.target.value as RecruitingChannel | '')}
          >
            <option value="">{t('staffing.not_set', { defaultValue: 'Not set' })}</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {vocab(t, RECRUITING_CHANNEL, c)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('staffing.position.owner', { defaultValue: 'Line manager' })}
          hint={t('staffing.position.owner_hint', { defaultValue: 'May open the personnel files of the people on this position.' })}
        >
          {mayOwner.allowed ? (
            <ProjectPeopleSelect
              projectId={projectId}
              value={draft.owner_user_id}
              onChange={(userId) => set('owner_user_id', userId)}
              placeholder={t('staffing.position.owner', { defaultValue: 'Line manager' })}
            />
          ) : (
            <p className="text-sm text-content-secondary" data-testid="owner-locked">
              {whyNot(labels.t, mayOwner)}
            </p>
          )}
        </WideModalField>
        <WideModalField span={2}>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-content-primary">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.key_role}
                disabled={!gate.allowed}
                onChange={(e) => set('key_role', e.target.checked)}
                data-testid="position-key-role"
              />
              {t('staffing.position.key_role', { defaultValue: 'Key role' })}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.handover_role}
                disabled={!gate.allowed}
                onChange={(e) => set('handover_role', e.target.checked)}
              />
              {t('staffing.position.handover_role', { defaultValue: 'Needs handover' })}
            </label>
          </div>
          {!gate.allowed && (
            <p className="mt-1 text-xs text-content-tertiary" data-testid="gate-fields-locked">
              {whyNot(labels.t, gate)}
            </p>
          )}
        </WideModalField>
        {tags.length > 0 && (draft.key_role || draft.required_before) && (
          <WideModalField
            label={t('staffing.position.required_before', { defaultValue: 'Needed before' })}
            hint={t('staffing.position.required_before_hint', {
              defaultValue: 'The project step that must not start while this key role is vacant.',
            })}
            span={2}
            htmlFor="position-required-before"
          >
            <select
              id="position-required-before"
              className={FIELD_CLASS}
              value={draft.required_before}
              disabled={!gate.allowed}
              onChange={(e) => set('required_before', e.target.value)}
              data-testid="position-required-before"
            >
              <option value="">{t('staffing.not_set', { defaultValue: 'Not set' })}</option>
              {tags.map((o) => (
                <option key={o.tag} value={o.tag}>
                  {humanizeCode(o.tag)}
                </option>
              ))}
            </select>
            {unchecked && (
              <p className="mt-1 text-xs text-semantic-warning" role="status" data-testid="required-before-unchecked">
                {t('staffing.position.required_before_unchecked', {
                  defaultValue: 'No gate of this project checks this step, so nothing will ask for the role to be filled.',
                })}
              </p>
            )}
          </WideModalField>
        )}
        <WideModalField label={t('staffing.position.notes', { defaultValue: 'Notes' })} span={2} htmlFor="position-notes">
          <textarea id="position-notes" rows={2} className={FIELD_CLASS} value={draft.notes} onChange={(e) => set('notes', e.target.value)} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/** One position per chosen catalogue role of a phase. Roles already planned in that phase are not offered. */
export function FromCatalogueDialog({
  open,
  projectId,
  labels,
  catalogue,
  positions,
  phases,
  defaultPhase,
  onClose,
  onDone,
}: DialogBase & { catalogue: StaffingCatalogue; positions: Position[]; phases: Phase[]; defaultPhase: Phase }) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>(defaultPhase);
  const [entry, setEntry] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  const offered = useMemo(() => rolesNotPlanned(catalogue, positions, phase), [catalogue, positions, phase]);
  useEffect(() => {
    if (open) {
      setPhase(defaultPhase);
      setEntry('');
      reset();
    }
  }, [open, defaultPhase, reset]);
  // Every offered role starts ticked: the usual case is "give me the whole phase".
  useEffect(() => {
    if (open) setPicked(new Set(offered.map((r) => r.code)));
  }, [open, offered]);

  const toggle = (code: string) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="from-catalogue-dialog"
      title={t('staffing.position.add_from_catalogue', { defaultValue: 'Add roles from catalogue' })}
      subtitle={t('staffing.position.add_from_catalogue_hint', {
        defaultValue: 'Each ticked role becomes one position with the FTE the catalogue suggests. You can change it afterwards.',
      })}
      footer={
        <Footer
          busy={busy}
          error={error}
          onClose={onClose}
          disabled={picked.size === 0}
          onSave={() =>
            void run(() =>
              createPositionsFromCatalogue(projectId, { phase, role_codes: [...picked], entry_date: entry || null }),
            )
          }
          saveLabel={t('staffing.position.add_count', { defaultValue: 'Add {{count}} positions', count: picked.size })}
          testId="from-catalogue-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.position.phase', { defaultValue: 'Phase' })} htmlFor="from-catalogue-phase">
          <select id="from-catalogue-phase" className={FIELD_CLASS} value={phase} onChange={(e) => setPhase(e.target.value as Phase)}>
            {phases.map((ph) => (
              <option key={ph} value={ph}>
                {vocab(t, PHASE, ph)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.position.entry_date', { defaultValue: 'Start' })} htmlFor="from-catalogue-entry">
          <input id="from-catalogue-entry" type="date" className={FIELD_CLASS} value={entry} onChange={(e) => setEntry(e.target.value)} />
        </WideModalField>
      </WideModalSection>
      {offered.length === 0 ? (
        <p className="mt-3 text-sm text-content-secondary" data-testid="from-catalogue-none">
          {t('staffing.position.all_roles_planned', { defaultValue: 'Every catalogue role of this phase is already planned.' })}
        </p>
      ) : (
        <ul className="mt-3 grid gap-1 sm:grid-cols-2" data-testid="from-catalogue-roles">
          {offered.map((r) => (
            <li key={r.code}>
              <label className="flex items-start gap-2 rounded-md px-2 py-1 text-sm text-content-primary hover:bg-surface-secondary">
                <input type="checkbox" className="mt-0.5" checked={picked.has(r.code)} onChange={() => toggle(r.code)} />
                <span>
                  {catalogueName(labels, catalogue, 'role', r.code)}
                  <span className="block text-xs text-content-tertiary">
                    {catalogueName(labels, catalogue, 'organisation', r.organisation)}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </WideModal>
  );
}

/** Put a person from the project team on a position. The assignment starts as proposed and is confirmed separately. */
export function FillDialog({
  open,
  projectId,
  labels,
  catalogue,
  position,
  onClose,
  onDone,
}: DialogBase & { catalogue: StaffingCatalogue | null; position: Position | null }) {
  const { t } = useTranslation();
  const rosterQ = useRoster(projectId, open);
  const [member, setMember] = useState('');
  const [share, setShare] = useState('1');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setMember('');
      setShare(position?.fte ?? '1');
      setFrom(position?.entry_date ?? '');
      setTo('');
      setTried(false);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, position?.id]);

  const problem = !member || !from ? 'required' : fteProblem(share) ?? datesProblem(from, to);
  const problemText =
    problem === 'required'
      ? t('staffing.fill.required', { defaultValue: 'Choose a person and a start date.' })
      : problem
        ? errorText(labels.t, problem)
        : null;
  const roster = (rosterQ.data ?? []).filter((m) => m.is_active !== false);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="fill-dialog"
      title={t('staffing.fill.add', { defaultValue: 'Assign person' })}
      subtitle={position ? positionName(labels, catalogue, position) : undefined}
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried ? problemText : null)}
          onClose={onClose}
          onSave={() => {
            if (problem || !position) {
              setTried(true);
              return;
            }
            void run(() =>
              createFill(projectId, position.id, {
                roster_member_id: member,
                fte_share: decimalString(share) ?? '1',
                from_date: from,
                to_date: to || null,
              }),
            );
          }}
          saveLabel={t('staffing.fill.add', { defaultValue: 'Assign person' })}
          testId="fill-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('staffing.fill.person', { defaultValue: 'Person' })}
          hint={t('staffing.fill.person_hint', { defaultValue: 'People come from the project team. Add somebody there first if they are missing.' })}
          span={2}
          htmlFor="fill-person"
        >
          <select id="fill-person" className={FIELD_CLASS} value={member} onChange={(e) => setMember(e.target.value)} data-testid="fill-person">
            <option value="">{t('staffing.choose', { defaultValue: 'Choose' })}</option>
            {roster.map((m) => (
              <option key={m.id} value={m.id}>
                {personLabel(labels.t, m.display_name)}
              </option>
            ))}
          </select>
          <PeoplePickerNote failed={rosterQ.isError} empty={rosterQ.isSuccess && roster.length === 0} onRetry={() => void rosterQ.refetch()} />
        </WideModalField>
        <WideModalField label={t('staffing.fill.share', { defaultValue: 'FTE share' })} htmlFor="fill-share">
          <input id="fill-share" inputMode="decimal" className={FIELD_CLASS} value={share} onChange={(e) => setShare(e.target.value)} />
        </WideModalField>
        <span className="hidden sm:block" />
        <WideModalField label={t('staffing.fill.from', { defaultValue: 'From' })} required htmlFor="fill-from">
          <input id="fill-from" type="date" className={FIELD_CLASS} value={from} onChange={(e) => setFrom(e.target.value)} data-testid="fill-from" />
        </WideModalField>
        <WideModalField label={t('staffing.fill.to', { defaultValue: 'To' })} htmlFor="fill-to">
          <input id="fill-to" type="date" className={FIELD_CLASS} value={to} onChange={(e) => setTo(e.target.value)} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/** Plan who hands over to which position, how long the two overlap and what is handed over. */
export function HandoverDialog({
  open,
  projectId,
  labels,
  catalogue,
  positions,
  handover,
  onClose,
  onDone,
}: DialogBase & { catalogue: StaffingCatalogue | null; positions: Position[]; handover: Handover | null }) {
  const { t } = useTranslation();
  const [fromFill, setFromFill] = useState('');
  const [toPosition, setToPosition] = useState('');
  const [overlap, setOverlap] = useState('14');
  const [scope, setScope] = useState('');
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setFromFill(handover?.from_fill_id ?? '');
      setToPosition(handover?.to_position_id ?? '');
      setOverlap(handover ? String(handover.overlap_days) : '14');
      setScope(handover?.scope ?? '');
      setTried(false);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, handover?.id]);

  const people = liveFills(positions);
  const targets = positions.filter((p) => p.status !== 'cancelled');
  const invalid = !fromFill || !toPosition || !/^\d+$/.test(overlap.trim());

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="handover-dialog"
      title={handover ? t('staffing.handover.edit', { defaultValue: 'Edit handover' }) : t('staffing.handover.add', { defaultValue: 'Plan handover' })}
      footer={
        <Footer
          busy={busy}
          error={
            error ??
            (tried && invalid
              ? t('staffing.handover.required', { defaultValue: 'Choose who hands over, the position that takes over and the overlap in days.' })
              : null)
          }
          onClose={onClose}
          onSave={() => {
            if (invalid) {
              setTried(true);
              return;
            }
            void run(() =>
              handover
                ? updateHandover(projectId, handover.id, { overlap_days: Number(overlap), scope: scope.trim() })
                : createHandover(projectId, {
                    from_fill_id: fromFill,
                    to_position_id: toPosition,
                    overlap_days: Number(overlap),
                    scope: scope.trim(),
                  }),
            );
          }}
          saveLabel={handover ? t('common.save', { defaultValue: 'Save' }) : t('staffing.handover.add', { defaultValue: 'Plan handover' })}
          testId="handover-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.handover.from', { defaultValue: 'From' })} required htmlFor="handover-from">
          <select id="handover-from" className={FIELD_CLASS} disabled={!!handover} value={fromFill} onChange={(e) => setFromFill(e.target.value)}>
            <option value="">{t('staffing.choose', { defaultValue: 'Choose' })}</option>
            {people.map(({ position, fill }) => (
              <option key={fill.id} value={fill.id}>
                {t('staffing.handover.person_on', {
                  defaultValue: '{{person}}, {{position}}',
                  person: personLabel(labels.t, fill.name),
                  position: positionName(labels, catalogue, position),
                })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.handover.to', { defaultValue: 'To position' })} required htmlFor="handover-to">
          <select id="handover-to" className={FIELD_CLASS} disabled={!!handover} value={toPosition} onChange={(e) => setToPosition(e.target.value)}>
            <option value="">{t('staffing.choose', { defaultValue: 'Choose' })}</option>
            {targets.map((p) => (
              <option key={p.id} value={p.id}>
                {positionName(labels, catalogue, p)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.handover.overlap_days', { defaultValue: 'Overlap (days)' })} htmlFor="handover-overlap">
          <input id="handover-overlap" inputMode="numeric" className={FIELD_CLASS} value={overlap} onChange={(e) => setOverlap(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.handover.scope', { defaultValue: 'What is handed over' })} span={2} htmlFor="handover-scope">
          <textarea id="handover-scope" rows={3} className={FIELD_CLASS} value={scope} onChange={(e) => setScope(e.target.value)} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
