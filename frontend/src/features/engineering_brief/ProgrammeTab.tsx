// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The room and area programme: lines with a kind, a label, a quantity, a unit
// and the basis the quantity comes from. Quantities travel as decimal strings.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';

import {
  createProgrammeLine,
  deleteProgrammeLine,
  updateProgrammeLine,
  type BriefCatalogue,
  type Can,
  type ProgrammeInput,
  type ProgrammeLine,
} from './api';
import { ExportButtons, FIELD_CLASS, FormError, ReadOnlyNotice, useBriefAction, useSubmit } from './BriefBits';
import { itemLabel, type LabelContext } from './labels';

const EMPTY: ProgrammeInput = { kind_code: '', label: '', unit: '', quantity: '', basis: '' };
const DECIMAL = /^-?\d+(\.\d+)?$/;

/** A decimal as typed, with a comma accepted as the separator; null when it is not a number. */
export function normaliseQuantity(raw: string): string | null {
  const text = raw.trim().replace(',', '.');
  return DECIMAL.test(text) ? text : null;
}

function ProgrammeDialog({
  open,
  projectId,
  catalogue,
  labels,
  editing,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  catalogue: BriefCatalogue;
  labels: LabelContext;
  editing: ProgrammeLine | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ProgrammeInput>(EMPTY);
  const [tried, setTried] = useState(false);
  const sub = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (!open) return;
    setTried(false);
    sub.reset();
    if (editing) {
      setForm({ kind_code: editing.kind_code, label: editing.label, unit: editing.unit, quantity: editing.quantity, basis: editing.basis });
    } else {
      const first = catalogue.programme_kinds[0];
      setForm({ ...EMPTY, kind_code: first?.code ?? '', unit: first?.default_unit ?? '' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const quantity = normaliseQuantity(form.quantity);
  const invalid = !form.kind_code || !form.label.trim() || !form.unit.trim() || quantity === null;
  const required = t('engineeringBrief.required', { defaultValue: 'Required' });
  const save = () => {
    if (invalid || quantity === null) {
      setTried(true);
      return;
    }
    const body = { ...form, quantity };
    void sub.run(() => (editing ? updateProgrammeLine(projectId, editing.id, body) : createProgrammeLine(projectId, body)));
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="md"
      testId="brief-programme-dialog"
      title={
        editing
          ? t('engineeringBrief.programme.edit', { defaultValue: 'Edit programme line' })
          : t('engineeringBrief.programme.add', { defaultValue: 'Add programme line' })
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={save} data-testid="brief-programme-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <WideModalField label={t('engineeringBrief.programme.kind', { defaultValue: 'Kind' })} required>
          <select
            className={FIELD_CLASS}
            value={form.kind_code}
            onChange={(e) => {
              const kind = catalogue.programme_kinds.find((k) => k.code === e.target.value);
              setForm((f) => ({ ...f, kind_code: e.target.value, unit: f.unit || kind?.default_unit || '' }));
            }}
          >
            {catalogue.programme_kinds.map((k) => (
              <option key={k.code} value={k.code}>
                {itemLabel(labels, k, k.code)}
              </option>
            ))}
            {form.kind_code && !catalogue.programme_kinds.some((k) => k.code === form.kind_code) ? (
              <option value={form.kind_code}>{form.kind_code}</option>
            ) : null}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.programme.label', { defaultValue: 'Label' })} required error={tried && !form.label.trim() ? required : undefined}>
          <input className={FIELD_CLASS} value={form.label} maxLength={255} onChange={(e) => setForm({ ...form, label: e.target.value })} data-testid="brief-programme-label" />
        </WideModalField>
        <div className="grid grid-cols-2 gap-3">
          <WideModalField
            label={t('engineeringBrief.programme.quantity', { defaultValue: 'Quantity' })}
            required
            error={tried && quantity === null ? t('engineeringBrief.programme.quantity_invalid', { defaultValue: 'Enter a number' }) : undefined}
          >
            <input className={FIELD_CLASS} inputMode="decimal" value={form.quantity} maxLength={32} onChange={(e) => setForm({ ...form, quantity: e.target.value })} data-testid="brief-programme-quantity" />
          </WideModalField>
          <WideModalField label={t('engineeringBrief.programme.unit', { defaultValue: 'Unit' })} required error={tried && !form.unit.trim() ? required : undefined}>
            <input className={FIELD_CLASS} value={form.unit} maxLength={20} onChange={(e) => setForm({ ...form, unit: e.target.value })} data-testid="brief-programme-unit" />
          </WideModalField>
        </div>
        <WideModalField label={t('engineeringBrief.programme.basis', { defaultValue: 'Basis' })} hint={t('engineeringBrief.programme.basis_hint', { defaultValue: 'Where the quantity comes from.' })}>
          <textarea className={FIELD_CLASS} rows={3} value={form.basis} maxLength={5000} onChange={(e) => setForm({ ...form, basis: e.target.value })} />
        </WideModalField>
      </div>
    </WideModal>
  );
}

export function ProgrammeTab({
  projectId,
  lines,
  catalogue,
  labels,
  edit,
  onChanged,
}: {
  projectId: string;
  lines: ProgrammeLine[];
  catalogue: BriefCatalogue;
  labels: LabelContext;
  edit: Can;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<{ editing: ProgrammeLine | null } | null>(null);
  const [removing, setRemoving] = useState<ProgrammeLine | null>(null);
  const remove = useBriefAction((id: string) => deleteProgrammeLine(projectId, id), () => {
    setRemoving(null);
    onChanged();
  });

  return (
    <div className="space-y-4" data-testid="brief-programme">
      <ReadOnlyNotice edit={edit} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ExportButtons projectId={projectId} what="programme" />
        {edit.allowed ? (
          <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ editing: null })} data-testid="brief-programme-add">
            {t('engineeringBrief.programme.add', { defaultValue: 'Add programme line' })}
          </Button>
        ) : null}
      </div>

      {lines.length === 0 ? (
        <EmptyState
          title={t('engineeringBrief.programme.empty_title', { defaultValue: 'No programme lines yet' })}
          description={t('engineeringBrief.programme.empty_body', {
            defaultValue: 'List the rooms, areas and capacities the building has to provide, each with a quantity and its unit.',
          })}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
              <tr>
                <th className="px-3 py-2">{t('engineeringBrief.programme.code', { defaultValue: 'No.' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.programme.kind', { defaultValue: 'Kind' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.programme.label', { defaultValue: 'Label' })}</th>
                <th className="px-3 py-2 text-right">{t('engineeringBrief.programme.quantity', { defaultValue: 'Quantity' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.programme.unit', { defaultValue: 'Unit' })}</th>
                <th className="px-3 py-2">{t('engineeringBrief.programme.basis', { defaultValue: 'Basis' })}</th>
                <th className="w-20 px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id} className="border-t border-border-light" data-testid="brief-programme-row">
                  <td className="px-3 py-2 font-mono text-xs text-content-tertiary">{l.code}</td>
                  <td className="px-3 py-2 text-content-secondary">{itemLabel(labels, catalogue.programme_kinds.find((k) => k.code === l.kind_code), l.kind_code)}</td>
                  <td className="px-3 py-2 text-content-primary">{l.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-primary">{l.quantity}</td>
                  <td className="px-3 py-2 text-content-secondary">{l.unit}</td>
                  <td className="px-3 py-2 text-content-secondary">{l.basis || '-'}</td>
                  <td className="px-3 py-2">
                    {edit.allowed ? (
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={14} />} onClick={() => setDialog({ editing: l })} />
                        <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={14} />} onClick={() => setRemoving(l)} />
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ProgrammeDialog
        open={dialog !== null}
        projectId={projectId}
        catalogue={catalogue}
        labels={labels}
        editing={dialog?.editing ?? null}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t('engineeringBrief.programme.delete_title', { defaultValue: 'Delete programme line' })}
        message={t('engineeringBrief.programme.delete_body', { defaultValue: 'This line is removed from the programme.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
