// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Mandates that apply to one part of the project only: a lot, a building, a
// package. The grid above holds the rule for the whole project; a line here
// overrides it for the part it names. Each part has its own single decider.

import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import type { DecisionType, Letter, MandateRow } from './api';
import { FIELD_CLASS } from './StakeholderBits';
import { LETTER, itemName, vocab, type LabelContext } from './labels';
import { LETTERS, cellKey, type MatrixColumn } from './rules';

export interface ScopedMandatesProps {
  labels: LabelContext;
  rows: MandateRow[];
  decisionTypes: DecisionType[];
  columns: MatrixColumn[];
  columnName: (column: MatrixColumn) => string;
  /** Absent while the matrix is only shown. */
  onChange?: (rows: MandateRow[]) => void;
}

export function ScopedMandates({ labels, rows, decisionTypes, columns, columnName, onChange }: ScopedMandatesProps) {
  const { t } = useTranslation();
  const typeName = (code: string) => {
    const dt = decisionTypes.find((d) => d.code === code);
    return dt ? itemName(labels, dt) : code;
  };
  const title = (
    <div>
      <h3 className="text-sm font-medium text-content-primary">
        {t('stakeholders.ui.scoped.title', { defaultValue: 'Exceptions for one part of the project' })}
      </h3>
      <p className="text-xs text-content-secondary">
        {t('stakeholders.ui.scoped.hint', {
          defaultValue: 'When a lot, a building or a package is decided by someone else than the rest of the project, say so here.',
        })}
      </p>
    </div>
  );

  if (!onChange) {
    if (rows.length === 0) return null;
    return (
      <section className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="scoped-mandates">
        {title}
        <ul className="space-y-1 text-sm">
          {rows.map((r, i) => (
            <li key={`${cellKey(r.decision_type, { kind: r.holder_kind, code: r.holder_code })}-${r.scope}-${i}`} data-testid="scoped-row">
              <span className="text-content-primary">
                {t('stakeholders.ui.scoped.line', {
                  defaultValue: '{{decision}} for {{scope}}: {{holder}}, {{letter}}',
                  decision: typeName(r.decision_type),
                  scope: r.scope,
                  holder: columnName({ kind: r.holder_kind, code: r.holder_code }),
                  letter: vocab(t, LETTER, r.letter),
                })}
              </span>
              {r.scope_note && <span className="block text-xs text-content-tertiary">{r.scope_note}</span>}
            </li>
          ))}
        </ul>
      </section>
    );
  }

  const patch = (index: number, change: Partial<MandateRow>) => onChange(rows.map((r, i) => (i === index ? { ...r, ...change } : r)));
  const first = columns[0];

  return (
    <section className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="scoped-mandates">
      {title}
      {rows.length === 0 && (
        <p className="text-xs text-content-tertiary" data-testid="scoped-empty">
          {t('stakeholders.ui.scoped.empty', { defaultValue: 'No exceptions. The grid applies to the whole project.' })}
        </p>
      )}
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border border-border-light bg-surface-elevated p-2" data-testid="scoped-edit-row">
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.mandate.col_decision', { defaultValue: 'Decision' })}
            <select
              className={FIELD_CLASS}
              value={r.decision_type}
              onChange={(e) => patch(i, { decision_type: e.target.value })}
              data-testid="scoped-decision"
            >
              {decisionTypes.map((d) => (
                <option key={d.code} value={d.code}>
                  {itemName(labels, d)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[9rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.scoped.scope', { defaultValue: 'Part of the project' })}
            <input
              className={FIELD_CLASS}
              value={r.scope}
              maxLength={128}
              onChange={(e) => patch(i, { scope: e.target.value })}
              data-testid="scoped-scope"
            />
          </label>
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.scoped.holder', { defaultValue: 'Role or body' })}
            <select
              className={FIELD_CLASS}
              value={cellKey('', { kind: r.holder_kind, code: r.holder_code })}
              onChange={(e) => {
                const column = columns.find((c) => cellKey('', c) === e.target.value);
                if (column) patch(i, { holder_kind: column.kind, holder_code: column.code });
              }}
              data-testid="scoped-holder"
            >
              {columns.map((c) => (
                <option key={cellKey('', c)} value={cellKey('', c)}>
                  {columnName(c)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex w-40 flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.scoped.letter', { defaultValue: 'Part in the decision' })}
            <select
              className={FIELD_CLASS}
              value={r.letter}
              onChange={(e) => patch(i, { letter: e.target.value as Letter })}
              data-testid="scoped-letter"
            >
              {LETTERS.map((l) => (
                <option key={l} value={l}>
                  {vocab(t, LETTER, l)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[10rem] flex-[2] flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.scoped.note', { defaultValue: 'Note (optional)' })}
            <input className={FIELD_CLASS} value={r.scope_note} onChange={(e) => patch(i, { scope_note: e.target.value })} />
          </label>
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 size={13} />}
            aria-label={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
            onClick={() => onChange(rows.filter((_, x) => x !== i))}
            data-testid="scoped-remove"
          />
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        icon={<Plus size={13} />}
        disabled={!first || decisionTypes.length === 0}
        onClick={() =>
          first &&
          onChange([
            ...rows,
            {
              decision_type: decisionTypes[0]?.code ?? '',
              scope: '',
              holder_kind: first.kind,
              holder_code: first.code,
              letter: 'D',
              scope_note: '',
            },
          ])
        }
        data-testid="scoped-add"
      >
        {t('stakeholders.ui.scoped.add', { defaultValue: 'Add an exception' })}
      </Button>
    </section>
  );
}
