// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * WorkflowEditor — the structured editor for a register item's remaining
 * workflow.
 *
 * It replaces the "one step per line, ⛔ for a gate" textarea. The rows
 * mirror the Team Standup configurators (grip, name, type, move, delete)
 * and the rules mirror the server's `configure_steps`, which is the rail:
 *
 *   - finished steps are history and are shown locked;
 *   - a step still on the list is KEPT by name (its type is fixed);
 *   - a hold point (gate) or a decision (route) is never deleted — taking
 *     one off marks it "coming off this workflow" and asks why, once, for
 *     all of them;
 *   - a NEW decision carries its own paths, or the save is refused.
 *
 *     const saved = await openWorkflowEditor({ item, spec, onSaved });
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useTranslation } from 'react-i18next';

import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { qConfirm } from './qAsk';
import {
  configureSteps,
  type KindSpec,
  type RegisterItemRow,
  type RemainingStep,
  type StepRow,
} from './registers-api';
import './ci.css';
import './workflow-editor.css';

export type RowType = 'step' | 'gate' | 'route';

export interface BranchDraft {
  key: string;
  label: string;
  /** The step names this path adds, one per line. */
  steps: string;
}

export interface EditRow {
  key: string;
  /** Came off the item's open steps: the server keeps it by name, so its
   *  type is fixed here and a gate/route can only be RETIRED, not dropped. */
  existing: boolean;
  type: RowType;
  name: string;
  owner: string;
  branches: BranchDraft[];
  /** An existing gate/route marked to come off this workflow. */
  retiring: boolean;
}

export interface WorkflowEditorArgs {
  item: RegisterItemRow;
  spec: KindSpec | undefined;
  onSaved: () => void;
}

let keySeq = 0;
const nextKey = (): string => `wfe-${++keySeq}`;

type LibraryAction = KindSpec['actions'][number];

function branchesToDrafts(rec: Record<string, string[]> | undefined): BranchDraft[] {
  return Object.entries(rec ?? {}).map(([label, steps]) => ({
    key: nextKey(),
    label,
    steps: (steps ?? []).join('\n'),
  }));
}

function draftsToRecord(drafts: BranchDraft[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const b of drafts) {
    const label = b.label.trim();
    if (!label) continue;
    out[label] = b.steps
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return out;
}

/** The to-do rows an item opens with: its open steps, in position order. */
export function rowsFromItem(item: RegisterItemRow): EditRow[] {
  return item.steps
    .filter((s) => s.state === 'open')
    .sort((a, b) => a.position - b.position)
    .map((s) => ({
      key: nextKey(),
      existing: true,
      type: s.type,
      name: s.name,
      owner: s.owner ?? '',
      branches: [],
      retiring: false,
    }));
}

function rowFromAction(a: LibraryAction, type?: RowType): EditRow {
  const t = type ?? ((a.t === 'gate' || a.t === 'route' ? a.t : 'step') as RowType);
  return {
    key: nextKey(),
    existing: false,
    type: t,
    name: a.name,
    owner: a.owner ?? '',
    branches: t === 'route' ? branchesToDrafts(a.branches) : [],
    retiring: false,
  };
}

function blankRow(type: RowType): EditRow {
  return { key: nextKey(), existing: false, type, name: '', owner: '', branches: [], retiring: false };
}

/** What goes to the server: the rows still on the list, in order. */
export function payloadOf(rows: EditRow[]): RemainingStep[] {
  return rows
    .filter((r) => !r.retiring)
    .map((r) => {
      const entry: RemainingStep = { name: r.name.trim(), type: r.type };
      if (r.owner.trim()) entry.owner = r.owner.trim();
      if (!r.existing && r.type === 'route') entry.branches = draftsToRecord(r.branches);
      return entry;
    });
}

type T = (key: string, opts: { defaultValue: string } & Record<string, unknown>) => string;

/** The first thing wrong with the draft, or '' when it can be sent. */
export function validateRows(rows: EditRow[], reason: string, t: T): string {
  const active = rows.filter((r) => !r.retiring);
  if (!active.length) {
    return t('ci.wfe_need_one', { defaultValue: 'A workflow needs at least one step still to do' });
  }
  if (active.some((r) => !r.name.trim())) {
    return t('ci.wfe_empty_name', { defaultValue: 'Every step needs a name' });
  }
  const seen = new Set<string>();
  for (const r of active) {
    const k = r.name.trim().toLowerCase();
    if (seen.has(k)) {
      return t('ci.wfe_dup_name', {
        defaultValue: 'Two steps share the name "{{name}}" — steps are matched by name, so each needs its own',
        name: r.name.trim(),
      });
    }
    seen.add(k);
  }
  for (const r of active) {
    if (!r.existing && r.type === 'route' && !Object.keys(draftsToRecord(r.branches)).length) {
      return t('ci.wfe_need_branch', {
        defaultValue: 'The decision "{{name}}" needs at least one path',
        name: r.name.trim(),
      });
    }
  }
  if (rows.some((r) => r.retiring) && !reason.trim()) {
    return t('ci.wfe_need_reason', { defaultValue: 'Say why these hold points are coming off this job' });
  }
  return '';
}

function move<X>(list: X[], from: number, to: number): X[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = list.slice();
  const [it] = next.splice(from, 1);
  next.splice(to, 0, it as X);
  return next;
}

const TYPE_ICON: Record<RowType, string> = { step: '', gate: '⛔', route: '🔀' };

/** `ConfigureStepsRequest.retire_reason` is capped at 300 on the server. */
export const REASON_MAX = 300;

// ── The dialog ──────────────────────────────────────────────────────────

export function WorkflowEditorDialog({
  item,
  spec,
  onSaved,
  resolve,
}: WorkflowEditorArgs & { resolve: (saved: boolean) => void }) {
  const { t } = useTranslation();
  const uid = useId();

  const [rows, setRows] = useState<EditRow[]>(() => rowsFromItem(item));
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showAllDone, setShowAllDone] = useState(false);
  const [libOpen, setLibOpen] = useState(false);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);
  // While a qConfirm is up (it listens to the same window keys) our
  // Escape must stay out of the way.
  const confirmingRef = useRef(false);
  const nameRefs = useRef(new Map<string, HTMLInputElement>());
  const libRef = useRef<HTMLDivElement>(null);

  const typeLabel = useCallback(
    (type: RowType): string =>
      type === 'gate'
        ? t('ci.wfe_gate', { defaultValue: 'Gate' })
        : type === 'route'
          ? t('ci.wfe_decision', { defaultValue: 'Decision' })
          : t('ci.wfe_step', { defaultValue: 'Step' }),
    [t],
  );

  const done = useMemo<StepRow[]>(
    () => item.steps.filter((s) => s.state !== 'open').sort((a, b) => a.position - b.position),
    [item.steps],
  );
  const doneNames = useMemo(() => new Set(done.map((s) => s.name)), [done]);
  const actions = useMemo<LibraryAction[]>(() => spec?.actions ?? [], [spec]);
  const namesByType = useMemo(() => {
    const out: Record<RowType, string[]> = { step: [], gate: [], route: [] };
    for (const a of actions) {
      const k: RowType = a.t === 'gate' || a.t === 'route' ? a.t : 'step';
      if (!out[k].includes(a.name)) out[k].push(a.name);
    }
    return out;
  }, [actions]);
  const owners = useMemo(() => {
    const set = new Set<string>();
    for (const f of [...(spec?.flow ?? []), ...actions]) if (f.owner) set.add(f.owner);
    for (const s of item.steps) if (s.owner) set.add(s.owner);
    return [...set].sort();
  }, [spec, actions, item.steps]);

  const retiring = rows.filter((r) => r.retiring);

  // ── keyboard: Escape cancels (unless something of ours is on top) ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || confirmingRef.current) return;
      e.preventDefault();
      if (libOpen) setLibOpen(false);
      else resolve(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [libOpen, resolve]);

  // The library popup closes on an outside click.
  useEffect(() => {
    if (!libOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!libRef.current?.contains(e.target as Node)) setLibOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [libOpen]);

  const patch = (key: string, fn: (r: EditRow) => EditRow) =>
    setRows((rs) => rs.map((r) => (r.key === key ? fn(r) : r)));

  const focusName = (key: string) => {
    setTimeout(() => nameRefs.current.get(key)?.focus(), 20);
  };

  const append = (row: EditRow) => {
    setRows((rs) => [...rs, row]);
    setError('');
    focusName(row.key);
  };

  const setName = (key: string, name: string) =>
    patch(key, (r) => {
      const next = { ...r, name };
      // A library decision typed by name brings its paths with it.
      if (!r.existing && r.type === 'route') {
        const hit = actions.find((a) => a.t === 'route' && a.name === name.trim() && a.branches);
        if (hit) next.branches = branchesToDrafts(hit.branches);
      }
      return next;
    });

  const setType = (key: string, type: RowType) =>
    patch(key, (r) => {
      if (r.existing) return r;
      const next = { ...r, type };
      if (type === 'route' && !r.branches.length) {
        const hit = actions.find((a) => a.t === 'route' && a.name === r.name.trim() && a.branches);
        next.branches = hit ? branchesToDrafts(hit.branches) : [];
      }
      return next;
    });

  const remove = (key: string) => {
    setError('');
    setRows((rs) => {
      const r = rs.find((x) => x.key === key);
      if (!r) return rs;
      if (r.existing && r.type !== 'step') return rs.map((x) => (x.key === key ? { ...x, retiring: true } : x));
      return rs.filter((x) => x.key !== key);
    });
  };

  const shift = (key: string, dir: -1 | 1) =>
    setRows((rs) => {
      const i = rs.findIndex((r) => r.key === key);
      return move(rs, i, i + dir);
    });

  const reset = async () => {
    if (!spec) return;
    confirmingRef.current = true;
    let ok = false;
    try {
      ok = await qConfirm(
        t('ci.wfe_reset_title', { defaultValue: 'Reset to the standard flow?' }),
        t('ci.wfe_reset_note', {
          defaultValue:
            'The to-do list is replaced with the standard {{kind}} flow, less anything already done. ' +
            'Hold points and decisions that are open now and not in the standard flow will be marked ' +
            'as coming off, and need a reason. Nothing is saved until you press Save.',
          kind: spec.label,
        }),
        t('ci.wfe_reset_ok', { defaultValue: 'Reset the list' }),
      );
    } finally {
      confirmingRef.current = false;
    }
    if (!ok) return;
    setRows((rs) => {
      const openNames = new Set(rs.filter((r) => r.existing).map((r) => r.name));
      const fresh: EditRow[] = spec.flow
        .filter((f) => !doneNames.has(f.name))
        .map((f) => ({ ...rowFromAction(f), existing: openNames.has(f.name) }));
      const listed = new Set(fresh.map((r) => r.name));
      // An open hold point the standard flow does not carry cannot just
      // vanish — the server refuses that — so it stays, marked off.
      const leftovers = rs
        .filter((r) => r.existing && r.type !== 'step' && !listed.has(r.name))
        .map((r) => ({ ...r, retiring: true }));
      return [...fresh, ...leftovers];
    });
    setError('');
  };

  const save = async () => {
    const bad = validateRows(rows, reason, t as unknown as T);
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await configureSteps(item.id, payloadOf(rows), retiring.length ? reason.trim() : undefined);
      onSaved();
      resolve(true);
    } catch (e) {
      // The server's refusal names the problem; keep the dialog and the
      // typing, show it inline.
      setError(getErrorMessage(e));
      setBusy(false);
    }
  };

  // ── drag and drop (HTML5, grip is the handle, row is the target) ──
  const onDragStart = (key: string) => (e: React.DragEvent<HTMLSpanElement>) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', key);
    const rowEl = (e.currentTarget as HTMLElement).closest('.cfg');
    if (rowEl) e.dataTransfer.setDragImage(rowEl, 16, 16);
    setDragKey(key);
  };
  const onDragEnd = () => {
    setDragKey(null);
    setOverKey(null);
  };
  const onDragOver = (key: string) => (e: React.DragEvent<HTMLDivElement>) => {
    if (!dragKey || dragKey === key) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (overKey !== key) setOverKey(key);
  };
  const onDrop = (key: string) => (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const from = dragKey ?? e.dataTransfer.getData('text/plain');
    if (from && from !== key) {
      setRows((rs) => move(rs, rs.findIndex((r) => r.key === from), rs.findIndex((r) => r.key === key)));
    }
    onDragEnd();
  };

  const onNameKey = (key: string) => (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const i = rows.findIndex((r) => r.key === key);
    const next = rows.slice(i + 1).find((r) => !r.retiring);
    if (next) nameRefs.current.get(next.key)?.focus();
  };

  const doneVisible = showAllDone || done.length <= 5 ? done : done.slice(-5);
  const hiddenDone = done.length - doneVisible.length;

  const fmtWho = (s: StepRow): string => {
    const who = s.completed_by_name || s.completed_by || '';
    const when = s.completed_at ? fmtDate(s.completed_at) : '';
    return [who, when].filter(Boolean).join(' · ');
  };

  return (
    <div className="ci" style={{ position: 'fixed', inset: 0, zIndex: 80 }}>
      <div className="ci-scrim" onClick={() => !busy && resolve(false)}>
        <div
          className="ci-wfe"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`${uid}-title`}
          onClick={(e) => e.stopPropagation()}
          data-testid="wfe"
        >
          <div className="wfe-head">
            <h2 id={`${uid}-title`}>{t('ci.wfe_title', { defaultValue: 'Configure the workflow' })}</h2>
            <span className="ref">{item.reference}</span>
            <span className="ttl" title={item.title}>
              {item.title}
            </span>
          </div>

          <div className="wfe-body">
            {/* ── Done ── */}
            <section className="sec" data-testid="wfe-done">
              <h3 className="sec-h">
                {t('ci.wfe_done', { defaultValue: 'Done — history' })}
                <span className="cnt">{done.length}</span>
              </h3>
              {done.length === 0 ? (
                <div className="empty">{t('ci.wfe_nothing_done', { defaultValue: 'Nothing finished yet.' })}</div>
              ) : (
                <>
                  {hiddenDone > 0 && (
                    <button type="button" className="showall" onClick={() => setShowAllDone(true)}>
                      {t('ci.wfe_show_all', {
                        defaultValue: 'show all {{n}} finished steps',
                        n: done.length,
                      })}
                    </button>
                  )}
                  {doneVisible.map((s) => {
                    const skipped = s.state === 'not_required';
                    const retired = skipped && s.override_reason;
                    return (
                      <div
                        key={s.id}
                        className={`done-row ${s.type} ${skipped ? 'skip' : ''} ${retired ? 'has-reason' : ''}`}
                        data-testid="wfe-done-row"
                      >
                        <span className="tick" aria-hidden="true">
                          {skipped ? '⊘' : '✓'}
                        </span>
                        <span className="nm">{s.name}</span>
                        {s.type !== 'step' && (
                          <span className={`tchip ${s.type}`}>
                            {TYPE_ICON[s.type]} {typeLabel(s.type)}
                          </span>
                        )}
                        {s.chosen_branch && <span className="tchip">→ {s.chosen_branch}</span>}
                        <span className="who">{fmtWho(s)}</span>
                        {retired && <span className="retired">{s.override_reason}</span>}
                      </div>
                    );
                  })}
                </>
              )}
            </section>

            {/* ── Still to do ── */}
            <section className="sec" data-testid="wfe-todo">
              <h3 className="sec-h">
                {t('ci.wfe_todo', { defaultValue: 'Still to do' })}
                <span className="cnt">{rows.filter((r) => !r.retiring).length}</span>
              </h3>
              <p className="why">
                {t('ci.wfe_todo_note', {
                  defaultValue:
                    'In the order it runs, after the last finished step. Drag the handle or use the arrows. ' +
                    'A step already on the list keeps its type; a hold point or a decision can only be ' +
                    'taken off with a reason.',
                })}
              </p>
              {rows.length === 0 && (
                <div className="empty">
                  {t('ci.wfe_no_rows', { defaultValue: 'Nothing left to do — add a step below.' })}
                </div>
              )}
              {rows.map((r, i) => {
                const listId = `${uid}-names-${r.type}`;
                return (
                  <div
                    key={r.key}
                    className={[
                      'cfg',
                      r.type,
                      r.retiring ? 'retiring' : '',
                      dragKey === r.key ? 'dragging' : '',
                      overKey === r.key ? 'dropinto' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    data-testid="wfe-row"
                    data-row-type={r.type}
                    data-existing={r.existing ? '1' : '0'}
                    onDragOver={onDragOver(r.key)}
                    onDragLeave={() => overKey === r.key && setOverKey(null)}
                    onDrop={onDrop(r.key)}
                  >
                    <div className="main">
                      <span
                        className="grip"
                        title={t('ci.wfe_drag', { defaultValue: 'Drag to reorder' })}
                        draggable={!r.retiring}
                        onDragStart={onDragStart(r.key)}
                        onDragEnd={onDragEnd}
                        aria-hidden="true"
                      >
                        ☰
                      </span>
                      <div className="cfg-move">
                        <button
                          type="button"
                          className="mv"
                          title={t('ci.wfe_up', { defaultValue: 'Move up' })}
                          aria-label={t('ci.wfe_up', { defaultValue: 'Move up' })}
                          disabled={i === 0 || r.retiring}
                          onClick={() => shift(r.key, -1)}
                        >
                          ▲
                        </button>
                        <button
                          type="button"
                          className="mv"
                          title={t('ci.wfe_down', { defaultValue: 'Move down' })}
                          aria-label={t('ci.wfe_down', { defaultValue: 'Move down' })}
                          disabled={i === rows.length - 1 || r.retiring}
                          onClick={() => shift(r.key, 1)}
                        >
                          ▼
                        </button>
                      </div>

                      {r.existing ? (
                        <span className={`tchip ${r.type}`} title={t('ci.wfe_type_fixed', { defaultValue: 'A kept step keeps its type' })}>
                          {TYPE_ICON[r.type]} {typeLabel(r.type)}
                        </span>
                      ) : (
                        <div className="seg" role="group" aria-label={t('ci.wfe_type', { defaultValue: 'Type' })}>
                          {(['step', 'gate', 'route'] as RowType[]).map((ty) => (
                            <button
                              key={ty}
                              type="button"
                              className={ty}
                              aria-pressed={r.type === ty}
                              onClick={() => setType(r.key, ty)}
                            >
                              {TYPE_ICON[ty]} {typeLabel(ty)}
                            </button>
                          ))}
                        </div>
                      )}

                      <input
                        ref={(el) => {
                          if (el) nameRefs.current.set(r.key, el);
                          else nameRefs.current.delete(r.key);
                        }}
                        className="cfg-name"
                        aria-label={t('ci.wfe_name', { defaultValue: 'Step name' })}
                        placeholder={
                          r.type === 'route'
                            ? t('ci.wfe_name_ph_route', { defaultValue: 'The question being decided…' })
                            : t('ci.wfe_name_ph', { defaultValue: 'What has to happen…' })
                        }
                        list={namesByType[r.type].length ? listId : undefined}
                        value={r.name}
                        disabled={r.retiring}
                        onChange={(e) => setName(r.key, e.target.value)}
                        onKeyDown={onNameKey(r.key)}
                      />
                      <input
                        className="cfg-owner"
                        aria-label={t('ci.wfe_owner', { defaultValue: 'Owner' })}
                        placeholder={t('ci.wfe_owner_ph', { defaultValue: 'owner' })}
                        list={owners.length ? `${uid}-owners` : undefined}
                        value={r.owner}
                        disabled={r.retiring}
                        onChange={(e) => patch(r.key, (x) => ({ ...x, owner: e.target.value }))}
                      />
                      {!r.retiring && (
                        <button
                          type="button"
                          className="mv del"
                          title={
                            r.existing && r.type !== 'step'
                              ? t('ci.wfe_take_off', { defaultValue: 'Take this off the workflow (needs a reason)' })
                              : t('ci.wfe_remove', { defaultValue: 'Remove' })
                          }
                          aria-label={t('ci.wfe_remove_named', { defaultValue: 'Remove {{name}}', name: r.name || typeLabel(r.type) })}
                          onClick={() => remove(r.key)}
                        >
                          ✕
                        </button>
                      )}
                    </div>

                    {r.retiring && (
                      <div className="offnote" data-testid="wfe-offnote">
                        <span>
                          {t('ci.wfe_coming_off', { defaultValue: 'coming off this workflow' })}
                        </span>
                        <button
                          type="button"
                          className="undo"
                          onClick={() => patch(r.key, (x) => ({ ...x, retiring: false }))}
                        >
                          {t('ci.wfe_undo', { defaultValue: 'undo' })}
                        </button>
                      </div>
                    )}

                    {!r.existing && r.type === 'route' && (
                      <div className="branches" data-testid="wfe-branches">
                        <span className="lbl">
                          {t('ci.wfe_paths', { defaultValue: 'Paths this decision can take' })}
                        </span>
                        {r.branches.map((b) => (
                          <div key={b.key} className="branch">
                            <input
                              className="b-label"
                              aria-label={t('ci.wfe_path_label', { defaultValue: 'Path' })}
                              placeholder={t('ci.wfe_path_ph', { defaultValue: 'e.g. Accepted' })}
                              value={b.label}
                              onChange={(e) =>
                                patch(r.key, (x) => ({
                                  ...x,
                                  branches: x.branches.map((y) => (y.key === b.key ? { ...y, label: e.target.value } : y)),
                                }))
                              }
                            />
                            <textarea
                              className="b-steps"
                              rows={1}
                              aria-label={t('ci.wfe_path_steps', { defaultValue: 'Steps this path adds' })}
                              placeholder={t('ci.wfe_path_steps_ph', {
                                defaultValue: 'steps this path adds, one per line',
                              })}
                              value={b.steps}
                              onChange={(e) =>
                                patch(r.key, (x) => ({
                                  ...x,
                                  branches: x.branches.map((y) => (y.key === b.key ? { ...y, steps: e.target.value } : y)),
                                }))
                              }
                            />
                            <button
                              type="button"
                              className="mv del"
                              aria-label={t('ci.wfe_remove_path', { defaultValue: 'Remove this path' })}
                              onClick={() =>
                                patch(r.key, (x) => ({ ...x, branches: x.branches.filter((y) => y.key !== b.key) }))
                              }
                            >
                              ✕
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="addbranch"
                          onClick={() =>
                            patch(r.key, (x) => ({
                              ...x,
                              branches: [...x.branches, { key: nextKey(), label: '', steps: '' }],
                            }))
                          }
                        >
                          + {t('ci.wfe_add_path', { defaultValue: 'Add a path' })}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}

              {retiring.length > 0 && (
                <div className="reason" data-testid="wfe-reason">
                  <div className="qlab">
                    {t('ci.wfe_why_off', { defaultValue: 'Why are these coming off this job?' })}{' '}
                    <span className="req">*</span>
                  </div>
                  <textarea
                    aria-label={t('ci.wfe_why_off', { defaultValue: 'Why are these coming off this job?' })}
                    placeholder={t('ci.retire_ph', {
                      defaultValue: 'e.g. the client issues this RFI direct — there is no internal review here',
                    })}
                    // The server keeps 300 characters of it; capping here
                    // beats a "retire_reason: String should have at most…"
                    // refusal after the fact.
                    maxLength={REASON_MAX}
                    value={reason}
                    onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
                  />
                  <span className="hint">
                    {reason.length >= REASON_MAX - 40 && (
                      <span className="cnt" data-testid="wfe-reason-count">
                        {reason.length}/{REASON_MAX} ·{' '}
                      </span>
                    )}
                    {t('ci.wfe_why_hint', {
                      defaultValue:
                        '{{names}} stay on the record marked off-this-workflow with this reason — they are not ' +
                        'deleted, and this is not the same as passing a gate below its rule.',
                      names: fmtList(retiring.map((r) => r.name)),
                    })}
                  </span>
                </div>
              )}

              <div className="cfg-foot">
                <button type="button" className="b mini" onClick={() => append(blankRow('step'))}>
                  + {t('ci.wfe_add_step', { defaultValue: 'Add step' })}
                </button>
                <button type="button" className="b mini" onClick={() => append(blankRow('gate'))}>
                  + ⛔ {t('ci.wfe_add_gate', { defaultValue: 'Add gate' })}
                </button>
                <button type="button" className="b mini" onClick={() => append(blankRow('route'))}>
                  + 🔀 {t('ci.wfe_add_decision', { defaultValue: 'Add decision' })}
                </button>
                <div className="lib-wrap" ref={libRef}>
                  <button
                    type="button"
                    className={`b mini ${libOpen ? 'on' : ''}`}
                    aria-expanded={libOpen}
                    disabled={!actions.length}
                    onClick={() => setLibOpen((v) => !v)}
                  >
                    {t('ci.wfe_library', { defaultValue: 'From the library' })} ▾
                  </button>
                  {libOpen && (
                    <div className="lib-pop" role="menu" data-testid="wfe-library">
                      {(['step', 'gate', 'route'] as RowType[]).map((ty) => {
                        const group = actions.filter((a) => (a.t === 'gate' || a.t === 'route' ? a.t : 'step') === ty);
                        if (!group.length) return null;
                        return (
                          <div key={ty}>
                            <div className={`grp ${ty}`}>
                              {TYPE_ICON[ty]} {typeLabel(ty)}
                            </div>
                            {group.map((a) => (
                              <button
                                key={a.name}
                                type="button"
                                className="opt"
                                role="menuitem"
                                onClick={() => {
                                  setLibOpen(false);
                                  append(rowFromAction(a, ty));
                                }}
                              >
                                <span>{a.name}</span>
                                {a.owner && <span className="own">{a.owner}</span>}
                              </button>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                <span className="sp" />
                <button type="button" className="b mini" disabled={!spec} onClick={() => void reset()}>
                  ↺ {t('ci.wfe_reset', { defaultValue: 'Reset to the standard flow' })}
                </button>
              </div>
            </section>
          </div>

          <div className="wfe-actions">
            {error && (
              <div className="err" role="alert" data-testid="wfe-error">
                {error}
              </div>
            )}
            <span className="sp" />
            <button type="button" className="b" disabled={busy} onClick={() => resolve(false)}>
              {t('ci.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button type="button" className="b pri" disabled={busy} onClick={() => void save()}>
              {t('ci.save_flow', { defaultValue: 'Save the workflow' })}
            </button>
          </div>

          {/* Datalists: library names per type, and the owners seen in the spec. */}
          {(['step', 'gate', 'route'] as RowType[]).map((ty) => (
            <datalist key={ty} id={`${uid}-names-${ty}`}>
              {namesByType[ty].map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          ))}
          <datalist id={`${uid}-owners`}>
            {owners.map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
        </div>
      </div>
    </div>
  );
}

/**
 * Open the editor over the page. Resolves `true` once the workflow was
 * saved (after `onSaved` ran), `false` on cancel / Escape / scrim click.
 */
export function openWorkflowEditor(args: WorkflowEditorArgs): Promise<boolean> {
  return new Promise((resolve) => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    let settled = false;
    const done = (saved: boolean) => {
      if (settled) return;
      settled = true;
      root.unmount();
      host.remove();
      resolve(saved);
    };
    root.render(<WorkflowEditorDialog {...args} resolve={done} />);
  });
}
