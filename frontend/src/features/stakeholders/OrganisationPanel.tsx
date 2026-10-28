// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project organisation: who holds which role, which bodies decide
// together, and the mandate matrix that says who decides what. A vacant role
// is shown as vacant, never left blank, because a required role without a
// holder blocks the next gate.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Network, Pencil, Scale, Plus, Settings2, Trash2, UserCog, Users } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import { deleteBody, type FrameworkRole, type GovernanceBody, type OrganisationWriteNotes, type RoleHolder } from './api';
import { MandateMatrix, WhoDecidesLookup, columnName } from './MandateMatrix';
import { BodyDialog, RoleHoldersDialog } from './OrganisationDialogs';
import { GatedButton, SectionHead, ToneBadge, useWrite } from './StakeholderBits';
import { useBodies, useMandates, useRoles, useRoster } from './hooks';
import { QUORUM, WRITE_NOTE, itemName, nameOf, vocab } from './labels';
import type { Screen } from './screen';

type RoleDef = Pick<FrameworkRole, 'code' | 'name_key' | 'holder_kind' | 'multi' | 'required'>;

type Dialog =
  | { kind: 'role'; role: RoleDef }
  | { kind: 'body'; body: GovernanceBody | null }
  | { kind: 'delete-body'; body: GovernanceBody }
  | null;

export interface OrganisationPanelProps {
  screen: Screen;
  /** Opens the settings, where the framework that brings the roles is chosen. */
  onOpenSettings?: () => void;
}

export function OrganisationPanel({ screen, onOpenSettings }: OrganisationPanelProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName, onChanged } = screen;
  const can = settings.can.manage_organisation;
  const addToast = useToastStore((s) => s.addToast);
  const rolesQ = useRoles(projectId);
  const bodiesQ = useBodies(projectId);
  const mandatesQ = useMandates(projectId);
  const roster = useRoster(projectId);
  const [dialog, setDialog] = useState<Dialog>(null);

  /** After a write: refetch, and say what the server noted besides accepting it. */
  const saved = (notes: OrganisationWriteNotes = {}) => {
    setDialog(null);
    onChanged();
    const codes = [...(notes.warnings ?? []), ...new Set((notes.hints ?? []).map((h) => h.code))];
    for (const code of codes) addToast({ type: 'warning', title: vocab(t, WRITE_NOTE, code) });
  };
  const removeBody = useWrite((body: GovernanceBody) => deleteBody(projectId, body.id), () => saved());

  if (rolesQ.isLoading || bodiesQ.isLoading || mandatesQ.isLoading) return <SkeletonTable rows={6} columns={4} />;
  const failed = rolesQ.error ?? bodiesQ.error ?? mandatesQ.error;
  if (failed || !rolesQ.data || !mandatesQ.data) {
    return (
      <ErrorState
        title={t('stakeholders.ui.organisation.load_failed', { defaultValue: 'The project organisation could not be loaded' })}
        hint={failed ? getErrorMessage(failed) : undefined}
        onRetry={onChanged}
      />
    );
  }

  const roles = rolesQ.data;
  const bodies = bodiesQ.data ?? [];
  const holdersOf = (code: string) => roles.holders.filter((h) => h.role_code === code);
  const holderLine = (h: RoleHolder) => {
    const name = h.holder_name ?? personName(h.user_id) ?? t('stakeholders.ui.role.unnamed_holder', { defaultValue: 'Unnamed holder' });
    if (h.valid_from && h.valid_to) {
      return t('stakeholders.ui.role.holder_between', {
        defaultValue: '{{name}} ({{from}} to {{to}})',
        name,
        from: fmtDate(h.valid_from),
        to: fmtDate(h.valid_to),
      });
    }
    if (h.valid_from) return t('stakeholders.ui.role.holder_from', { defaultValue: '{{name}} (from {{from}})', name, from: fmtDate(h.valid_from) });
    if (h.valid_to) return t('stakeholders.ui.role.holder_until', { defaultValue: '{{name}} (until {{to}})', name, to: fmtDate(h.valid_to) });
    return name;
  };
  const memberName = (m: GovernanceBody['members'][number]) =>
    m.role_code
      ? columnName(labels, { kind: 'role', code: m.role_code }, { screen, roles, bodies })
      : (personName(m.user_id) ?? t('stakeholders.ui.body.member_external', { defaultValue: 'External member' }));

  const addBody = (
    <GatedButton
      allowed={can}
      capability="organisation"
      variant="secondary"
      size="sm"
      icon={<Plus size={13} />}
      onClick={() => setDialog({ kind: 'body', body: null })}
      data-testid="body-add"
    >
      {t('stakeholders.ui.body.add_title', { defaultValue: 'Add a governance body' })}
    </GatedButton>
  );

  return (
    <div className="space-y-8" data-testid="organisation-panel">
      <section className="space-y-2">
        <SectionHead
          title={t('stakeholders.ui.role.title', { defaultValue: 'Roles' })}
          hint={t('stakeholders.ui.role.hint', {
            defaultValue: 'Who stands for the client, who manages, who controls. A required role without a holder blocks the next gate.',
          })}
        />
        {roles.roles.length === 0 ? (
          <div data-testid="roles-empty">
            <EmptyState
              icon={<Users size={28} />}
              title={t('stakeholders.ui.role.empty_title', { defaultValue: 'This framework brings no roles' })}
              description={t('stakeholders.ui.role.empty_body', {
                defaultValue: 'Roles come with the framework the project works with. Choose one that names them in the settings, then say here who holds each.',
              })}
              action={
                onOpenSettings && (
                  <Button variant="secondary" icon={<Settings2 size={14} />} onClick={onOpenSettings} data-testid="roles-open-settings">
                    {t('stakeholders.ui.role.open_settings', { defaultValue: 'Open the settings' })}
                  </Button>
                )
              }
            />
          </div>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid="role-list">
            {roles.roles.map((role) => {
              const holders = holdersOf(role.code);
              const vacant = roles.vacant.includes(role.code);
              const blocking = roles.vacant_required.includes(role.code);
              return (
                <li key={role.code} className="flex flex-wrap items-center gap-3 px-3 py-2" data-testid="role-entry" data-vacant={vacant}>
                  <span className="w-56 shrink-0 text-sm font-medium text-content-primary">
                    {itemName(labels, role)}
                    {role.required && (
                      <span className="ml-2 text-xs font-normal text-content-tertiary">{t('stakeholders.ui.role.required', { defaultValue: 'required' })}</span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1 text-sm">
                    {holders.filter((h) => h.valid_today).length > 0 ? (
                      <span className="text-content-primary">{fmtList(holders.filter((h) => h.valid_today).map(holderLine))}</span>
                    ) : (
                      <span
                        className={blocking ? 'flex items-center gap-1 font-medium text-semantic-error' : 'text-content-tertiary'}
                        data-testid="role-vacant"
                      >
                        {blocking && <AlertTriangle size={12} aria-hidden />}
                        {t('stakeholders.ui.role.vacant', { defaultValue: 'Vacant' })}
                      </span>
                    )}
                    {holders.some((h) => !h.valid_today) && (
                      <span className="block text-xs text-content-tertiary">
                        {t('stakeholders.ui.role.other_periods', {
                          defaultValue: 'Other periods: {{holders}}',
                          holders: fmtList(holders.filter((h) => !h.valid_today).map(holderLine)),
                        })}
                      </span>
                    )}
                  </span>
                  {can && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<UserCog size={13} />}
                      onClick={() => setDialog({ kind: 'role', role })}
                      data-testid="role-set"
                    >
                      {t('stakeholders.ui.role.set', { defaultValue: 'Set holder' })}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <SectionHead
          title={t('stakeholders.ui.body.title', { defaultValue: 'Bodies' })}
          hint={t('stakeholders.ui.body.hint', { defaultValue: 'Groups that decide together, with the members they need present.' })}
          action={bodies.length > 0 ? addBody : undefined}
        />
        {bodies.length === 0 ? (
          <div data-testid="bodies-empty">
            <EmptyState
              icon={<Network size={28} />}
              title={t('stakeholders.ui.body.empty_title', { defaultValue: 'No bodies yet' })}
              description={t('stakeholders.ui.body.empty_body', {
                defaultValue: 'Add one when a group, not one person, decides: a steering committee, a change board. Its members and its quorum say when it can decide.',
              })}
              action={addBody}
            />
          </div>
        ) : (
          <ul className="grid gap-2 md:grid-cols-2" data-testid="body-list">
            {bodies.map((b) => (
              <li key={b.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="body-entry">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-content-primary">{b.name}</span>
                  <span className="text-xs text-content-tertiary">{nameOf(labels, settings.framework.body_types, b.body_type)}</span>
                  {b.inquorate && (
                    <ToneBadge tone="error" testId="body-inquorate">
                      {t('stakeholders.ui.body.inquorate', { defaultValue: 'Cannot decide today' })}
                    </ToneBadge>
                  )}
                  {can && (
                    <span className="ml-auto flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Pencil size={13} />}
                        aria-label={t('stakeholders.ui.edit', { defaultValue: 'Edit' })}
                        onClick={() => setDialog({ kind: 'body', body: b })}
                        data-testid="body-edit"
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={13} />}
                        aria-label={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
                        onClick={() => setDialog({ kind: 'delete-body', body: b })}
                        data-testid="body-delete"
                      />
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-content-secondary">
                  {b.members.length > 0
                    ? t('stakeholders.ui.body.members_line', { defaultValue: 'Members: {{names}}', names: fmtList(b.members.map(memberName)) })
                    : t('stakeholders.ui.body.no_members', { defaultValue: 'No members yet' })}
                </p>
                <p className="text-xs text-content-tertiary">
                  {t('stakeholders.ui.body.quorum_line', {
                    defaultValue: 'To decide it needs: {{rule}}. Valid members today: {{present}} of {{needed}} needed.',
                    rule: vocab(t, QUORUM, b.quorum_kind),
                    present: b.quorum_present,
                    needed: b.quorum_needed,
                  })}
                </p>
                <p className="text-xs text-content-tertiary" data-testid="body-level">
                  {t('stakeholders.ui.body.level_line', { defaultValue: 'Escalation level {{level}}', level: b.decision_level })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {mandatesQ.data.decision_types.length === 0 ? (
        // Without kinds of decision there is no line to fill in and nothing to look up.
        <section className="space-y-2" data-testid="mandates-empty">
          <SectionHead title={t('stakeholders.ui.mandate.title', { defaultValue: 'Who decides what' })} />
          <EmptyState
            icon={<Scale size={28} />}
            title={t('stakeholders.ui.mandate.empty_title', { defaultValue: 'This framework names no kinds of decision' })}
            description={t('stakeholders.ui.mandate.empty_body', {
              defaultValue: 'The kinds of decision, such as awarding an order or agreeing a commitment, come with the framework the project works with. Choose one that names them in the settings, then say here who decides each.',
            })}
            action={
              onOpenSettings && (
                <Button variant="secondary" icon={<Settings2 size={14} />} onClick={onOpenSettings} data-testid="mandates-open-settings">
                  {t('stakeholders.ui.role.open_settings', { defaultValue: 'Open the settings' })}
                </Button>
              )
            }
          />
        </section>
      ) : (
        <>
          <MandateMatrix screen={screen} matrix={mandatesQ.data} roles={roles} bodies={bodies} onSaved={saved} />
          <WhoDecidesLookup screen={screen} matrix={mandatesQ.data} roles={roles} bodies={bodies} />
        </>
      )}

      {dialog?.kind === 'role' && (
        <RoleHoldersDialog
          screen={screen}
          role={dialog.role}
          holders={holdersOf(dialog.role.code)}
          roster={roster}
          onClose={() => setDialog(null)}
          onSaved={saved}
        />
      )}
      {dialog?.kind === 'body' && (
        <BodyDialog screen={screen} body={dialog.body} roles={roles.roles} onClose={() => setDialog(null)} onSaved={() => saved()} />
      )}
      <ConfirmDialog
        open={dialog?.kind === 'delete-body'}
        variant="danger"
        loading={removeBody.busy}
        title={t('stakeholders.ui.body.delete_title', { defaultValue: 'Remove this body?' })}
        message={
          removeBody.refusal?.message ??
          t('stakeholders.ui.body.delete_body', {
            defaultValue: 'The body and its member list are removed. A body that still holds a letter in the mandate matrix cannot be removed.',
          })
        }
        confirmLabel={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => {
          removeBody.clear();
          setDialog(null);
        }}
        onConfirm={() => dialog?.kind === 'delete-body' && removeBody.run(dialog.body)}
      />
    </div>
  );
}
