// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who decides what. One line per kind of decision, one column per role and
// body, and in each cell a letter: proposes, decides, approves alongside, is
// consulted, is informed. Exactly one cell of a line decides. Below the grid,
// a lookup answers the practical question: for this decision, today, who is
// it.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Pencil, Search } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { fmtList } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';

import {
  putMandates,
  whoDecides,
  type GovernanceBody,
  type Letter,
  type MandateConflict,
  type MandateMatrix as Matrix,
  type MandateRow,
  type OrganisationWriteNotes,
  type RolesView,
  type WhoDecides,
} from './api';
import { ConflictAcknowledge } from './ConflictAcknowledge';
import { ScopedMandates } from './ScopedMandates';
import { FIELD_CLASS, GatedButton, RefusalBox, SectionHead, useWrite } from './StakeholderBits';
import { DECIDER_FLAG, LETTER, humanizeCode, itemName, nameOf, vocab, type LabelContext } from './labels';
import { LETTERS, cellKey, doubleDeciders, doubleScopedDeciders, joinMatrix, splitMatrix, type MatrixColumn } from './rules';
import type { Screen } from './screen';

/** The name of a matrix column: the framework's role name, a project's own role label, or the body's name. */
export function columnName(
  labels: LabelContext,
  column: MatrixColumn,
  ctx: { screen: Screen; roles: RolesView | undefined; bodies: GovernanceBody[] },
): string {
  if (column.kind === 'body') return ctx.bodies.find((b) => b.code === column.code)?.name || humanizeCode(column.code);
  const defined = ctx.screen.settings.framework.roles.find((r) => r.code === column.code);
  if (defined) return itemName(labels, defined);
  const custom = ctx.roles?.holders.find((h) => h.role_code === column.code && h.custom_label)?.custom_label;
  return custom || humanizeCode(column.code);
}

export interface MandateMatrixProps {
  screen: Screen;
  matrix: Matrix;
  roles: RolesView | undefined;
  bodies: GovernanceBody[];
  onSaved: (notes: OrganisationWriteNotes) => void;
}

export function MandateMatrix({ screen, matrix, roles, bodies, onSaved }: MandateMatrixProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName } = screen;
  const stored = useMemo(() => splitMatrix(matrix.rows), [matrix.rows]);
  const [draft, setDraft] = useState<Record<string, Letter | ''> | null>(null);
  const [scopedDraft, setScopedDraft] = useState<MandateRow[]>([]);
  const cells = draft ?? stored.cells;
  const editing = draft !== null;

  const columns: MatrixColumn[] = [
    ...matrix.roles.map((code) => ({ kind: 'role' as const, code })),
    ...matrix.bodies.map((code) => ({ kind: 'body' as const, code })),
  ];
  const nameCtx = { screen, roles, bodies };
  const doubles = editing ? doubleDeciders(cells) : [];
  const scopedDoubles = editing ? doubleScopedDeciders(scopedDraft) : [];
  const scopeMissing = editing && scopedDraft.some((r) => !r.scope.trim());

  const write = useWrite(
    () => putMandates(projectId, joinMatrix(cells, editing ? scopedDraft : stored.scoped, matrix.rows)),
    (result) => {
      setDraft(null);
      onSaved(result);
    },
  );

  const typeName = (code: string) => nameOf(labels, matrix.decision_types, code);
  const conflictText = (c: MandateConflict) =>
    t('stakeholders.ui.mandate.conflict_line', {
      defaultValue: '{{person}} holds {{letters}} for {{decision}} through the roles {{roles}}.',
      person: personName(c.user_id) ?? t('stakeholders.ui.someone', { defaultValue: 'One person' }),
      letters: fmtList(c.letters.map((l) => vocab(t, LETTER, l)), 'prose'),
      decision: typeName(c.decision_type),
      roles: fmtList(c.roles.map((code) => columnName(labels, { kind: 'role', code }, nameCtx)), 'prose'),
    });

  return (
    <section className="space-y-3" data-testid="mandate-matrix">
      <SectionHead
        title={t('stakeholders.ui.mandate.title', { defaultValue: 'Who decides what' })}
        hint={t('stakeholders.ui.mandate.hint', {
          defaultValue: 'One line per kind of decision. Exactly one role or body decides each line.',
        })}
        action={
          editing ? (
            <span className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => { setDraft(null); write.clear(); }} disabled={write.busy}>
                {t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button size="sm" loading={write.busy} disabled={doubles.length > 0 || scopedDoubles.length > 0 || scopeMissing} onClick={() => write.run(undefined)} data-testid="mandate-save">
                {t('stakeholders.ui.mandate.save', { defaultValue: 'Save mandates' })}
              </Button>
            </span>
          ) : (
            <GatedButton
              allowed={settings.can.manage_organisation}
              capability="organisation"
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={() => {
                setDraft({ ...stored.cells });
                setScopedDraft(stored.scoped.map((r) => ({ ...r })));
              }}
              data-testid="mandate-edit"
            >
              {t('stakeholders.ui.mandate.edit', { defaultValue: 'Edit mandates' })}
            </GatedButton>
          )
        }
      />

      {write.refusal?.code === 'conflict_not_acknowledged' ? (
        <ConflictAcknowledge screen={screen} refusal={write.refusal} onAcknowledged={() => write.run(undefined)} />
      ) : (
        <RefusalBox refusal={write.refusal} />
      )}
      {doubles.length > 0 && (
        <p role="alert" className="text-xs text-semantic-error" data-testid="mandate-two-deciders">
          {t('stakeholders.ui.mandate.two_deciders', {
            defaultValue: 'Only one role or body can decide: {{decisions}}',
            decisions: fmtList(doubles.map(typeName)),
          })}
        </p>
      )}

      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-secondary" aria-label={t('stakeholders.ui.mandate.legend', { defaultValue: 'What the letters mean' })}>
        {LETTERS.map((l) => (
          <li key={l}>
            <span className="font-semibold text-content-primary">{l}</span> {vocab(t, LETTER, l)}
          </li>
        ))}
      </ul>

      <div className="overflow-x-auto rounded-lg border border-border-light">
        <table className="w-full text-sm" data-testid="mandate-table">
          <thead className="bg-surface-secondary text-xs text-content-tertiary">
            <tr>
              <th scope="col" className="sticky left-0 min-w-[12rem] bg-surface-secondary px-3 py-2 text-left font-medium">
                {t('stakeholders.ui.mandate.col_decision', { defaultValue: 'Decision' })}
              </th>
              {columns.map((c) => (
                <th key={cellKey('', c)} scope="col" className="min-w-[5.5rem] px-2 py-2 text-center font-medium">
                  {columnName(labels, c, nameCtx)}
                  {c.kind === 'body' && (
                    <span className="block font-normal text-content-quaternary">{t('stakeholders.ui.mandate.body_tag', { defaultValue: 'body' })}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.decision_types.map((dt) => {
              const missing = !editing && matrix.missing.includes(dt.code);
              return (
                <tr key={dt.code} className="border-t border-border-light" data-testid="mandate-row" data-missing={missing}>
                  <th scope="row" className="sticky left-0 bg-surface-primary px-3 py-2 text-left font-normal text-content-primary">
                    {itemName(labels, dt)}
                    {missing && (
                      <span className="mt-0.5 flex items-center gap-1 text-xs font-medium text-semantic-error" data-testid="mandate-missing">
                        <AlertTriangle size={12} aria-hidden />
                        {t('stakeholders.ui.mandate.missing', { defaultValue: 'Nobody decides this yet' })}
                      </span>
                    )}
                  </th>
                  {columns.map((c) => {
                    const key = cellKey(dt.code, c);
                    const letter = cells[key] ?? '';
                    return (
                      <td key={key} className="px-2 py-1.5 text-center">
                        {editing ? (
                          <select
                            className="rounded border border-border-light bg-surface-primary px-1 py-0.5 text-sm"
                            value={letter}
                            aria-label={t('stakeholders.ui.mandate.cell', {
                              defaultValue: '{{decision}}: {{holder}}',
                              decision: itemName(labels, dt),
                              holder: columnName(labels, c, nameCtx),
                            })}
                            onChange={(e) => setDraft((d) => ({ ...(d ?? {}), [key]: e.target.value as Letter | '' }))}
                            data-testid="mandate-cell"
                          >
                            <option value="">{t('stakeholders.ui.mandate.no_letter', { defaultValue: 'none' })}</option>
                            {LETTERS.map((l) => (
                              <option key={l} value={l}>
                                {l}
                              </option>
                            ))}
                          </select>
                        ) : letter ? (
                          <span
                            title={vocab(t, LETTER, letter)}
                            className={clsx(
                              'inline-flex h-6 w-6 items-center justify-center rounded text-xs font-semibold',
                              letter === 'D' ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-primary',
                            )}
                          >
                            {letter}
                            <span className="sr-only">{vocab(t, LETTER, letter)}</span>
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {scopedDoubles.length > 0 && (
        <p role="alert" className="text-xs text-semantic-error" data-testid="scoped-two-deciders">
          {t('stakeholders.ui.mandate.two_deciders', {
            defaultValue: 'Only one role or body can decide: {{decisions}}',
            decisions: fmtList(
              scopedDoubles.map(([type, scope]) =>
                t('stakeholders.ui.scoped.name', { defaultValue: '{{decision}} for {{scope}}', decision: typeName(type), scope }),
              ),
            ),
          })}
        </p>
      )}
      {scopeMissing && (
        <p className="text-xs text-semantic-error" data-testid="scoped-scope-missing">
          {t('stakeholders.ui.scoped.scope_missing', { defaultValue: 'Name the part of the project each exception applies to.' })}
        </p>
      )}
      <ScopedMandates
        labels={labels}
        rows={editing ? scopedDraft : stored.scoped}
        decisionTypes={matrix.decision_types}
        columns={columns}
        columnName={(c) => columnName(labels, c, nameCtx)}
        onChange={editing ? setScopedDraft : undefined}
      />

      {matrix.conflicts.length > 0 && (
        <div className="rounded-lg border border-semantic-warning/40 p-3" data-testid="mandate-conflicts">
          <h3 className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
            <AlertTriangle size={14} className="text-semantic-warning" aria-hidden />
            {t('stakeholders.ui.mandate.conflicts_title', { defaultValue: 'One person on both sides of a decision' })}
          </h3>
          <ul className="ml-5 mt-1 list-disc space-y-0.5 text-xs text-content-secondary">
            {matrix.conflicts.map((c, i) => (
              <li key={`${c.decision_type}-${c.user_id}-${i}`}>
                {conflictText(c)}{' '}
                {c.acknowledged && <span className="text-content-tertiary">{t('stakeholders.ui.mandate.acknowledged', { defaultValue: '(accepted with a written reason)' })}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export interface WhoDecidesLookupProps {
  screen: Screen;
  matrix: Matrix;
  roles: RolesView | undefined;
  bodies: GovernanceBody[];
}

/** The lookup: pick a kind of decision, optionally an amount, and read who decides it today. */
export function WhoDecidesLookup({ screen, matrix, roles, bodies }: WhoDecidesLookupProps) {
  const { t } = useTranslation();
  const { projectId, labels, personName } = screen;
  const [decisionType, setDecisionType] = useState(matrix.decision_types[0]?.code ?? '');
  const [amount, setAmount] = useState('');
  const [answer, setAnswer] = useState<WhoDecides | null>(null);
  const lookup = useWrite(() => whoDecides(projectId, { decisionType, amount: amount.trim() || undefined }), setAnswer);
  const selected = matrix.decision_types.find((d) => d.code === decisionType);

  const partyName = (p: WhoDecides['parties'][number]) =>
    (p.name || null) ??
    personName(p.user_id) ??
    roles?.holders.find((h) => h.roster_member_id && h.roster_member_id === p.roster_member_id)?.holder_name ??
    roles?.holders.find((h) => h.holder_contact_id && h.holder_contact_id === p.contact_id)?.holder_name ??
    t('stakeholders.ui.who.unnamed_party', { defaultValue: 'A member without an account' });

  return (
    <section className="space-y-3 rounded-lg border border-border-light p-3" data-testid="who-decides">
      <SectionHead
        title={t('stakeholders.ui.who.title', { defaultValue: 'Look up who decides' })}
        hint={t('stakeholders.ui.who.hint', { defaultValue: 'Pick a kind of decision and read who holds it today.' })}
      />
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[14rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
          {t('stakeholders.ui.mandate.col_decision', { defaultValue: 'Decision' })}
          <select
            className={FIELD_CLASS}
            value={decisionType}
            onChange={(e) => {
              setDecisionType(e.target.value);
              setAnswer(null);
            }}
            data-testid="who-decision"
          >
            {matrix.decision_types.map((d) => (
              <option key={d.code} value={d.code}>
                {itemName(labels, d)}
              </option>
            ))}
          </select>
        </label>
        {selected?.commitment_type && (
          <label className="flex w-40 flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.who.amount', { defaultValue: 'Amount (optional)' })}
            <input className={FIELD_CLASS} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
        )}
        <Button
          variant="secondary"
          icon={<Search size={14} />}
          loading={lookup.busy}
          disabled={!decisionType}
          onClick={() => lookup.run(undefined)}
          data-testid="who-lookup"
        >
          {t('stakeholders.ui.who.lookup', { defaultValue: 'Look up' })}
        </Button>
      </div>
      <RefusalBox refusal={lookup.refusal} />
      {answer && (
        <div className="space-y-1 text-sm" data-testid="who-answer">
          {answer.holder_code && answer.holder_kind && (
            <p className="text-content-primary">
              {t('stakeholders.ui.who.holder', {
                defaultValue: 'Decided by: {{holder}}',
                holder: columnName(labels, { kind: answer.holder_kind, code: answer.holder_code }, { screen, roles, bodies }),
              })}
            </p>
          )}
          {answer.parties.length > 0 && (
            <p className="text-content-secondary">
              {t('stakeholders.ui.who.people', { defaultValue: 'Today that is: {{names}}', names: fmtList(answer.parties.map(partyName)) })}
            </p>
          )}
          {answer.quorum_needed != null && (
            <p className="text-content-secondary">
              {t('stakeholders.ui.who.quorum', {
                defaultValue: 'Valid members today: {{present}}. Needed to decide: {{needed}}.',
                present: answer.quorum_present ?? 0,
                needed: answer.quorum_needed,
              })}
            </p>
          )}
          {answer.authority && (
            <p className="text-content-secondary">
              {answer.authority.escalate_outside
                ? t('stakeholders.ui.who.authority_outside', {
                    defaultValue: '{{amount}} is above every limit in the authority schedule and goes outside the project.',
                    amount: formatCurrency(answer.authority.amount, answer.authority.currency),
                  })
                : t('stakeholders.ui.who.authority', {
                    defaultValue: '{{amount}} falls under: {{names}}',
                    amount: formatCurrency(answer.authority.amount, answer.authority.currency),
                    names:
                      fmtList(answer.authority.approver_user_ids.map((id) => personName(id) ?? '')) ||
                      humanizeCode(answer.authority.tier_code ?? ''),
                  })}
            </p>
          )}
          {answer.flags.map((flag) => (
            <p key={flag} className="flex items-center gap-1.5 text-xs font-medium text-semantic-error" data-testid="who-flag" data-flag={flag}>
              <AlertTriangle size={12} aria-hidden />
              {vocab(t, DECIDER_FLAG, flag)}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
