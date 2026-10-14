// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Responsibilities tab: every role the catalogue names, whether the facts make it compulsory, who carries
// it and since when. The safety and health coordinator of the design stage and of the execution stage are
// two roles of the catalogue; a national title is shown beside the neutral name.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { fmtList } from '@/shared/lib/formatters';
import { Input } from '@/shared/ui/Input';
import { fmtDate } from '@/shared/lib/formatters';

import { createRole, deleteRole, localToday, patchRole, type Catalogue, type CatRole, type Duties, type Role } from './api';
import type { HseWrite } from './hooks';
import { ExportButtons } from './ExportButtons';
import { RemoveConfirm, type RemoveTarget } from './RemoveConfirm';
import { dutyWord, labelOf } from './labels';

interface Props {
  projectId: string;
  roles: Role[];
  catalogue: Catalogue;
  duties: Duties | null;
  write: HseWrite;
  canEdit: boolean;
}

/** Whether a role is compulsory under the facts: true, false or undecided. */
function requiredNow(kind: CatRole, duties: Duties | null): boolean | null {
  switch (kind.required_when) {
    case null:
      return false;
    case 'always':
      return true;
    case 'multiple_employers':
      return duties ? duties.coordinator : null;
    case 'plan_required':
      return duties ? duties.plan : null;
    case 'advance_notice':
      return duties ? duties.advance_notice : null;
    case 'hazardous_work':
      return duties ? duties.hazardous_work : null;
    default:
      return null;
  }
}

function AddRole({ projectId, kind, write }: { projectId: string; kind: CatRole; write: HseWrite }) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [organisation, setOrganisation] = useState('');
  const [qualification, setQualification] = useState('');
  const [valid, setValid] = useState('');
  const [day, setDay] = useState(localToday());
  const [status, setStatus] = useState<'proposed' | 'appointed'>('appointed');
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2" data-testid={`add-role-${kind.code}`}>
      <Input label={t('hseFrame.role.person', { defaultValue: 'Person' })} value={name} onChange={(e) => setName(e.target.value)} data-testid="role-person" />
      <Input label={t('hseFrame.role.organisation', { defaultValue: 'Organisation' })} value={organisation} onChange={(e) => setOrganisation(e.target.value)} />
      {kind.qualification_required && (
        <>
          <Input label={t('hseFrame.role.qualification', { defaultValue: 'Qualification' })} value={qualification} onChange={(e) => setQualification(e.target.value)} />
          <Input label={t('hseFrame.role.valid_until', { defaultValue: 'Valid until' })} type="date" value={valid} onChange={(e) => setValid(e.target.value)} />
        </>
      )}
      <label className="flex flex-col gap-1 text-xs text-content-secondary">
        {t('hseFrame.role.status', { defaultValue: 'Status' })}
        <select className="h-10 rounded-lg border border-border bg-surface-primary px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="appointed">{t('hseFrame.role_status.appointed', { defaultValue: 'Appointed' })}</option>
          <option value="proposed">{t('hseFrame.role_status.proposed', { defaultValue: 'Proposed' })}</option>
        </select>
      </label>
      {status === 'appointed' && (
        <Input label={t('hseFrame.role.appointed_on', { defaultValue: 'Appointed on' })} type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      )}
      <Button
        size="sm"
        disabled={write.pending || !name.trim()}
        onClick={() =>
          write.send(
            () =>
              createRole(projectId, {
                role_code: kind.code,
                person_name: name.trim(),
                organisation,
                status,
                appointed_on: status === 'appointed' ? day : null,
                qualification,
                qualification_valid_until: valid || null,
              }),
            () => {
              setName('');
              setOrganisation('');
              setQualification('');
              setValid('');
            },
          )
        }
        data-testid="role-add"
      >
        {t('hseFrame.role.add', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

export function RolesPanel({ projectId, roles, catalogue, duties, write, canEdit }: Props) {
  const { t, i18n } = useTranslation();
  const [removing, setRemoving] = useState<RemoveTarget | null>(null);
  return (
    <div className="space-y-4" data-testid="roles-panel">
      <div className="flex justify-end">
        <ExportButtons projectId={projectId} what="roles" />
      </div>
      {catalogue.role_kinds.map((kind) => {
        const mine = roles.filter((r) => r.role_code === kind.code);
        const word = dutyWord(requiredNow(kind, duties));
        const held = mine.some((r) => r.in_force);
        return (
          <section key={kind.code} className="rounded-lg border border-border-light p-3" data-testid={`role-${kind.code}`} data-required={word} data-held={held}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-content-primary">{labelOf(kind, i18n.language)}</h2>
                <p className="text-xs text-content-secondary">{[kind.national_name, kind.legal_basis].filter(Boolean).join(' | ')}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={word === 'yes' ? 'warning' : 'neutral'}>
                  {t(`hseFrame.role_required.${word}`, {
                    defaultValue: word === 'yes' ? 'Required' : word === 'no' ? 'Optional' : 'Undecided',
                  })}
                </Badge>
                <Badge variant={held ? 'success' : word === 'yes' ? 'error' : 'neutral'} dot>
                  {held ? t('hseFrame.role.held', { defaultValue: 'Filled' }) : t('hseFrame.role.vacant', { defaultValue: 'Vacant' })}
                </Badge>
              </div>
            </div>
            {mine.length > 0 && (
              <ul className="mt-2 space-y-1">
                {mine.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 text-sm" data-testid={`assignment-${r.id}`} data-status={r.status}>
                    <span className="text-content-primary">
                      {fmtList([r.person_name, r.organisation]) || t('hseFrame.role.unnamed', { defaultValue: 'No person named' })}
                      <span className="ml-2 text-xs text-content-secondary">
                        {[
                          t(`hseFrame.role_status.${r.status}`, { defaultValue: r.status }),
                          r.appointed_on && fmtDate(r.appointed_on),
                          r.qualification,
                          r.qualification_valid_until && t('hseFrame.role.valid_until_short', { defaultValue: 'valid until {{date}}', date: fmtDate(r.qualification_valid_until) }),
                        ]
                          .filter(Boolean)
                          .join(' | ')}
                      </span>
                    </span>
                    {canEdit && (
                      <span className="flex gap-1">
                        {r.status === 'proposed' && (
                          <Button size="sm" variant="secondary" disabled={write.pending || !(r.person_name || r.person_user_id)} onClick={() => write.send(() => patchRole(projectId, r.id, { status: 'appointed', appointed_on: localToday() }))}>
                            {t('hseFrame.role.appoint', { defaultValue: 'Appoint' })}
                          </Button>
                        )}
                        {r.status === 'appointed' && (
                          <Button size="sm" variant="ghost" disabled={write.pending} onClick={() => write.send(() => patchRole(projectId, r.id, { status: 'ended', ends_on: localToday() }))}>
                            {t('hseFrame.role.end', { defaultValue: 'End' })}
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" disabled={write.pending} onClick={() => setRemoving({ name: [kind.national_name || labelOf(kind, i18n.language), r.person_name].filter(Boolean).join(', '), run: () => deleteRole(projectId, r.id) })}>
                          {t('common.delete', { defaultValue: 'Delete' })}
                        </Button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {canEdit && <AddRole projectId={projectId} kind={kind} write={write} />}
          </section>
        );
      })}
      <RemoveConfirm target={removing} write={write} onClose={() => setRemoving(null)} />
    </div>
  );
}
