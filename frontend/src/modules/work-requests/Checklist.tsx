// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The department's sign-off list on one request: "4 of 7", a box per
 * item, the required ones flagged, and - when a closing stage was
 * refused - the server's own sentence naming what is still outstanding.
 *
 * Two rules that are easy to get wrong and expensive to get wrong:
 *
 *  - only the DEPARTMENT side ticks. The requester reads the list; the
 *    workshop signs it. A reader who is not on that side gets the boxes
 *    disabled with one line saying why, not boxes that tick and then
 *    silently 403.
 *  - the refusal is the SERVER's. A required item might be gated by a
 *    rule this screen cannot see, so the 409's message is printed
 *    verbatim; the locally-known outstanding items are listed under it as
 *    a convenience, never in place of it.
 *
 * The LIST itself is editable by a manager or the department's lead - a
 * separate right from ticking - behind an explicit "Edit checklist"
 * toggle, so the everyday reader sees a list to sign, not a form. Those
 * endpoints landed after the rest of the module, so every one of them
 * degrades: a 404/405 turns editing off and says so, once, instead of
 * leaving buttons that cannot work.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, GripVertical, Plus, RotateCcw, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { qConfirm } from '../comms-intelligence/qAsk';
import {
  addChecklistItem,
  deleteChecklistItem,
  patchChecklistItem,
  reorderChecklist,
  resetChecklist,
  type ChecklistItem,
  type UserRow,
  type WorkRequest,
} from './api';
import { useWrMutation } from './hooks';
import { checklistOf, checklistProgress, errorText, fmtDay, isModuleMissing, nameOfUser, outstandingRequired } from './lib';

export function ChecklistProgress({ req }: { req: Pick<WorkRequest, 'checklist' | 'checklist_done' | 'checklist_total'> }) {
  const { t } = useTranslation();
  const { done, total } = checklistProgress(req);
  if (total === 0) return null;
  const pct = Math.round((done / total) * 100);
  return (
    <span
      className="wr-check-prog"
      data-testid="wr-checklist-progress"
      title={t('wr.checklist_hint', { defaultValue: '{{done}} of {{total}} checklist items signed off', done, total })}
    >
      <span className="wr-bar" role="img" aria-label={t('wr.checklist_progress', { defaultValue: '{{done}} of {{total}}', done, total })}>
        <i className="lg" style={{ width: `${pct}%` }} />
      </span>
      {t('wr.checklist_progress', { defaultValue: '{{done}} of {{total}}', done, total })}
    </span>
  );
}

/**
 * Who signed one item off, and when - "Robin Placeholder · 03 Sep 2026".
 *
 * `by` is a user ID on the wire. Resolved through the users the module
 * already loads for its pickers; an id it cannot place shows nothing at
 * all, because the alternative was a row reading
 * "e58c94e2-3258-4725-be3f-499ffc07eb58 · Sep 03, 2026" as if that were
 * a colleague. The date goes through the app's own `fmtDate`, like every
 * other date on the screen.
 */
function SignedOff({ item, users }: { item: ChecklistItem; users: UserRow[] }) {
  const { t } = useTranslation();
  const who = nameOfUser(users, item.by);
  const when = item.at ? fmtDay(item.at) : null;
  if (!who && !when) return null;
  return (
    <span className="by" title={t('wr.checklist_signed', { defaultValue: 'Signed off' })}>
      {[who, when].filter(Boolean).join(' · ')}
    </span>
  );
}

export function Checklist({
  req,
  canTick,
  canEdit = false,
  users = [],
  busyKey,
  refusal,
  onTick,
  onDismissRefusal,
}: {
  req: WorkRequest;
  /** The reader is on the department side (see `onDepartmentSide`). */
  canTick: boolean;
  /** The reader may edit the LIST - manager, or the department's lead. */
  canEdit?: boolean;
  /** For turning a tick's user id into a person (see `nameOfUser`). */
  users?: UserRow[];
  /** The item mid-flight, so only its own box goes quiet. */
  busyKey?: string | null;
  /** The server's words from a refused closing move, if there was one. */
  refusal?: string | null;
  onTick: (item: ChecklistItem, done: boolean) => void;
  onDismissRefusal?: () => void;
}) {
  const { t } = useTranslation();
  const items = checklistOf(req);
  const outstanding = outstandingRequired(req);

  const [editing, setEditing] = useState(false);
  /** An endpoint answered 404/405: this server has no checklist editing. */
  const [unavailable, setUnavailable] = useState(false);
  /** The server's refusal, against the row it belongs to (`''` = the section). */
  const [rowError, setRowError] = useState<{ key: string; text: string } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [newLabel, setNewLabel] = useState('');
  const [newRequired, setNewRequired] = useState(false);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const addRef = useRef<HTMLInputElement>(null);

  // An edit mode left open on a request whose list has gone (a reset, a
  // type change) is a form over nothing.
  useEffect(() => {
    if (items.length === 0 && !canEdit) setEditing(false);
  }, [items.length, canEdit]);

  const fail = (key: string) => (err: unknown) => {
    if (isModuleMissing(err)) {
      setUnavailable(true);
      setEditing(false);
      setRowError(null);
      return;
    }
    setRowError({ key, text: errorText(err) });
  };

  const addM = useWrMutation((body: { label: string; required: boolean }) => addChecklistItem(req.id, body), {
    onSuccess: () => {
      setNewLabel('');
      setNewRequired(false);
      setRowError(null);
      addRef.current?.focus();
    },
    onError: fail(''),
  });
  const patchM = useWrMutation(({ key, body }: { key: string; body: { label?: string; required?: boolean } }) => patchChecklistItem(req.id, key, body), {
    onSuccess: () => setRowError(null),
    onError: (err, args) => fail(args.key)(err),
  });
  const removeM = useWrMutation((key: string) => deleteChecklistItem(req.id, key), {
    onSuccess: () => setRowError(null),
    onError: (err, key) => fail(key)(err),
  });
  const orderM = useWrMutation((keys: string[]) => reorderChecklist(req.id, keys), {
    onSuccess: () => setRowError(null),
    onError: fail(''),
  });
  const resetM = useWrMutation<void, WorkRequest>(() => resetChecklist(req.id), {
    onSuccess: () => {
      setRowError(null);
      setDrafts({});
    },
    onError: fail(''),
  });
  const editBusy = addM.isPending || patchM.isPending || removeM.isPending || orderM.isPending || resetM.isPending;

  const keys = useMemo(() => items.map((i) => i.key), [items]);

  const move = (key: string, delta: number) => {
    const from = keys.indexOf(key);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= keys.length) return;
    const next = [...keys];
    next.splice(to, 0, ...next.splice(from, 1));
    void orderM.mutateAsync(next).catch(() => undefined);
  };

  const dropOn = (key: string) => {
    if (!dragKey || dragKey === key) return;
    const next = keys.filter((k) => k !== dragKey);
    next.splice(next.indexOf(key), 0, dragKey);
    setDragKey(null);
    void orderM.mutateAsync(next).catch(() => undefined);
  };

  const commitLabel = (item: ChecklistItem) => {
    const draft = (drafts[item.key] ?? item.label).trim();
    setDrafts((d) => {
      const next = { ...d };
      delete next[item.key];
      return next;
    });
    // An emptied label is a slip, not an instruction to blank the line.
    if (!draft || draft === item.label) return;
    void patchM.mutateAsync({ key: item.key, body: { label: draft } }).catch(() => undefined);
  };

  const doReset = async () => {
    const ok = await qConfirm(
      t('wr.checklist_reset_q', {
        defaultValue: 'Replace this checklist with the standard list for this request type? Lines added here are removed, and every tick is cleared.',
      }),
    );
    if (ok) void resetM.mutateAsync().catch(() => undefined);
  };

  if (items.length === 0 && !canEdit) {
    return (
      <span className="wr-hint" data-testid="wr-checklist-empty">
        {t('wr.checklist_none', { defaultValue: 'This request type has no checklist. Add one to the request type in Manage departments.' })}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="wr-checklist">
      {refusal && (
        <div className="wr-banner err" role="alert" data-testid="wr-checklist-refusal">
          <div className="flex-1">
            {/* The server's sentence, verbatim - it names the items, and it
                knows rules this screen does not. */}
            <b>{t('wr.checklist_blocked', { defaultValue: 'That stage closes the request, and the checklist is not finished.' })}</b>
            <div className="mt-1">{refusal}</div>
            {outstanding.length > 0 && (
              <ul className="mt-1 list-disc pl-4">
                {outstanding.map((i) => (
                  <li key={i.key}>{i.label}</li>
                ))}
              </ul>
            )}
          </div>
          {onDismissRefusal && (
            <button type="button" className="wr-btn-quiet" onClick={onDismissRefusal} aria-label={t('common.close', { defaultValue: 'Close' })}>
              ✕
            </button>
          )}
        </div>
      )}

      {canEdit && !unavailable && (
        <div className="wr-check-tools">
          <button
            type="button"
            className={clsx('wr-btn-quiet', editing && 'on')}
            aria-pressed={editing}
            onClick={() => {
              setEditing((e) => !e);
              setRowError(null);
            }}
            data-testid="wr-checklist-edit-toggle"
          >
            {editing ? t('wr.checklist_done_editing', { defaultValue: 'Done editing' }) : t('wr.checklist_edit', { defaultValue: 'Edit checklist' })}
          </button>
          {editing && (
            <button type="button" className="wr-btn-quiet" disabled={editBusy} onClick={() => void doReset()} data-testid="wr-checklist-reset">
              <RotateCcw size={11} /> {t('wr.checklist_reset', { defaultValue: 'Reset to the standard list for this type' })}
            </button>
          )}
        </div>
      )}

      {unavailable && (
        <span className="wr-hint" data-testid="wr-checklist-noedit">
          {t('wr.checklist_edit_unavailable', { defaultValue: 'This server does not support editing the checklist yet - it can still be signed off.' })}
        </span>
      )}

      {rowError && rowError.key === '' && (
        <div className="wr-banner err" role="alert" data-testid="wr-checklist-error">
          <span className="flex-1">{rowError.text}</span>
          <button type="button" className="wr-btn-quiet" onClick={() => setRowError(null)} aria-label={t('common.close', { defaultValue: 'Close' })}>
            ✕
          </button>
        </div>
      )}

      <div className={clsx('wr-check', editing && 'editing')} role="group" aria-label={t('wr.sec_checklist', { defaultValue: 'Checklist' })}>
        {items.map((i, idx) => {
          const id = `wr-chk-${req.id}-${i.key}`;
          const err = rowError && rowError.key === i.key ? rowError.text : null;
          if (editing) {
            return (
              <div
                key={i.key}
                className={clsx('wr-check-row edit', dragKey === i.key && 'dragging')}
                draggable
                onDragStart={() => setDragKey(i.key)}
                onDragEnd={() => setDragKey(null)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  dropOn(i.key);
                }}
                data-testid={`wr-chk-edit-${i.key}`}
              >
                <span className="grip" aria-hidden>
                  <GripVertical size={12} />
                </span>
                <input
                  className="wr-inl flex-1"
                  value={drafts[i.key] ?? i.label}
                  aria-label={t('wr.checklist_item_label', { defaultValue: 'Checklist item' })}
                  onChange={(e) => setDrafts((d) => ({ ...d, [i.key]: e.target.value }))}
                  onBlur={() => commitLabel(i)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                    if (e.key === 'Escape') {
                      setDrafts((d) => {
                        const next = { ...d };
                        delete next[i.key];
                        return next;
                      });
                      (e.target as HTMLInputElement).blur();
                    }
                  }}
                />
                <label className="wr-tog" title={t('wr.checklist_required', { defaultValue: 'Required before the request can be closed' })}>
                  <input
                    type="checkbox"
                    checked={i.required}
                    disabled={editBusy}
                    onChange={(e) => void patchM.mutateAsync({ key: i.key, body: { required: e.target.checked } }).catch(() => undefined)}
                    data-testid={`wr-chk-req-${i.key}`}
                  />
                  {t('wr.required', { defaultValue: 'required' })}
                </label>
                {i.source === 'request' && (
                  <span className="src" title={t('wr.checklist_added_here_hint', { defaultValue: 'Added on this request - not part of the standard list for its type' })}>
                    {t('wr.checklist_added_here', { defaultValue: 'added here' })}
                  </span>
                )}
                <button
                  type="button"
                  className="wr-btn-quiet"
                  disabled={editBusy || idx === 0}
                  aria-label={t('wr.checklist_move_up', { defaultValue: 'Move up' })}
                  onClick={() => move(i.key, -1)}
                >
                  <ChevronUp size={11} />
                </button>
                <button
                  type="button"
                  className="wr-btn-quiet"
                  disabled={editBusy || idx === items.length - 1}
                  aria-label={t('wr.checklist_move_down', { defaultValue: 'Move down' })}
                  onClick={() => move(i.key, 1)}
                >
                  <ChevronDown size={11} />
                </button>
                <button
                  type="button"
                  className="wr-btn-quiet danger"
                  disabled={editBusy}
                  aria-label={t('wr.checklist_remove', { defaultValue: 'Remove item' })}
                  onClick={() => void removeM.mutateAsync(i.key).catch(() => undefined)}
                  data-testid={`wr-chk-del-${i.key}`}
                >
                  <Trash2 size={11} />
                </button>
                {/* The server refuses to delete a line somebody has already
                    ticked - that tick is a record. Its sentence lands on
                    the row it is about, not in a toast over the drawer. */}
                {err && (
                  <span className="rowerr" role="alert" data-testid={`wr-chk-err-${i.key}`}>
                    {err}
                  </span>
                )}
              </div>
            );
          }
          return (
            <label key={i.key} className={clsx('wr-check-row', i.done && 'done')} htmlFor={id}>
              <input
                id={id}
                type="checkbox"
                checked={i.done}
                disabled={!canTick || busyKey === i.key}
                onChange={(e) => onTick(i, e.target.checked)}
                data-testid={`wr-chk-${i.key}`}
              />
              <span className="lbl">{i.label}</span>
              {i.required && (
                <span className="req" title={t('wr.checklist_required', { defaultValue: 'Required before the request can be closed' })}>
                  {t('wr.required', { defaultValue: 'required' })}
                </span>
              )}
              {i.done && <SignedOff item={i} users={users} />}
            </label>
          );
        })}
      </div>

      {editing && !unavailable && (
        <div className="wr-check-add" data-testid="wr-checklist-add">
          <Plus size={12} aria-hidden />
          <input
            ref={addRef}
            className="wr-inl flex-1"
            value={newLabel}
            placeholder={t('wr.checklist_add_ph', { defaultValue: 'Add an item - what has to be signed off' })}
            aria-label={t('wr.checklist_add', { defaultValue: 'Add item' })}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newLabel.trim()) void addM.mutateAsync({ label: newLabel.trim(), required: newRequired }).catch(() => undefined);
            }}
          />
          <label className="wr-tog" title={t('wr.checklist_required', { defaultValue: 'Required before the request can be closed' })}>
            <input type="checkbox" checked={newRequired} onChange={(e) => setNewRequired(e.target.checked)} />
            {t('wr.required', { defaultValue: 'required' })}
          </label>
          <button
            type="button"
            className="wr-btn-quiet on"
            disabled={!newLabel.trim() || editBusy}
            onClick={() => void addM.mutateAsync({ label: newLabel.trim(), required: newRequired }).catch(() => undefined)}
          >
            {t('wr.checklist_add', { defaultValue: 'Add item' })}
          </button>
        </div>
      )}

      {editing && (
        <span className="wr-hint">
          {t('wr.checklist_edit_hint', {
            defaultValue: 'Lines added here belong to this request only; the rest come from its request type. A line somebody has already signed off cannot be removed.',
          })}
        </span>
      )}

      {!editing && !canTick && (
        <span className="wr-hint" data-testid="wr-checklist-readonly">
          {t('wr.checklist_readonly', { defaultValue: 'Only the department doing the work signs these off.' })}
        </span>
      )}
      {!editing && canTick && outstanding.length > 0 && (
        <span className="wr-hint">
          {t('wr.checklist_outstanding', {
            defaultValue_one: '{{count}} required item still to sign off before this can be closed.',
            defaultValue_other: '{{count}} required items still to sign off before this can be closed.',
            defaultValue: '{{count}} required items still to sign off before this can be closed.',
            count: outstanding.length,
          })}
        </span>
      )}
    </div>
  );
}
