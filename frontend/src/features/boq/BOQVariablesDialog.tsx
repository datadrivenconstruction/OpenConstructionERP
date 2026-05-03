/**
 * BOQVariablesDialog — manage per-BOQ named variables ($GFA, $LABOR_RATE …).
 *
 * Variables live on `boq.metadata.variables` and are referenced from the
 * formula engine (Phase C+). Names are uppercase, alnum + underscore,
 * 1–32 chars; the UI shows them with a leading `$` prefix.
 *
 * Editing is whole-list-replace — the user edits the table, hits Save, and
 * the entire array round-trips. This keeps state simple and matches the
 * backend `PUT /v1/boq/boqs/{id}/variables/` endpoint.
 */
import { useEffect, useMemo, useState, type FormEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { X, Plus, Trash2, Variable as VariableIcon, AlertCircle } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi, type BOQVariable } from './api';
import { getErrorMessage } from '@/shared/lib/api';

interface BOQVariablesDialogProps {
  open: boolean;
  onClose: () => void;
  boqId: string;
}

const NAME_RE = /^[A-Z][A-Z0-9_]{0,31}$/;
const MAX_VARIABLES = 50;

interface Draft {
  /** stable client-side row id so React can key safely while names are
   *  being typed (the canonical id `name` may be empty or duplicate). */
  uid: string;
  name: string;
  type: BOQVariable['type'];
  value: string;
  description: string;
}

function makeUid(): string {
  return `v_${Math.random().toString(36).slice(2, 10)}`;
}

function fromServer(v: BOQVariable): Draft {
  return {
    uid: makeUid(),
    name: v.name,
    type: v.type,
    value: v.value === null || v.value === undefined ? '' : String(v.value),
    description: v.description ?? '',
  };
}

function blankRow(): Draft {
  return { uid: makeUid(), name: '', type: 'number', value: '', description: '' };
}

function toPayload(d: Draft): BOQVariable {
  // Normalise the name on submit: strip `$`, uppercase, trim. Backend
  // also defends against this but doing it here gives the user instant
  // feedback in the table.
  const cleaned = d.name.replace(/^\$/, '').trim().toUpperCase();
  let value: BOQVariable['value'];
  if (d.value === '') {
    value = null;
  } else if (d.type === 'number') {
    const n = Number(d.value);
    value = Number.isFinite(n) ? n : (d.value as unknown as string);
  } else {
    value = d.value;
  }
  return {
    name: cleaned,
    type: d.type,
    value,
    description: d.description.trim() || null,
  };
}

function validateRow(d: Draft, allNames: string[]): string | null {
  const cleaned = d.name.replace(/^\$/, '').trim().toUpperCase();
  if (!cleaned) return 'Name required';
  if (!NAME_RE.test(cleaned)) {
    return 'Use UPPER_SNAKE_CASE, letters/digits/underscore, max 32 chars';
  }
  if (allNames.filter((n) => n === cleaned).length > 1) {
    return 'Duplicate name';
  }
  if (d.type === 'number' && d.value !== '' && !Number.isFinite(Number(d.value))) {
    return 'Value must be numeric';
  }
  return null;
}

export function BOQVariablesDialog({ open, onClose, boqId }: BOQVariablesDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);

  const variablesQuery = useQuery({
    queryKey: ['boq', boqId, 'variables'],
    queryFn: () => boqApi.listBoqVariables(boqId),
    enabled: open,
    staleTime: 0,
  });

  // Hydrate drafts whenever fresh server data arrives or the dialog opens.
  useEffect(() => {
    if (!open) return;
    if (variablesQuery.data) {
      setDrafts(variablesQuery.data.map(fromServer));
      setServerError(null);
    }
  }, [open, variablesQuery.data]);

  const replaceMutation = useMutation({
    mutationFn: (vars: BOQVariable[]) => boqApi.replaceBoqVariables(boqId, vars),
    onSuccess: (saved) => {
      queryClient.setQueryData(['boq', boqId, 'variables'], saved);
      setDrafts(saved.map(fromServer));
      setServerError(null);
      addToast({
        type: 'success',
        title: t('boq.variables_saved', { defaultValue: 'Variables saved' }),
      });
    },
    onError: (err) => {
      setServerError(getErrorMessage(err));
    },
  });

  const namesSnapshot = useMemo(
    () => drafts.map((d) => d.name.replace(/^\$/, '').trim().toUpperCase()),
    [drafts],
  );
  const rowErrors = useMemo(
    () => drafts.map((d) => validateRow(d, namesSnapshot)),
    [drafts, namesSnapshot],
  );
  const hasErrors = rowErrors.some((e) => e !== null);
  const overCap = drafts.length > MAX_VARIABLES;

  function patchRow(uid: string, patch: Partial<Draft>) {
    setDrafts((prev) => prev.map((d) => (d.uid === uid ? { ...d, ...patch } : d)));
    setServerError(null);
  }

  function deleteRow(uid: string) {
    setDrafts((prev) => prev.filter((d) => d.uid !== uid));
    setServerError(null);
  }

  function addRow() {
    if (drafts.length >= MAX_VARIABLES) return;
    setDrafts((prev) => [...prev, blankRow()]);
  }

  function handleSave(e: FormEvent) {
    e.preventDefault();
    if (hasErrors || overCap) return;
    replaceMutation.mutate(drafts.map(toPayload));
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="boq-variables-dialog-title"
        className="w-full max-w-3xl max-h-[88vh] overflow-hidden rounded-2xl bg-surface-elevated shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-border-light px-5 py-3">
          <div className="flex items-center gap-2">
            <VariableIcon size={18} className="text-oe-blue" />
            <h2 id="boq-variables-dialog-title" className="text-base font-semibold text-content-primary">
              {t('boq.variables_title', { defaultValue: 'BOQ variables' })}
            </h2>
            <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-tertiary">
              {drafts.length}/{MAX_VARIABLES}
            </span>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSave} className="flex flex-1 flex-col overflow-hidden">
          {/* Body */}
          <div className="flex-1 overflow-auto px-5 py-4 space-y-3">
            <p className="text-xs text-content-tertiary">
              {t('boq.variables_help', {
                defaultValue:
                  'Define named values you can reference in formulas. e.g. set $GFA = 1500, then write =$GFA * 0.15 in any quantity or rate cell.',
              })}
            </p>

            {variablesQuery.isLoading && (
              <p className="text-sm text-content-tertiary">{t('common.loading', { defaultValue: 'Loading…' })}</p>
            )}

            {drafts.length === 0 && !variablesQuery.isLoading && (
              <div className="rounded-xl border border-dashed border-border-light bg-surface-secondary/40 px-4 py-8 text-center">
                <p className="text-sm text-content-secondary">
                  {t('boq.variables_empty', {
                    defaultValue: 'No variables yet. Add the first one below.',
                  })}
                </p>
              </div>
            )}

            {drafts.length > 0 && (
              <div className="overflow-hidden rounded-xl border border-border-light">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary/40 text-2xs uppercase tracking-wider text-content-tertiary">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold w-[22%]">
                        {t('boq.variables_name', { defaultValue: 'Name' })}
                      </th>
                      <th className="px-3 py-2 text-left font-semibold w-[14%]">
                        {t('boq.variables_type', { defaultValue: 'Type' })}
                      </th>
                      <th className="px-3 py-2 text-left font-semibold w-[20%]">
                        {t('boq.variables_value', { defaultValue: 'Value' })}
                      </th>
                      <th className="px-3 py-2 text-left font-semibold">
                        {t('boq.variables_description', { defaultValue: 'Description' })}
                      </th>
                      <th className="w-10 px-2 py-2"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {drafts.map((d, i) => {
                      const err = rowErrors[i];
                      return (
                        <tr key={d.uid} className={err ? 'bg-semantic-error-bg/30' : ''}>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <span className="text-content-tertiary text-xs select-none">$</span>
                              <input
                                type="text"
                                value={d.name}
                                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                  patchRow(d.uid, { name: e.target.value })
                                }
                                placeholder="GFA"
                                className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 font-mono text-sm uppercase focus:border-oe-blue focus:outline-none"
                                aria-invalid={err ? true : undefined}
                              />
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={d.type}
                              onChange={(e) =>
                                patchRow(d.uid, { type: e.target.value as BOQVariable['type'] })
                              }
                              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm focus:border-oe-blue focus:outline-none"
                            >
                              <option value="number">number</option>
                              <option value="text">text</option>
                              <option value="date">date</option>
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type={d.type === 'date' ? 'date' : d.type === 'number' ? 'number' : 'text'}
                              step={d.type === 'number' ? 'any' : undefined}
                              value={d.value}
                              onChange={(e) => patchRow(d.uid, { value: e.target.value })}
                              placeholder={d.type === 'number' ? '1500' : ''}
                              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm focus:border-oe-blue focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="text"
                              value={d.description}
                              onChange={(e) => patchRow(d.uid, { description: e.target.value })}
                              placeholder={t('boq.variables_description_placeholder', {
                                defaultValue: 'Optional note',
                              })}
                              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm focus:border-oe-blue focus:outline-none"
                            />
                          </td>
                          <td className="px-2 py-2">
                            <button
                              type="button"
                              onClick={() => deleteRow(d.uid)}
                              aria-label={t('common.delete', { defaultValue: 'Delete' })}
                              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg"
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                {/* Per-row errors live underneath, indexed by row id */}
                {rowErrors.some((e) => e) && (
                  <div className="border-t border-border-light bg-semantic-error-bg/40 px-3 py-2 text-xs text-semantic-error space-y-0.5">
                    {drafts.map((d, i) =>
                      rowErrors[i] ? (
                        <div key={d.uid} className="flex items-center gap-1.5">
                          <AlertCircle size={12} />
                          <span className="font-mono">${d.name || '???'}</span>
                          <span>—</span>
                          <span>{rowErrors[i]}</span>
                        </div>
                      ) : null,
                    )}
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={addRow}
              disabled={drafts.length >= MAX_VARIABLES}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border-light bg-surface-secondary/30 px-4 py-2 text-sm font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={14} />
              {t('boq.variables_add', { defaultValue: 'Add variable' })}
            </button>

            {overCap && (
              <p className="text-xs text-semantic-error">
                {t('boq.variables_cap', {
                  defaultValue: 'Maximum {{cap}} variables per BOQ.',
                  cap: MAX_VARIABLES,
                })}
              </p>
            )}

            {serverError && (
              <div className="flex items-start gap-2 rounded-xl bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{serverError}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border-light bg-surface-secondary/30 px-5 py-3">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              type="submit"
              disabled={hasErrors || overCap || replaceMutation.isPending}
            >
              {replaceMutation.isPending
                ? t('common.saving', { defaultValue: 'Saving…' })
                : t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
