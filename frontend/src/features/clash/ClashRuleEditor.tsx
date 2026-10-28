// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashRuleEditor — Wave A4 modal panel listing the run's per-pair
// tolerance overrides. The coordinator can add / edit / disable / delete
// rows; saving sends the full list as a PATCH (idempotent — first match
// wins, so order matters; new rows go to the bottom).
//
// Scope: minimal table, no validation extras beyond what the schema
// already enforces (pair non-empty, tolerance in [0, 10]). Engine
// integration (applying the rules on the next run) lives in the
// backend; this component is pure CRUD.

import { useEffect, useId, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Trash2, Plus } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import { clashApi, type ClashRule } from './api';

export interface ClashRuleEditorProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  runId: string;
}

function _emptyRule(): ClashRule {
  return {
    id: `rule-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    discipline_a: '',
    discipline_b: '',
    tolerance_m: 0.05,
    severity_override: null,
    enabled: true,
  };
}

export function ClashRuleEditor({
  open,
  onClose,
  projectId,
  runId,
}: ClashRuleEditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const tableId = useId();

  const { data, isLoading } = useQuery<ClashRule[]>({
    queryKey: ['clash', projectId, runId, 'rules'],
    queryFn: () => clashApi.listRules(projectId, runId),
    enabled: open && !!projectId && !!runId,
  });

  // Editor state — initial value seeded once from the server payload,
  // then user-controlled until Save.
  const [draft, setDraft] = useState<ClashRule[]>([]);
  useEffect(() => {
    if (open && data) setDraft(data.map((r) => ({ ...r })));
  }, [open, data]);

  const save = useMutation({
    mutationFn: () => clashApi.replaceRules(projectId, runId, draft),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clash', projectId, runId, 'rules'] });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
      addToast({
        type: 'success',
        title: t('clash.rules.saved', { defaultValue: 'Rules saved' }),
      });
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('clash.rules.save_failed', { defaultValue: 'Save failed' }),
        message: (err as Error).message,
      });
    },
  });

  const canSave = useMemo(
    () =>
      draft.every(
        (r) =>
          r.discipline_a.trim() &&
          r.discipline_b.trim() &&
          r.tolerance_m >= 0 &&
          r.tolerance_m <= 10,
      ),
    [draft],
  );

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('clash.rules.title', { defaultValue: 'Rule editor' })}
      subtitle={t('clash.rules.subtitle', {
        defaultValue:
          'Per-discipline-pair tolerance overrides. First matching enabled rule wins.',
      })}
      size="xl"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!canSave || save.isPending}
            onClick={() => save.mutate()}
            loading={save.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <div className="py-6 text-center text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : (
        <div className="space-y-3">
          <table
            id={tableId}
            className="w-full text-sm border-collapse"
            data-testid="clash-rule-editor-table"
          >
            <thead>
              <tr className="text-left text-content-tertiary text-xs uppercase">
                <th className="px-2 py-2">{t('clash.rules.disc_a', { defaultValue: 'Discipline A' })}</th>
                <th className="px-2 py-2">{t('clash.rules.disc_b', { defaultValue: 'Discipline B' })}</th>
                <th className="px-2 py-2 w-32">
                  {t('clash.rules.tolerance', { defaultValue: 'Tolerance (m)' })}
                </th>
                <th className="px-2 py-2 w-28">
                  {t('clash.rules.severity', { defaultValue: 'Severity' })}
                </th>
                <th className="px-2 py-2 w-20 text-center">
                  {t('clash.rules.enabled', { defaultValue: 'Enabled' })}
                </th>
                <th className="px-2 py-2 w-12" />
              </tr>
            </thead>
            <tbody>
              {draft.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-2 py-6 text-center text-content-tertiary"
                  >
                    {t('clash.rules.empty', {
                      defaultValue:
                        'No rules yet - add one to override the run-wide tolerance for a discipline pair.',
                    })}
                  </td>
                </tr>
              ) : (
                draft.map((r, i) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-2 py-2">
                      <input
                        type="text"
                        aria-label={t('clash.rules.disc_a', {
                          defaultValue: 'Discipline A',
                        })}
                        className="w-full rounded border border-border px-2 py-1 bg-surface-primary"
                        value={r.discipline_a}
                        onChange={(e) =>
                          setDraft((d) =>
                            d.map((x, j) =>
                              i === j
                                ? { ...x, discipline_a: e.target.value }
                                : x,
                            ),
                          )
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        type="text"
                        aria-label={t('clash.rules.disc_b', {
                          defaultValue: 'Discipline B',
                        })}
                        className="w-full rounded border border-border px-2 py-1 bg-surface-primary"
                        value={r.discipline_b}
                        onChange={(e) =>
                          setDraft((d) =>
                            d.map((x, j) =>
                              i === j
                                ? { ...x, discipline_b: e.target.value }
                                : x,
                            ),
                          )
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        type="number"
                        min={0}
                        max={10}
                        step={0.001}
                        aria-label={t('clash.rules.tolerance', {
                          defaultValue: 'Tolerance (m)',
                        })}
                        className="w-full rounded border border-border px-2 py-1 bg-surface-primary text-right"
                        value={r.tolerance_m}
                        onChange={(e) =>
                          setDraft((d) =>
                            d.map((x, j) =>
                              i === j
                                ? {
                                    ...x,
                                    tolerance_m:
                                      Number.isFinite(e.target.valueAsNumber)
                                        ? e.target.valueAsNumber
                                        : 0,
                                  }
                                : x,
                            ),
                          )
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        aria-label={t('clash.rules.severity', {
                          defaultValue: 'Severity',
                        })}
                        className="w-full rounded border border-border px-2 py-1 bg-surface-primary"
                        value={r.severity_override ?? ''}
                        onChange={(e) =>
                          setDraft((d) =>
                            d.map((x, j) =>
                              i === j
                                ? {
                                    ...x,
                                    severity_override:
                                      e.target.value === ''
                                        ? null
                                        : (e.target.value as ClashRule['severity_override']),
                                  }
                                : x,
                            ),
                          )
                        }
                      >
                        <option
                          value=""
                          aria-label={t('clash.rules.severity_none', {
                            defaultValue: 'No override',
                          })}
                        >
                          —
                        </option>
                        <option value="critical">critical</option>
                        <option value="high">high</option>
                        <option value="medium">medium</option>
                        <option value="low">low</option>
                      </select>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <input
                        type="checkbox"
                        aria-label={t('clash.rules.enabled', {
                          defaultValue: 'Enabled',
                        })}
                        checked={r.enabled}
                        onChange={(e) =>
                          setDraft((d) =>
                            d.map((x, j) =>
                              i === j ? { ...x, enabled: e.target.checked } : x,
                            ),
                          )
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        onClick={() =>
                          setDraft((d) => d.filter((_, j) => j !== i))
                        }
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="text-content-tertiary hover:text-semantic-error"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <div className="flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setDraft((d) => [...d, _emptyRule()])}
            >
              {t('clash.rules.add', { defaultValue: 'Add rule' })}
            </Button>
          </div>
        </div>
      )}
    </WideModal>
  );
}
