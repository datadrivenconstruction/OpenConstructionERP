// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The design team: who designs what, in which role, and the short code each
// party carries in drawing numbers. A role that drawings still use cannot be
// deleted; the server says so and the screen repeats it.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Users } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';

import { createRole, deleteRole, updateRole, type DesignRole, type PartyKind, type RoleInput } from './api';
import { CELL, CELL_MUTED, PanelHeader, ROLE_TONE, Table, ToneBadge, pickerField, type DesignContext, WriteButton } from './DesignBits';
import { useDesignOptions } from './hooks';
import { FormDialog, str, type FieldSpec, type FormValues } from './FormDialog';
import { PARTY_KIND, ROLE_STATE, ui, vocab, vocabOptions, type TFn } from './labels';
import { changedFields, filledFields, roleStateChoices } from './rules';

type Dialog = { kind: 'create' } | { kind: 'edit'; role: DesignRole } | { kind: 'delete'; role: DesignRole } | null;

const NULLABLE = ['discipline_code', 'originator_code', 'user_id', 'contact_id'] as const;

function roleValues(role: DesignRole | null): FormValues {
  return {
    code: role?.code ?? '',
    title: role?.title ?? '',
    party_kind: role?.party_kind ?? '',
    discipline_code: role?.discipline_code ?? '',
    originator_code: role?.originator_code ?? '',
    user_id: role?.user_id ?? '',
    contact_id: role?.contact_id ?? '',
    state: role?.state ?? 'planned',
  };
}

export function TeamPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const contacts = useDesignOptions(ctx.projectId, 'contacts', ctx.labels);

  const fields = (role: DesignRole | null): FieldSpec[] => [
    { name: 'title', label: ui(t, 'design.ui.team.title_field'), type: 'text', required: true },
    { name: 'party_kind', label: ui(t, 'design.ui.team.party_kind'), type: 'select', required: true, options: vocabOptions(t, PARTY_KIND) },
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
    { name: 'discipline_code', label: ui(t, 'design.ui.field.discipline'), type: 'text' },
    { name: 'originator_code', label: ui(t, 'design.ui.team.originator'), type: 'text', hint: ui(t, 'design.ui.team.originator_hint') },
    { name: 'user_id', label: ui(t, 'design.ui.team.person'), type: 'person' },
    ...pickerField('contact_id', ui(t, 'design.ui.team.contact'), contacts),
    ...(role
      ? [
          {
            name: 'state',
            label: ui(t, 'design.ui.field.state'),
            type: 'select' as const,
            required: true,
            options: roleStateChoices(role.state, role.can?.transitions).map((s) => ({ value: s, label: vocab(t, ROLE_STATE, s) })),
          },
        ]
      : []),
  ];

  const body = (values: FormValues): RoleInput => ({
    ...filledFields<RoleInput>({ ...values, state: '' }),
    party_kind: str(values, 'party_kind') as PartyKind,
  });

  return (
    <div className="space-y-4" data-testid="design-team-panel">
      <PanelHeader
        title={ui(t, 'design.ui.team.title')}
        hint={ui(t, 'design.ui.team.hint')}
        action={
          <WriteButton onClick={() => setDialog({ kind: 'create' })} data-testid="role-add">
            {ui(t, 'design.ui.team.add')}
          </WriteButton>
        }
      />
      {ctx.roles.length === 0 ? (
        <EmptyState
          icon={<Users size={28} />}
          title={ui(t, 'design.ui.team.empty_title')}
          description={ui(t, 'design.ui.team.empty_body')}
          action={{ label: ui(t, 'design.ui.team.add'), onClick: () => setDialog({ kind: 'create' }) }}
        />
      ) : (
        <Table
          testId="roles-table"
          head={[
            ui(t, 'design.ui.team.title_field'),
            ui(t, 'design.ui.team.party_kind'),
            ui(t, 'design.ui.field.discipline'),
            ui(t, 'design.ui.team.originator'),
            ui(t, 'design.ui.team.person'),
            ui(t, 'design.ui.field.state'),
            '',
          ]}
        >
          {ctx.roles.map((role) => (
            <tr key={role.id} data-testid="role-row">
              <td className={CELL}>
                <span className="font-medium">{role.title || role.code}</span>
                <span className="ml-2 font-mono text-xs text-content-tertiary">{role.code}</span>
              </td>
              <td className={CELL_MUTED}>{vocab(t, PARTY_KIND, role.party_kind)}</td>
              <td className={CELL_MUTED}>{role.discipline_code}</td>
              <td className={`${CELL_MUTED} font-mono`}>{role.originator_code}</td>
              <td className={CELL_MUTED}>
                {role.user_id ? ctx.personName(role.user_id) ?? ui(t, 'design.ui.team.project_member') : ui(t, 'design.ui.team.nobody')}
              </td>
              <td className={CELL}>
                <ToneBadge tone={ROLE_TONE[role.state]}>{vocab(t, ROLE_STATE, role.state)}</ToneBadge>
              </td>
              <td className={`${CELL} whitespace-nowrap text-right`}>
                <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'edit', role })}>
                  {ui(t, 'design.ui.action.edit')}
                </WriteButton>
                <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'delete', role })}>
                  {ui(t, 'design.ui.action.delete')}
                </WriteButton>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {dialog?.kind === 'create' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.team.add')}
          fields={fields(null)}
          initial={roleValues(null)}
          submitLabel={ui(t, 'design.ui.team.add')}
          submit={(values) => createRole(ctx.projectId, body(values))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'edit' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.team.edit')}
          fields={fields(dialog.role)}
          initial={roleValues(dialog.role)}
          submitLabel={ui(t, 'design.ui.action.save')}
          submit={(values) =>
            updateRole(ctx.projectId, dialog.role.id, changedFields<RoleInput>(roleValues(dialog.role), values, NULLABLE))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'delete' && (
        <FormDialog
          projectId={ctx.projectId}
          danger
          title={ui(t, 'design.ui.team.delete_title')}
          subtitle={ui(t, 'design.ui.team.delete_body', { name: dialog.role.title || dialog.role.code })}
          fields={[]}
          initial={{}}
          submitLabel={ui(t, 'design.ui.action.delete')}
          submit={() => deleteRole(ctx.projectId, dialog.role.id)}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
    </div>
  );
}
