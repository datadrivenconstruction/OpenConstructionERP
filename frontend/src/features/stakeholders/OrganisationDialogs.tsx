// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The two dialogs of the project organisation: who holds a role (with a
// deputy and the dates the appointment is valid), and a governance body with
// its members and the quorum it needs to decide.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';

import type { RosterMember } from '@/features/teams/api';
import { Button } from '@/shared/ui/Button';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import {
  createBody,
  putBodyMembers,
  putRoleHolders,
  updateBody,
  type BodyInput,
  type FrameworkRole,
  type GovernanceBody,
  type HolderInput,
  type MemberInput,
  type OrganisationWriteNotes,
  type QuorumKind,
  type RoleHolder,
} from './api';
import { ConflictAcknowledge } from './ConflictAcknowledge';
import { FIELD_CLASS, RefusalBox, useWrite } from './StakeholderBits';
import { QUORUM, itemName, vocab } from './labels';
import type { Screen } from './screen';

let rowSeq = 0;
const nextRow = () => {
  rowSeq += 1;
  return `r${rowSeq}`;
};

interface HolderDraft extends HolderInput {
  rowId: string;
  /** The name of a contact holder, known only for rows that came from the server. */
  contactName: string;
}

export interface RoleHoldersDialogProps {
  screen: Screen;
  role: Pick<FrameworkRole, 'code' | 'name_key' | 'holder_kind' | 'multi'>;
  holders: RoleHolder[];
  roster: RosterMember[];
  onClose: () => void;
  onSaved: (notes: OrganisationWriteNotes) => void;
}

export function RoleHoldersDialog({ screen, role, holders, roster, onClose, onSaved }: RoleHoldersDialogProps) {
  const { t } = useTranslation();
  const { projectId, labels } = screen;
  const blank = (): HolderDraft => ({
    rowId: nextRow(),
    roster_member_id: null,
    holder_contact_id: null,
    deputy_roster_member_id: null,
    valid_from: null,
    valid_to: null,
    conflict_rationale: '',
    contactName: '',
  });
  const [rows, setRows] = useState<HolderDraft[]>(() =>
    holders.length > 0
      ? holders.map((h) => ({
          rowId: nextRow(),
          roster_member_id: h.roster_member_id,
          holder_contact_id: h.holder_contact_id,
          deputy_roster_member_id: h.deputy_roster_member_id,
          valid_from: h.valid_from,
          valid_to: h.valid_to,
          conflict_rationale: h.conflict_rationale,
          contactName: h.holder_contact_id ? (h.holder_name ?? '') : '',
        }))
      : [blank()],
  );
  const patch = (rowId: string, change: Partial<HolderDraft>) =>
    setRows((all) => all.map((r) => (r.rowId === rowId ? { ...r, ...change } : r)));

  const write = useWrite(
    () =>
      putRoleHolders(
        projectId,
        role.code,
        rows.map(({ rowId: _rowId, contactName: _contactName, ...holder }) => holder),
        holders[0]?.custom_label ?? '',
      ),
    onSaved,
  );

  // Every row names exactly one holder: a person on the project or a contact.
  const ready = rows.every((r) => !!r.roster_member_id !== !!r.holder_contact_id);
  // Somebody who has left is not offered, but stays selectable where they are already named.
  const people = roster.filter(
    (m) => m.is_active || rows.some((r) => r.roster_member_id === m.id || r.deputy_roster_member_id === m.id),
  );
  const personOption = (m: RosterMember) => (
    <option key={m.id} value={m.id}>
      {m.company_name
        ? t('stakeholders.ui.role.person_of_company', {
            defaultValue: '{{name}} ({{company}})',
            name: m.display_name,
            company: m.company_name,
          })
        : m.display_name}
    </option>
  );

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="xl"
      testId="role-holders-dialog"
      title={t('stakeholders.ui.role.dialog_title', { defaultValue: 'Who holds this role: {{role}}', role: itemName(labels, role) })}
      subtitle={t('stakeholders.ui.role.dialog_subtitle', {
        defaultValue: 'Name the holder and, if there is one, the deputy. Dates are optional: leave them empty for an open-ended appointment.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!ready} onClick={() => write.run(undefined)} data-testid="role-holders-save">
            {t('stakeholders.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox refusal={write.refusal} />
        {rows.length === 0 && (
          <p className="text-sm text-content-secondary" data-testid="role-holders-none">
            {t('stakeholders.ui.role.no_rows', { defaultValue: 'Saving now leaves the role vacant.' })}
          </p>
        )}
        {rows.map((r) => (
          <div key={r.rowId} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="role-holder-row">
            <WideModalSection columns={3}>
              {r.holder_contact_id || (role.holder_kind === 'organisation' && !r.roster_member_id) ? (
                <WideModalField
                  label={t('stakeholders.ui.role.holder_contact', { defaultValue: 'Holder (organisation or contact)' })}
                  span={2}
                >
                  <ContactSearchInput
                    value={r.holder_contact_id ?? ''}
                    displayValue={r.contactName}
                    onChange={(id, name) => patch(r.rowId, { holder_contact_id: id || null, contactName: name, roster_member_id: null })}
                    showBrowse={false}
                  />
                </WideModalField>
              ) : (
                <WideModalField label={t('stakeholders.ui.role.holder', { defaultValue: 'Holder' })} span={2} htmlFor={`holder-${r.rowId}`}>
                  <select
                    id={`holder-${r.rowId}`}
                    className={FIELD_CLASS}
                    value={r.roster_member_id ?? ''}
                    onChange={(e) => patch(r.rowId, { roster_member_id: e.target.value || null, holder_contact_id: null })}
                    data-testid="role-holder-select"
                  >
                    <option value="">{t('stakeholders.ui.choose', { defaultValue: 'Choose' })}</option>
                    {people.map(personOption)}
                  </select>
                </WideModalField>
              )}
              <WideModalField label={t('stakeholders.ui.role.deputy', { defaultValue: 'Deputy' })} htmlFor={`deputy-${r.rowId}`}>
                <select
                  id={`deputy-${r.rowId}`}
                  className={FIELD_CLASS}
                  value={r.deputy_roster_member_id ?? ''}
                  onChange={(e) => patch(r.rowId, { deputy_roster_member_id: e.target.value || null })}
                >
                  <option value="">{t('stakeholders.ui.role.no_deputy', { defaultValue: 'No deputy' })}</option>
                  {people.map(personOption)}
                </select>
              </WideModalField>
              <WideModalField label={t('stakeholders.ui.valid_from', { defaultValue: 'Valid from' })} htmlFor={`from-${r.rowId}`}>
                <input
                  id={`from-${r.rowId}`}
                  type="date"
                  className={FIELD_CLASS}
                  value={r.valid_from ?? ''}
                  onChange={(e) => patch(r.rowId, { valid_from: e.target.value || null })}
                />
              </WideModalField>
              <WideModalField label={t('stakeholders.ui.valid_to', { defaultValue: 'Valid to' })} htmlFor={`to-${r.rowId}`}>
                <input
                  id={`to-${r.rowId}`}
                  type="date"
                  className={FIELD_CLASS}
                  value={r.valid_to ?? ''}
                  min={r.valid_from ?? undefined}
                  onChange={(e) => patch(r.rowId, { valid_to: e.target.value || null })}
                />
              </WideModalField>
              <div className="flex items-end justify-end">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={13} />}
                  onClick={() => setRows((all) => all.filter((x) => x.rowId !== r.rowId))}
                  data-testid="role-holder-remove"
                >
                  {t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
                </Button>
              </div>
              <WideModalField
                label={t('stakeholders.ui.role.conflict_rationale', { defaultValue: 'If this person also proposes or co-signs what the role decides: why that is accepted' })}
                span={3}
                htmlFor={`conflict-${r.rowId}`}
              >
                <input
                  id={`conflict-${r.rowId}`}
                  className={FIELD_CLASS}
                  value={r.conflict_rationale}
                  onChange={(e) => patch(r.rowId, { conflict_rationale: e.target.value })}
                />
              </WideModalField>
            </WideModalSection>
          </div>
        ))}
        <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={() => setRows((all) => [...all, blank()])} data-testid="role-holder-add">
          {role.multi || rows.length === 0
            ? t('stakeholders.ui.role.add_holder', { defaultValue: 'Add a holder' })
            : t('stakeholders.ui.role.add_successor', { defaultValue: 'Add a successor for a later period' })}
        </Button>
      </div>
    </WideModal>
  );
}

interface MemberDraft extends MemberInput {
  rowId: string;
}

export interface BodyDialogProps {
  screen: Screen;
  body: GovernanceBody | null;
  roles: Array<Pick<FrameworkRole, 'code' | 'name_key'>>;
  onClose: () => void;
  onSaved: () => void;
}

export function BodyDialog({ screen, body, roles, onClose, onSaved }: BodyDialogProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName } = screen;
  const fw = settings.framework;
  // A body created by a first attempt whose member list was then refused: the retry updates it.
  const [savedId, setSavedId] = useState<string | null>(body?.id ?? null);
  const [draft, setDraft] = useState({
    code: body?.code ?? '',
    name: body?.name ?? '',
    body_type: body?.body_type ?? fw.body_types[0]?.code ?? '',
    chair: body?.chair_role_code ?? '',
    quorum_kind: (body?.quorum_kind ?? 'majority') as QuorumKind,
    quorum_min: body?.quorum_min != null ? String(body.quorum_min) : '',
    level: String(body?.decision_level ?? fw.body_types[0]?.default_decision_level ?? 1),
  });
  const [members, setMembers] = useState<MemberDraft[]>(() =>
    (body?.members ?? []).map((m) => ({
      rowId: nextRow(),
      role_code: m.role_code,
      user_id: m.user_id,
      contact_id: m.contact_id,
      voting: m.voting,
      valid_from: m.valid_from,
      valid_to: m.valid_to,
    })),
  );
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const patch = (rowId: string, change: Partial<MemberDraft>) =>
    setMembers((all) => all.map((m) => (m.rowId === rowId ? { ...m, ...change } : m)));

  const write = useWrite(async () => {
    const fields: BodyInput = {
      name: draft.name.trim(),
      body_type: draft.body_type,
      chair_role_code: draft.chair || null,
      quorum_kind: draft.quorum_kind,
      quorum_min: draft.quorum_kind === 'min_members' && draft.quorum_min ? Number(draft.quorum_min) : null,
      decision_level: Number(draft.level),
    };
    let id = savedId;
    if (id) await updateBody(projectId, id, fields);
    else {
      id = (await createBody(projectId, { ...fields, code: draft.code.trim() })).id;
      setSavedId(id);
    }
    return putBodyMembers(
      projectId,
      id,
      members.map(({ rowId: _rowId, ...member }) => member),
    );
  }, onSaved);

  const codeOk = !!savedId || /^[a-z0-9][a-z0-9_]*$/.test(draft.code.trim());
  const membersOk = members.every((m) => [m.role_code, m.user_id, m.contact_id].filter(Boolean).length === 1);
  const quorumOk = draft.quorum_kind !== 'min_members' || Number(draft.quorum_min) >= 1;
  const levelOk = Number.isInteger(Number(draft.level)) && Number(draft.level) >= 1 && Number(draft.level) <= 20;
  const ready = !!draft.name.trim() && !!draft.body_type && codeOk && membersOk && quorumOk && levelOk;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={write.busy}
      size="xl"
      testId="body-dialog"
      title={
        body
          ? t('stakeholders.ui.body.edit_title', { defaultValue: 'Edit governance body' })
          : t('stakeholders.ui.body.add_title', { defaultValue: 'Add a governance body' })
      }
      subtitle={t('stakeholders.ui.body.dialog_subtitle', {
        defaultValue: 'A group that decides together, such as a steering committee. It can hold a letter in the mandate matrix like a role does.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={write.busy}>
            {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={write.busy} disabled={!ready} onClick={() => write.run(undefined)} data-testid="body-save">
            {t('stakeholders.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {write.refusal?.code === 'conflict_not_acknowledged' ? (
          <ConflictAcknowledge screen={screen} refusal={write.refusal} onAcknowledged={() => write.run(undefined)} />
        ) : (
          <RefusalBox refusal={write.refusal} />
        )}
        <WideModalSection columns={3}>
          <WideModalField label={t('stakeholders.ui.body.name', { defaultValue: 'Name' })} required span={2} htmlFor="body-name">
            <input id="body-name" className={FIELD_CLASS} value={draft.name} maxLength={255} onChange={(e) => set('name', e.target.value)} />
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.body.code', { defaultValue: 'Short code' })}
            required
            hint={t('stakeholders.ui.body.code_hint', {
              defaultValue: 'Small letters, digits and underscores. It cannot be changed later.',
            })}
            error={draft.code && !codeOk ? t('stakeholders.ui.body.code_invalid', { defaultValue: 'Use only small letters, digits and underscores.' }) : undefined}
            htmlFor="body-code"
          >
            <input
              id="body-code"
              className={FIELD_CLASS}
              value={draft.code}
              maxLength={64}
              disabled={!!savedId}
              onChange={(e) => set('code', e.target.value)}
            />
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.body.type', { defaultValue: 'Kind of body' })} htmlFor="body-type">
            <select
              id="body-type"
              className={FIELD_CLASS}
              value={draft.body_type}
              onChange={(e) => {
                const type = fw.body_types.find((b) => b.code === e.target.value);
                // A new body takes the level its kind usually sits on; an existing one keeps its own.
                setDraft((d) => ({
                  ...d,
                  body_type: e.target.value,
                  level: body || !type ? d.level : String(type.default_decision_level),
                }));
              }}
            >
              {fw.body_types.map((b) => (
                <option key={b.code} value={b.code}>
                  {itemName(labels, b)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.body.chair', { defaultValue: 'Chaired by the role' })} htmlFor="body-chair">
            <select id="body-chair" className={FIELD_CLASS} value={draft.chair} onChange={(e) => set('chair', e.target.value)}>
              <option value="">{t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}</option>
              {roles.map((r) => (
                <option key={r.code} value={r.code}>
                  {itemName(labels, r)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('stakeholders.ui.body.quorum', { defaultValue: 'To decide, it needs' })} htmlFor="body-quorum">
            <select
              id="body-quorum"
              className={FIELD_CLASS}
              value={draft.quorum_kind}
              onChange={(e) => set('quorum_kind', e.target.value as QuorumKind)}
            >
              {(Object.keys(QUORUM) as QuorumKind[]).map((q) => (
                <option key={q} value={q}>
                  {vocab(t, QUORUM, q)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('stakeholders.ui.body.level', { defaultValue: 'Escalation level' })}
            hint={t('stakeholders.ui.body.level_hint', {
              defaultValue: '1 is the first level. A body with a higher number takes what the level below could not settle.',
            })}
            htmlFor="body-level"
          >
            <input
              id="body-level"
              type="number"
              min={1}
              max={20}
              className={FIELD_CLASS}
              value={draft.level}
              onChange={(e) => set('level', e.target.value)}
            />
          </WideModalField>
          {draft.quorum_kind === 'min_members' && (
            <WideModalField label={t('stakeholders.ui.body.quorum_min', { defaultValue: 'How many members at least' })} required htmlFor="body-quorum-min">
              <input
                id="body-quorum-min"
                type="number"
                min={1}
                max={100}
                className={FIELD_CLASS}
                value={draft.quorum_min}
                onChange={(e) => set('quorum_min', e.target.value)}
              />
            </WideModalField>
          )}
        </WideModalSection>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-content-primary">{t('stakeholders.ui.body.members', { defaultValue: 'Members' })}</h3>
          <p className="text-xs text-content-secondary">
            {t('stakeholders.ui.body.members_hint', {
              defaultValue: 'A member is either a role (whoever holds it sits on the body) or a named person.',
            })}
          </p>
          {members.map((m) => (
            <div key={m.rowId} className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-2" data-testid="body-member-row">
              {m.contact_id ? (
                <span className="flex-1 text-sm text-content-secondary">
                  {t('stakeholders.ui.body.member_contact', { defaultValue: 'External contact (kept as it is)' })}
                </span>
              ) : (
                <>
                  <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
                    {t('stakeholders.ui.body.member_role', { defaultValue: 'Role' })}
                    <select
                      className={FIELD_CLASS}
                      value={m.role_code ?? ''}
                      onChange={(e) => patch(m.rowId, { role_code: e.target.value || null, user_id: e.target.value ? null : m.user_id })}
                      data-testid="body-member-role"
                    >
                      <option value="">{t('stakeholders.ui.body.member_person_instead', { defaultValue: 'A named person instead' })}</option>
                      {roles.map((r) => (
                        <option key={r.code} value={r.code}>
                          {itemName(labels, r)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!m.role_code && (
                    <div className="min-w-[12rem] flex-1 text-xs text-content-secondary">
                      {t('stakeholders.ui.body.member_person', { defaultValue: 'Person' })}
                      <ProjectPeopleSelect
                        projectId={projectId}
                        value={m.user_id ?? ''}
                        displayValue={personName(m.user_id) ?? ''}
                        onChange={(id) => patch(m.rowId, { user_id: id || null })}
                      />
                    </div>
                  )}
                </>
              )}
              <label className="flex items-center gap-1.5 pb-1.5 text-sm text-content-primary">
                <input type="checkbox" checked={m.voting} onChange={(e) => patch(m.rowId, { voting: e.target.checked })} />
                {t('stakeholders.ui.body.member_voting', { defaultValue: 'Has a vote' })}
              </label>
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                aria-label={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
                onClick={() => setMembers((all) => all.filter((x) => x.rowId !== m.rowId))}
              />
            </div>
          ))}
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={13} />}
            onClick={() =>
              setMembers((all) => [
                ...all,
                { rowId: nextRow(), role_code: roles[0]?.code ?? null, user_id: null, contact_id: null, voting: true, valid_from: null, valid_to: null },
              ])
            }
            data-testid="body-member-add"
          >
            {t('stakeholders.ui.body.member_add', { defaultValue: 'Add a member' })}
          </Button>
        </section>
      </div>
    </WideModal>
  );
}
