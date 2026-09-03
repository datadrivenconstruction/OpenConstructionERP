// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The List view's bulk action bar: tick a set of rows, then assign,
 * re-stage, re-date, re-prioritise or template them in one write.
 *
 * The whole point of this file is the LAST paragraph of the contract:
 * `POST /requests/bulk` answers `{updated, refused}`, and partial success
 * is the normal case - a stage that only one of two departments has, a
 * closing move blocked by an unticked required item, a request somebody
 * else closed while the boxes were being ticked. A bare "Done!" toast
 * over eight requests of which two did not move is the kind of lie that
 * costs a delivery date, so the bar reports both halves, names the
 * refused references, and prints the server's reason for each.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarDays, Check, Copy, Flag, Layers, Users, X } from 'lucide-react';
import type { BulkPatch, BulkResult, Department, Priority, WorkRequest } from './api';
import { PRIORITIES } from './api';
import { useMenu, type MenuItem } from '../comms-intelligence/ContextMenu';
import { Picker, type PickAnchor } from './Pickers';
import { Avatar } from './bits';
import { useUsers } from './hooks';
import { PRIORITY_LABEL, deptOf, memberPool, stagesOf } from './lib';
import { fmtList } from '@/shared/lib/formatters';

export interface BulkOutcome extends BulkResult {
  /** What was asked for, so the banner can say what did not happen. */
  what: string;
}

export function BulkBar({
  selected,
  departments,
  busy,
  outcome,
  onApply,
  onClear,
  onDismiss,
}: {
  selected: WorkRequest[];
  departments: Department[];
  busy?: boolean;
  outcome: BulkOutcome | null;
  onApply: (patch: BulkPatch, what: string) => void;
  onClear: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const menu = useMenu();
  const users = useUsers();
  const [picker, setPicker] = useState<PickAnchor | null>(null);
  const [dueOpen, setDueOpen] = useState(false);
  const [due, setDue] = useState('');

  /**
   * The stages worth offering: the ones EVERY selected request's
   * department has. A stage only one department carries would be offered
   * as a move that is guaranteed to be refused for the rest of the
   * selection - the server would say so, honestly, eight times over, but
   * a menu that only lists moves that can work is better than a menu that
   * teaches the reader to expect refusals.
   */
  const stages = useMemo(() => {
    const depts = Array.from(new Set(selected.map((r) => r.department))).map((k) => deptOf(departments, k));
    if (depts.length === 0 || depts.some((d) => !d)) return [];
    const lists = depts.map((d) => stagesOf(d));
    const first = lists[0] ?? [];
    return first.filter((s) => lists.every((l) => l.some((x) => x.key === s.key)));
  }, [selected, departments]);

  /** Everyone the selection's departments offer, de-duplicated. */
  const pool = useMemo(() => {
    const all = users.data ?? [];
    const depts = Array.from(new Set(selected.map((r) => r.department))).map((k) => deptOf(departments, k));
    const seen = new Map<string, (typeof all)[number]>();
    for (const d of depts) for (const u of memberPool(d, all)) seen.set(u.id, u);
    return Array.from(seen.values());
  }, [selected, departments, users.data]);

  const n = selected.length;
  const allTemplates = n > 0 && selected.every((r) => r.is_template === true);
  const refByIdMap = useMemo(() => new Map(selected.map((r) => [r.id, r.reference])), [selected]);

  if (n === 0 && !outcome) return null;

  return (
    <>
      {outcome && (
        <div
          className={outcome.refused.length ? 'wr-banner err wr-bulkres' : 'wr-banner ball wr-bulkres'}
          role="status"
          data-testid="wr-bulk-result"
        >
          <div className="flex-1">
            <b>
              {/* Both halves, always. "6 updated, 2 refused" - never a
                  count of successes with the failures left off. */}
              {outcome.refused.length === 0
                ? t('wr.bulk_all_ok', {
                    defaultValue_one: '{{count}} request updated - {{what}}',
                    defaultValue_other: '{{count}} requests updated - {{what}}',
                    defaultValue: '{{count}} requests updated - {{what}}',
                    count: outcome.updated.length,
                    what: outcome.what,
                  })
                : t('wr.bulk_partial', {
                    defaultValue: '{{ok}} updated, {{bad}} refused - {{what}}',
                    ok: outcome.updated.length,
                    bad: outcome.refused.length,
                    what: outcome.what,
                  })}
            </b>
            {outcome.refused.length > 0 && (
              <ul>
                {outcome.refused.map((r) => (
                  <li key={r.id}>
                    <b className="wr-mono">{refByIdMap.get(r.id) ?? r.id}</b> — {r.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" className="wr-btn-quiet" onClick={onDismiss} aria-label={t('common.close', { defaultValue: 'Close' })}>
            ✕
          </button>
        </div>
      )}

      {n > 0 && (
        <div className="wr-bulkbar" role="group" aria-label={t('wr.bulk_actions', { defaultValue: 'Bulk actions' })} data-testid="wr-bulkbar">
          <span className="n" data-testid="wr-bulk-count">
            {t('wr.bulk_selected', {
              defaultValue_one: '{{count}} selected',
              defaultValue_other: '{{count}} selected',
              defaultValue: '{{count}} selected',
              count: n,
            })}
          </span>

          <button type="button" className="wr-btn-quiet" disabled={busy} onClick={(e) => setPicker(e.currentTarget)} data-testid="wr-bulk-assign">
            <Users size={11} /> {t('wr.bulk_assign', { defaultValue: 'Assign…' })}
          </button>

          <button
            type="button"
            className="wr-btn-quiet"
            disabled={busy || stages.length === 0}
            title={stages.length === 0 ? t('wr.bulk_no_common_stage', { defaultValue: 'The selected requests are in departments with no stage in common.' }) : undefined}
            onClick={(e) =>
              menu.openBelow(
                e.currentTarget,
                stages.map<MenuItem>((s) => ({
                  label: s.name,
                  color: s.colour,
                  note: s.closes ? t('wr.closes', { defaultValue: 'closes' }) : undefined,
                  onClick: () => onApply({ stage: s.key }, t('wr.bulk_what_stage', { defaultValue: 'move to {{stage}}', stage: s.name })),
                })),
                { head: t('wr.move_to_stage', { defaultValue: 'Move to stage' }) },
              )
            }
            data-testid="wr-bulk-stage"
          >
            <Layers size={11} /> {t('wr.bulk_stage', { defaultValue: 'Move to stage…' })}
          </button>

          {dueOpen ? (
            <span className="inline-flex items-center gap-1.5">
              {/* The browser's own picker, like every other date in the
                  module - a typed YYYY-MM-DD is the one date format this
                  app never asks anybody for. */}
              <input
                type="date"
                className="wr-in"
                style={{ width: 'auto' }}
                value={due}
                autoFocus
                aria-label={t('wr.bulk_due', { defaultValue: 'Set due date…' })}
                onChange={(e) => setDue(e.target.value)}
                data-testid="wr-bulk-due-input"
              />
              <button
                type="button"
                className="wr-btn-quiet on"
                disabled={busy}
                onClick={() => {
                  setDueOpen(false);
                  onApply(
                    { due_date: due || null },
                    due
                      ? t('wr.bulk_what_due', { defaultValue: 'due {{d}}', d: due })
                      : t('wr.bulk_what_due_clear', { defaultValue: 'due date cleared' }),
                  );
                }}
                data-testid="wr-bulk-due-apply"
              >
                <Check size={11} /> {t('wr.pick_apply', { defaultValue: 'Apply' })}
              </button>
              <button type="button" className="wr-btn-quiet" onClick={() => setDueOpen(false)} aria-label={t('common.cancel', { defaultValue: 'Cancel' })}>
                <X size={11} />
              </button>
            </span>
          ) : (
            <button type="button" className="wr-btn-quiet" disabled={busy} onClick={() => setDueOpen(true)} data-testid="wr-bulk-due">
              <CalendarDays size={11} /> {t('wr.bulk_due', { defaultValue: 'Set due date…' })}
            </button>
          )}

          <button
            type="button"
            className="wr-btn-quiet"
            disabled={busy}
            onClick={(e) =>
              menu.openBelow(
                e.currentTarget,
                PRIORITIES.map<MenuItem>((p) => ({
                  label: t(`wr.priority.${p}`, { defaultValue: PRIORITY_LABEL[p] }),
                  onClick: () =>
                    onApply({ priority: p as Priority }, t('wr.bulk_what_priority', { defaultValue: 'priority {{p}}', p: t(`wr.priority.${p}`, { defaultValue: PRIORITY_LABEL[p] }) })),
                })),
                { head: t('wr.priority_lbl', { defaultValue: 'Priority' }) },
              )
            }
            data-testid="wr-bulk-priority"
          >
            <Flag size={11} /> {t('wr.bulk_priority', { defaultValue: 'Set priority…' })}
          </button>

          <button
            type="button"
            className="wr-btn-quiet"
            disabled={busy}
            onClick={() =>
              onApply(
                { is_template: !allTemplates },
                allTemplates ? t('wr.bulk_what_untemplate', { defaultValue: 'no longer templates' }) : t('wr.bulk_what_template', { defaultValue: 'marked as templates' }),
              )
            }
            data-testid="wr-bulk-template"
          >
            <Copy size={11} />
            {allTemplates ? t('wr.bulk_untemplate', { defaultValue: 'Unmark template' }) : t('wr.bulk_template', { defaultValue: 'Mark template' })}
          </button>

          <span className="sp" />
          <button type="button" className="wr-btn-quiet" onClick={onClear} data-testid="wr-bulk-clear">
            {t('wr.bulk_clear', { defaultValue: 'Clear' })}
          </button>
        </div>
      )}

      {menu.element}
      {picker && (
        <Picker
          anchor={picker}
          multi
          options={pool.map((u) => ({ id: u.id, label: u.full_name || u.email, sub: u.email, lead: <Avatar person={{ id: u.id, name: u.full_name || u.email }} size={18} /> }))}
          selected={[]}
          placeholder={t('wr.bulk_assign_ph', { defaultValue: 'Assign these to…' })}
          onClose={() => setPicker(null)}
          onChange={(ids) =>
            onApply(
              { assignee_ids: ids },
              t('wr.bulk_what_assign', {
                defaultValue: 'assigned to {{who}}',
                who: fmtList(ids.map((id) => pool.find((u) => u.id === id)?.full_name || id)) || t('wr.nobody', { defaultValue: 'nobody' }),
              }),
            )
          }
        />
      )}
    </>
  );
}
