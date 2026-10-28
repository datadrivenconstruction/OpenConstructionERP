// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the reader sees when a change to the mandates or to a body is refused
// because it puts one person on both sides of a decision. The server accepts
// that only with a written reason on the person's role. This box names each
// case, takes the reason, writes it onto the role and then repeats the save
// that was refused.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtList } from '@/shared/lib/formatters';

import { putRoleHolders, type HolderInput, type RoleHolder } from './api';
import { FIELD_CLASS, RefusalBox, useWrite, type Refusal } from './StakeholderBits';
import { useRoles } from './hooks';
import { LETTER, nameOf, vocab } from './labels';
import type { Screen } from './screen';

/** One case the server listed: a person, the decision, and the roles that put them on both sides. */
export interface ConflictCase {
  decisionType: string;
  scope: string;
  userId: string;
  letters: string[];
  roles: string[];
}

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string') : []);

/** The cases of a refusal, read from its `violations`. Entries without a person or a decision are dropped. */
export function conflictCases(refusal: Refusal | null): ConflictCase[] {
  if (!refusal) return [];
  return refusal.violations.flatMap((v) =>
    typeof v.user_id === 'string' && typeof v.decision_type === 'string'
      ? [
          {
            decisionType: v.decision_type,
            scope: typeof v.scope === 'string' ? v.scope : '',
            userId: v.user_id,
            letters: strings(v.letters),
            roles: strings(v.roles),
          },
        ]
      : [],
  );
}

/**
 * The role rows a reason has to be written on: for each case, the rows of
 * that person in the roles the case names. A case whose person holds none of
 * those roles (a named seat on a body) cannot be accepted this way.
 */
export function holdersToAcknowledge(cases: readonly ConflictCase[], holders: readonly RoleHolder[]): {
  rows: RoleHolder[];
  open: ConflictCase[];
} {
  const rows = new Map<string, RoleHolder>();
  const open: ConflictCase[] = [];
  for (const c of cases) {
    const mine = holders.filter((h) => h.user_id === c.userId && c.roles.includes(h.role_code));
    if (mine.length === 0) open.push(c);
    for (const h of mine) rows.set(h.id, h);
  }
  return { rows: [...rows.values()], open };
}

const asInput = (h: RoleHolder, rationale: string | null): HolderInput => ({
  roster_member_id: h.roster_member_id,
  holder_contact_id: h.holder_contact_id,
  deputy_roster_member_id: h.deputy_roster_member_id,
  valid_from: h.valid_from,
  valid_to: h.valid_to,
  conflict_rationale: rationale ?? h.conflict_rationale,
});

export interface ConflictAcknowledgeProps {
  screen: Screen;
  refusal: Refusal;
  /** Repeats the save that was refused, once the reason is on record. */
  onAcknowledged: () => void;
}

export function ConflictAcknowledge({ screen, refusal, onAcknowledged }: ConflictAcknowledgeProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName } = screen;
  const fw = settings.framework;
  const rolesQ = useRoles(projectId);
  const [reason, setReason] = useState('');
  const cases = conflictCases(refusal);
  const holders = rolesQ.data?.holders ?? [];
  const { rows, open } = holdersToAcknowledge(cases, holders);

  const write = useWrite(async () => {
    const text = reason.trim();
    for (const role of [...new Set(rows.map((r) => r.role_code))]) {
      const all = holders.filter((h) => h.role_code === role);
      await putRoleHolders(
        projectId,
        role,
        all.map((h) => asInput(h, rows.some((r) => r.id === h.id) ? text : null)),
        all[0]?.custom_label ?? '',
      );
    }
  }, onAcknowledged);

  const caseText = (c: ConflictCase) =>
    t('stakeholders.ui.mandate.conflict_line', {
      defaultValue: '{{person}} holds {{letters}} for {{decision}} through the roles {{roles}}.',
      person: personName(c.userId) ?? t('stakeholders.ui.someone', { defaultValue: 'One person' }),
      letters: fmtList(c.letters.map((l) => vocab(t, LETTER, l)), 'prose'),
      decision: nameOf(labels, fw.decision_types, c.decisionType),
      roles: fmtList(c.roles.map((code) => nameOf(labels, fw.roles, code)), 'prose'),
    });

  if (cases.length === 0) return <RefusalBox refusal={refusal} />;

  return (
    <div
      role="alert"
      className="space-y-2 rounded-md border border-semantic-warning/40 bg-surface-secondary p-3 text-sm"
      data-testid="conflict-acknowledge"
    >
      <p className="flex items-start gap-1.5 font-medium text-content-primary">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
        {t('stakeholders.ui.conflict.title', {
          defaultValue: 'This change puts one person on both sides of a decision. It is saved only with a written reason.',
        })}
      </p>
      <ul className="ml-5 list-disc space-y-0.5 text-xs text-content-secondary" data-testid="conflict-cases">
        {cases.map((c, i) => (
          <li key={`${c.decisionType}-${c.userId}-${i}`}>{caseText(c)}</li>
        ))}
      </ul>
      <RefusalBox refusal={write.refusal} />
      {rolesQ.isLoading ? null : rows.length === 0 || open.length > 0 ? (
        <p className="text-xs text-content-secondary" data-testid="conflict-no-role">
          {t('stakeholders.ui.conflict.no_role', {
            defaultValue: 'A person who sits on a body by name, without a project role, cannot be accepted here. Change the members or the letters so that nobody proposes and decides the same thing.',
          })}
        </p>
      ) : (
        <>
          <label className="block text-xs text-content-secondary">
            {t('stakeholders.ui.conflict.reason', { defaultValue: 'Why this is accepted on this project' })}
            <textarea
              rows={2}
              className={FIELD_CLASS}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              data-testid="conflict-reason"
            />
          </label>
          <p className="text-xs text-content-tertiary">
            {t('stakeholders.ui.conflict.where', {
              defaultValue: 'The reason is stored with the role of that person and shown with the mandates.',
            })}
          </p>
          <Button
            size="sm"
            loading={write.busy}
            disabled={!reason.trim()}
            onClick={() => write.run(undefined)}
            data-testid="conflict-accept"
          >
            {t('stakeholders.ui.conflict.accept', { defaultValue: 'Record the reason and save' })}
          </Button>
        </>
      )}
    </div>
  );
}
