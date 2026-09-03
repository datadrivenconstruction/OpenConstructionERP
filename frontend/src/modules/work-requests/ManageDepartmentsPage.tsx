// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Manage departments - the screen behind "Add more request types and let
 * the user add more if needed".
 *
 * One department at a time (`?dept=` keeps the choice through a reload):
 * its name, colour, hourly rate, lead and members on the left, and the
 * request types it offers on the right - add one, rename it, reorder,
 * retire or restore it, delete it, and edit the fields it asks for.
 *
 * Three rules run through the whole screen:
 *
 *  - **No optimism.** Nothing on screen moves until the server has said
 *    yes; then every Work Requests query is invalidated so the tabs, the
 *    board and the raise dialog all pick the change up at once. A
 *    reordered list that snaps back is a bug report; a list that waits a
 *    beat is just honest.
 *  - **The server's words, where the thing is.** A refusal - a type still
 *    in use, a duplicate key, a 403 - is printed against the control that
 *    caused it, never as a toast that outlives its context.
 *  - **`manage` is the server's call.** The button that opens this screen
 *    is hidden for a role that could only be refused, but the gate is
 *    the backend's: a 403 here turns every editor read-only and says so,
 *    rather than letting somebody type into a form that cannot save.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ChevronDown, ChevronUp, Plus, RotateCcw, SlidersHorizontal, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { qConfirm } from '../comms-intelligence/qAsk';
import {
  createRequestType,
  deleteRequestType,
  patchDepartment,
  patchRequestType,
  reorderRequestTypes,
  type Department,
  type FieldType,
  type RequestField,
  type RequestType,
} from './api';
import { Avatar } from './bits';
import { useDepartments, useInvalidateWr, useUsers } from './hooks';
import { Picker } from './Pickers';
import {
  COLOUR_CHOICES,
  NEUTRAL,
  errorText,
  isForbidden,
  isModuleMissing,
  isNotFound,
  resolveColour,
  typesOf,
} from './lib';
import { ModuleMissing } from './ModuleMissing';
import './wr.css';
import { fmtList } from '@/shared/lib/formatters';

const FIELD_TYPES: FieldType[] = ['text', 'area', 'date', 'number', 'bool', 'select', 'url'];

/** The key the server would mint from a label - shown before it is asked. */
export function slugKey(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40);
}

function readDept(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('dept');
  } catch {
    return null;
  }
}

export default function ManageDepartmentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // The retired types have to be here, or "restore" would have nothing to
  // restore - this is the one screen that asks for them.
  const departments = useDepartments(true);
  const [key, setKey] = useState<string | null>(readDept);

  const deps = useMemo(() => departments.data ?? [], [departments.data]);
  const current = deps.find((d) => d.key === key) ?? deps[0];

  useEffect(() => {
    if (!current) return;
    try {
      const p = new URLSearchParams(window.location.search);
      p.set('dept', current.key);
      window.history.replaceState(window.history.state, '', `${window.location.pathname}?${p.toString()}`);
    } catch {
      /* not in a browser */
    }
  }, [current]);

  const missing = departments.isError && isModuleMissing(departments.error);

  return (
    <div className="wr flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 flex items-center gap-2 text-xl font-bold text-content-primary">
            <SlidersHorizontal size={20} className="text-content-tertiary" aria-hidden />
            {t('wr.manage_title', { defaultValue: 'Manage departments' })}
          </h1>
          <p className="m-0 text-xs text-content-tertiary">
            {t('wr.manage_sub', {
              defaultValue: 'Who each department is, what it charges, and the request types it offers.',
            })}
          </p>
        </div>
        <Link to="/work-requests" className="wr-btn-quiet">
          <ArrowLeft size={12} /> {t('wr.back_to_requests', { defaultValue: 'Back to requests' })}
        </Link>
      </div>

      {missing && <ModuleMissing onRetry={() => void departments.refetch()} />}
      {departments.isError && !missing && (
        <div className="wr-banner err">
          {isForbidden(departments.error)
            ? t('wr.manage_403', {
                defaultValue: 'Your account cannot manage departments - ask a manager or an administrator.',
              })
            : errorText(departments.error)}{' '}
          <button type="button" className="wr-btn-quiet" onClick={() => void departments.refetch()}>
            {t('wr.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      )}
      {departments.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}

      {departments.data && deps.length === 0 && (
        <div className="wr-empty">
          <b>{t('wr.no_departments', { defaultValue: 'No active departments are configured.' })}</b>
          {t('wr.no_departments_body', { defaultValue: 'A department has to exist before it can offer request types.' })}
        </div>
      )}

      {current && (
        <div className="wr-manage">
          <nav className="wr-manage-list" aria-label={t('wr.departments', { defaultValue: 'Departments' })}>
            {deps.map((d) => (
              <button
                key={d.key}
                type="button"
                className="wr-manage-item"
                aria-current={d.key === current.key ? 'true' : undefined}
                onClick={() => setKey(d.key)}
              >
                <span className="sw" style={{ background: resolveColour(d.colour) }} aria-hidden />
                <span className="nm">{d.name}</span>
                <span className="wr-mono px">{d.prefix}</span>
                {!d.active && <span className="wr-hint">{t('wr.retired', { defaultValue: 'retired' })}</span>}
              </button>
            ))}
          </nav>

          <div className="wr-manage-body">
            {/* Remounting on the department key throws away the drafts of the
                one before it - a half-typed rate must never follow you to
                another department's form. */}
            <DepartmentForm key={`d-${current.key}`} dept={current} onGone={() => navigate('/work-requests')} />
            <RequestTypeEditor key={`t-${current.key}`} dept={current} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── The department itself ───────────────────────────────────────── */

function DepartmentForm({ dept, onGone }: { dept: Department; onGone: () => void }) {
  const { t } = useTranslation();
  const invalidate = useInvalidateWr();
  const users = useUsers();
  const [name, setName] = useState(dept.name);
  const [description, setDescription] = useState(dept.description ?? '');
  const [colour, setColour] = useState(dept.colour);
  const [rate, setRate] = useState(dept.hourly_rate ?? '');
  const [lead, setLead] = useState<string | null>(dept.lead_user_id);
  const [members, setMembers] = useState<string[]>(dept.member_ids ?? []);
  const [picker, setPicker] = useState<{ at: HTMLElement; what: 'lead' | 'members' } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const userName = (id: string) => {
    const u = (users.data ?? []).find((x) => x.id === id);
    return u ? u.full_name || u.email : id;
  };

  // Money is Decimal-as-TEXT on this contract, so the rate is validated as
  // text and sent as text - never parsed into a float and back.
  const rateBad = rate.trim() !== '' && !/^\d{1,9}(\.\d{1,2})?$/.test(rate.trim());
  const dirty =
    name !== dept.name ||
    description !== (dept.description ?? '') ||
    colour !== dept.colour ||
    rate !== (dept.hourly_rate ?? '') ||
    lead !== dept.lead_user_id ||
    members.join(',') !== (dept.member_ids ?? []).join(',');

  const save = async () => {
    if (!name.trim() || rateBad) return;
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      await patchDepartment(dept.key, {
        name: name.trim(),
        description: description.trim(),
        colour,
        hourly_rate: rate.trim() === '' ? null : rate.trim(),
        lead_user_id: lead,
        member_ids: members,
      });
      void invalidate();
      setSaved(true);
    } catch (e) {
      if (isNotFound(e)) onGone();
      setErr(
        isForbidden(e)
          ? t('wr.manage_403', { defaultValue: 'Your account cannot manage departments - ask a manager or an administrator.' })
          : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="wr-panel" aria-label={t('wr.manage_dept_sec', { defaultValue: 'Department' })}>
      <h2 className="wr-panel-h">
        {t('wr.manage_dept_sec', { defaultValue: 'Department' })}
        <span className="wr-mono wr-hint">{dept.prefix}</span>
      </h2>

      <div className="wr-form">
        <div className="wr-field">
          <label htmlFor="wr-md-name">
            {t('wr.dept_name', { defaultValue: 'Name' })} <span className="req">*</span>
          </label>
          <input id="wr-md-name" className={clsx('wr-in', !name.trim() && 'miss')} value={name} onChange={(e) => setName(e.target.value)} />
          {!name.trim() && <span className="err">{t('wr.err_name', { defaultValue: 'A department needs a name.' })}</span>}
        </div>
        <div className="wr-field">
          <label htmlFor="wr-md-rate">{t('wr.hourly_rate', { defaultValue: 'Hourly rate' })}</label>
          <input
            id="wr-md-rate"
            className={clsx('wr-in', rateBad && 'miss')}
            inputMode="decimal"
            value={rate}
            placeholder={t('wr.no_rate_ph', { defaultValue: 'none' })}
            onChange={(e) => setRate(e.target.value)}
          />
          {rateBad && <span className="err">{t('wr.err_rate', { defaultValue: 'A rate like 125 or 125.50.' })}</span>}
        </div>
        <div className="wr-field wide">
          <label htmlFor="wr-md-desc">{t('wr.description', { defaultValue: 'Description' })}</label>
          <input id="wr-md-desc" className="wr-in" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div className="wr-field wide">
          <label id="wr-md-col-lab">{t('wr.colour', { defaultValue: 'Colour' })}</label>
          <div className="wr-swatches" role="radiogroup" aria-labelledby="wr-md-col-lab">
            {COLOUR_CHOICES.map((c) => (
              <button
                key={c.token}
                type="button"
                role="radio"
                aria-checked={colour === c.token}
                aria-label={c.token}
                title={c.token}
                className="wr-swatch"
                style={{ background: c.hex }}
                onClick={() => setColour(c.token)}
              />
            ))}
          </div>
        </div>

        <div className="wr-field">
          <label>{t('wr.dept_lead', { defaultValue: 'Lead' })}</label>
          <button type="button" className="wr-in text-left" onClick={(e) => setPicker({ at: e.currentTarget, what: 'lead' })}>
            {lead ? userName(lead) : <span className="wr-hint">{t('wr.pick_lead', { defaultValue: 'Who leads it?' })}</span>}
          </button>
        </div>
        <div className="wr-field">
          <label>{t('wr.dept_members', { defaultValue: 'Members' })}</label>
          <button type="button" className="wr-in text-left" onClick={(e) => setPicker({ at: e.currentTarget, what: 'members' })}>
            {members.length ? (
              fmtList(members.map(userName))
            ) : (
              <span className="wr-hint">{t('wr.no_members', { defaultValue: 'Nobody yet - every user is offered' })}</span>
            )}
          </button>
        </div>
      </div>

      {err && (
        <div className="wr-banner err mt-2" role="alert">
          <span>{err}</span>
        </div>
      )}

      <div className="wr-panel-foot">
        {saved && !dirty && <span className="wr-hint">{t('wr.saved', { defaultValue: 'Saved.' })}</span>}
        <button type="button" className="wr-btn-quiet on" disabled={busy || !dirty || !name.trim() || rateBad} onClick={() => void save()} data-testid="wr-dept-save">
          {busy ? t('wr.saving', { defaultValue: 'Saving…' }) : t('wr.save', { defaultValue: 'Save department' })}
        </button>
      </div>

      {picker && (
        <Picker
          anchor={picker.at}
          multi={picker.what === 'members'}
          selected={picker.what === 'members' ? members : lead ? [lead] : []}
          options={(users.data ?? []).map((u) => ({
            id: u.id,
            label: u.full_name || u.email,
            sub: u.email,
            lead: <Avatar person={{ id: u.id, name: u.full_name || u.email }} size={18} />,
          }))}
          placeholder={picker.what === 'members' ? t('wr.pick_members', { defaultValue: 'Who is in it?' }) : t('wr.pick_lead', { defaultValue: 'Who leads it?' })}
          onClose={() => setPicker(null)}
          onChange={(ids) => {
            if (picker.what === 'members') setMembers(ids);
            else setLead(ids[0] ?? null);
          }}
        />
      )}
    </section>
  );
}

/* ── The request types it offers ─────────────────────────────────── */

function RequestTypeEditor({ dept }: { dept: Department }) {
  const { t } = useTranslation();
  const invalidate = useInvalidateWr();
  const addToast = useToastStore((s) => s.addToast);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  /** Keyed by type key, plus `''` for the add-a-type row. */
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [openFields, setOpenFields] = useState<string | null>(null);

  const all = useMemo(() => typesOf(dept, true), [dept]);
  const taken = new Set(all.map((x) => x.key));
  const nextKey = slugKey(label);
  const keyClash = nextKey !== '' && taken.has(nextKey);

  const fail = (k: string, e: unknown) =>
    setErrs((s) => ({
      ...s,
      [k]: isForbidden(e)
        ? t('wr.manage_403', { defaultValue: 'Your account cannot manage departments - ask a manager or an administrator.' })
        : isNotFound(e)
          ? t('wr.types_unsupported', {
              defaultValue: 'This server cannot edit request types yet - its Work Requests module predates the editor.',
            })
          : errorText(e),
    }));

  /** One write, one busy key, one place errors land. Nothing is optimistic. */
  const run = async (k: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(k);
    setErrs((s) => ({ ...s, [k]: '' }));
    try {
      await fn();
      void invalidate();
      if (done) addToast({ type: 'success', title: done });
      return true;
    } catch (e) {
      fail(k, e);
      return false;
    } finally {
      setBusy(null);
    }
  };

  const add = async () => {
    const l = label.trim();
    if (!l || keyClash) return;
    const ok = await run('', () => createRequestType(dept.key, { label: l, key: nextKey, disciplines: [], fields: [] }));
    if (ok) setLabel('');
  };

  const move = async (from: number, to: number) => {
    if (to < 0 || to >= all.length) return;
    const keys = all.map((x) => x.key);
    const [moved] = keys.splice(from, 1);
    if (!moved) return;
    keys.splice(to, 0, moved);
    await run('order', () => reorderRequestTypes(dept.key, keys));
  };

  return (
    <section className="wr-panel" aria-label={t('wr.request_types', { defaultValue: 'Request types' })}>
      <h2 className="wr-panel-h">
        {t('wr.request_types', { defaultValue: 'Request types' })}
        <span className="wr-hint">
          {t('wr.types_sec_hint', { defaultValue: 'A request may carry several of these at once.' })}
        </span>
      </h2>

      {errs.order && (
        <div className="wr-banner err mb-2" role="alert">
          <span>{errs.order}</span>
        </div>
      )}

      <ul className="wr-types-list">
        {all.length === 0 && (
          <li className="wr-hint px-1 py-2">{t('wr.no_types', { defaultValue: 'This department has no request types configured.' })}</li>
        )}
        {all.map((rt, i) => (
          <TypeRow
            key={rt.key}
            dept={dept}
            rt={rt}
            first={i === 0}
            last={i === all.length - 1}
            busy={busy === rt.key || busy === 'order'}
            error={errs[rt.key] || ''}
            fieldsOpen={openFields === rt.key}
            onToggleFields={() => setOpenFields((k) => (k === rt.key ? null : rt.key))}
            onUp={() => void move(i, i - 1)}
            onDown={() => void move(i, i + 1)}
            onRun={run}
          />
        ))}
      </ul>

      <div className="wr-addtype">
        <div className="wr-field">
          <label htmlFor="wr-newtype">{t('wr.add_type', { defaultValue: 'Add a request type' })}</label>
          <input
            id="wr-newtype"
            className={clsx('wr-in', keyClash && 'miss')}
            value={label}
            placeholder={t('wr.add_type_ph', { defaultValue: 'e.g. Functional design specification' })}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void add();
              }
            }}
            data-testid="wr-newtype"
          />
          {/* The key is what every existing request stores, so it is shown
              before it is minted rather than discovered afterwards. */}
          {nextKey && !keyClash && (
            <span className="wr-hint">{t('wr.type_key_preview', { defaultValue: 'key: {{k}}', k: nextKey })}</span>
          )}
          {keyClash && <span className="err">{t('wr.type_key_taken', { defaultValue: '“{{k}}” is already a type here.', k: nextKey })}</span>}
        </div>
        <button type="button" className="wr-btn-quiet on" disabled={!label.trim() || keyClash || busy === ''} onClick={() => void add()} data-testid="wr-addtype">
          <Plus size={12} /> {busy === '' ? t('wr.adding', { defaultValue: 'Adding…' }) : t('wr.add', { defaultValue: 'Add' })}
        </button>
      </div>
      {errs[''] && (
        <div className="wr-banner err mt-2" role="alert">
          <span>{errs['']}</span>
        </div>
      )}
    </section>
  );
}

function TypeRow({
  dept,
  rt,
  first,
  last,
  busy,
  error,
  fieldsOpen,
  onToggleFields,
  onUp,
  onDown,
  onRun,
}: {
  dept: Department;
  rt: RequestType;
  first: boolean;
  last: boolean;
  busy: boolean;
  error: string;
  fieldsOpen: boolean;
  onToggleFields: () => void;
  onUp: () => void;
  onDown: () => void;
  onRun: (k: string, fn: () => Promise<unknown>, done?: string) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState(rt.label);
  useEffect(() => setLabel(rt.label), [rt.label]);
  const retired = rt.active === false;

  const rename = () => {
    const l = label.trim();
    if (!l || l === rt.label) {
      setLabel(rt.label);
      return;
    }
    void onRun(rt.key, () => patchRequestType(dept.key, rt.key, { label: l }));
  };

  return (
    <li className={clsx('wr-type', retired && 'off')}>
      <div className="wr-type-head">
        <span className="ord">
          <button type="button" className="wr-btn-quiet" disabled={first || busy} onClick={onUp} aria-label={t('wr.move_up', { defaultValue: 'Move {{name}} up', name: rt.label })}>
            <ChevronUp size={12} />
          </button>
          <button type="button" className="wr-btn-quiet" disabled={last || busy} onClick={onDown} aria-label={t('wr.move_down', { defaultValue: 'Move {{name}} down', name: rt.label })}>
            <ChevronDown size={12} />
          </button>
        </span>
        <input
          className="wr-inl flex-1"
          value={label}
          aria-label={t('wr.type_label_of', { defaultValue: 'Label of {{k}}', k: rt.key })}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={rename}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            if (e.key === 'Escape') {
              setLabel(rt.label);
              (e.target as HTMLInputElement).blur();
            }
          }}
        />
        <span className="wr-mono wr-hint shrink-0">{rt.key}</span>
        {retired && <span className="wr-pill shrink-0">{t('wr.retired', { defaultValue: 'retired' })}</span>}
        <span className="wr-hint shrink-0">
          {/* i18next picks the plural form from `defaultValue_one` /
              `defaultValue_other`; a bare `defaultValue` printed the
              literal "1 fields". */}
          {t('wr.n_fields', {
            defaultValue_one: '{{count}} field',
            defaultValue_other: '{{count}} fields',
            defaultValue: '{{count}} fields',
            count: (rt.fields ?? []).length,
          })}
        </span>
        <button type="button" className="wr-btn-quiet shrink-0" onClick={onToggleFields} aria-expanded={fieldsOpen}>
          {fieldsOpen ? t('wr.hide_fields', { defaultValue: 'Hide fields' }) : t('wr.edit_fields', { defaultValue: 'Fields…' })}
        </button>
        <button
          type="button"
          className="wr-btn-quiet shrink-0"
          disabled={busy}
          title={retired ? t('wr.restore_hint', { defaultValue: 'Offer it again' }) : t('wr.retire_hint', { defaultValue: 'Stop offering it; requests that carry it keep it' })}
          onClick={() => void onRun(rt.key, () => patchRequestType(dept.key, rt.key, { active: retired }))}
        >
          <RotateCcw size={11} /> {retired ? t('wr.restore', { defaultValue: 'Restore' }) : t('wr.retire', { defaultValue: 'Retire' })}
        </button>
        <button
          type="button"
          className="wr-btn-quiet shrink-0"
          disabled={busy}
          aria-label={t('wr.delete_type', { defaultValue: 'Delete {{name}}', name: rt.label })}
          onClick={async () => {
            const ok = await qConfirm(
              t('wr.delete_type_q', { defaultValue: 'Delete the request type “{{name}}”?', name: rt.label }),
              t('wr.delete_type_note', {
                defaultValue: 'The server refuses if any request still carries it - retire it instead to stop offering it.',
              }),
              t('wr.delete', { defaultValue: 'Delete' }),
            );
            if (ok) void onRun(rt.key, () => deleteRequestType(dept.key, rt.key));
          }}
        >
          <Trash2 size={11} />
        </button>
      </div>

      {/* The server's own sentence - "3 requests still use it" - printed
          against the type it is about, not floated away as a toast. */}
      {error && (
        <div className="wr-banner err" role="alert">
          <span>{error}</span>
        </div>
      )}

      {fieldsOpen && <FieldsEditor dept={dept} rt={rt} busy={busy} onRun={onRun} />}
    </li>
  );
}

function FieldsEditor({
  dept,
  rt,
  busy,
  onRun,
}: {
  dept: Department;
  rt: RequestType;
  busy: boolean;
  onRun: (k: string, fn: () => Promise<unknown>, done?: string) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [fields, setFields] = useState<RequestField[]>(() => (rt.fields ?? []).map((f) => ({ ...f })));
  useEffect(() => setFields((rt.fields ?? []).map((f) => ({ ...f }))), [rt.fields]);

  const set = (i: number, patch: Partial<RequestField>) =>
    setFields((s) => s.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  const dupes = new Set(
    fields.map((f) => f.key.trim()).filter((k, i, a) => k !== '' && a.indexOf(k) !== i),
  );
  const bad = fields.some((f) => !f.key.trim() || !f.label.trim()) || dupes.size > 0;
  const dirty = JSON.stringify(fields) !== JSON.stringify(rt.fields ?? []);

  return (
    <div className="wr-fields">
      <div className="wr-fields-grid">
        <span className="h">{t('wr.field_key', { defaultValue: 'Key' })}</span>
        <span className="h">{t('wr.field_label', { defaultValue: 'Label' })}</span>
        <span className="h">{t('wr.field_type', { defaultValue: 'Type' })}</span>
        <span className="h">{t('wr.field_options', { defaultValue: 'Options (select)' })}</span>
        <span className="h">{t('wr.field_required', { defaultValue: 'Required' })}</span>
        <span className="h" />
        {fields.map((f, i) => (
          <FieldRowCells
            key={`f${i}`}
            field={f}
            index={i}
            duplicate={dupes.has(f.key.trim())}
            onChange={(p) => set(i, p)}
            onRemove={() => setFields((s) => s.filter((_, j) => j !== i))}
          />
        ))}
      </div>
      {fields.length === 0 && (
        <p className="wr-hint">{t('wr.no_fields', { defaultValue: 'This type asks nothing extra - just a title and a description.' })}</p>
      )}
      {dupes.size > 0 && (
        <p className="err">{t('wr.field_key_dupe', { defaultValue: 'Two fields cannot share a key.' })}</p>
      )}
      <div className="wr-panel-foot">
        <button
          type="button"
          className="wr-btn-quiet mr-auto"
          onClick={() => setFields((s) => [...s, { key: '', label: '', type: 'text' }])}
        >
          <Plus size={11} /> {t('wr.add_field', { defaultValue: 'Add a field' })}
        </button>
        {dirty && (
          <button type="button" className="wr-btn-quiet" onClick={() => setFields((rt.fields ?? []).map((f) => ({ ...f })))}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        )}
        <button
          type="button"
          className="wr-btn-quiet on"
          disabled={busy || bad || !dirty}
          onClick={() =>
            void onRun(rt.key, () =>
              patchRequestType(dept.key, rt.key, {
                fields: fields.map((f) => ({
                  key: f.key.trim(),
                  label: f.label.trim(),
                  type: f.type,
                  // Only a select carries options, and `required: false` is
                  // the default - neither is sent as noise.
                  ...(f.type === 'select' ? { options: (f.options ?? []).filter(Boolean) } : {}),
                  ...(f.required ? { required: true } : {}),
                })),
              }),
            )
          }
          data-testid={`wr-savefields-${rt.key}`}
        >
          {t('wr.save_fields', { defaultValue: 'Save fields' })}
        </button>
      </div>
    </div>
  );
}

function FieldRowCells({
  field,
  index,
  duplicate,
  onChange,
  onRemove,
}: {
  field: RequestField;
  index: number;
  duplicate: boolean;
  onChange: (p: Partial<RequestField>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const n = index + 1;
  return (
    <>
      <input
        className={clsx('wr-in', (!field.key.trim() || duplicate) && 'miss')}
        value={field.key}
        aria-label={t('wr.field_key_n', { defaultValue: 'Field {{n}} key', n })}
        placeholder="ifc_link"
        onChange={(e) => onChange({ key: e.target.value })}
      />
      <input
        className={clsx('wr-in', !field.label.trim() && 'miss')}
        value={field.label}
        aria-label={t('wr.field_label_n', { defaultValue: 'Field {{n}} label', n })}
        placeholder={t('wr.field_label_ph', { defaultValue: 'What to ask' })}
        onChange={(e) => onChange({ label: e.target.value })}
      />
      <select
        className="wr-in"
        value={field.type}
        aria-label={t('wr.field_type_n', { defaultValue: 'Field {{n}} type', n })}
        onChange={(e) => onChange({ type: e.target.value as FieldType })}
      >
        {FIELD_TYPES.map((ft) => (
          <option key={ft} value={ft}>
            {t(`wr.ftype.${ft}`, { defaultValue: ft })}
          </option>
        ))}
      </select>
      <input
        className="wr-in"
        value={(field.options ?? []).join(', ')}
        disabled={field.type !== 'select'}
        aria-label={t('wr.field_options_n', { defaultValue: 'Field {{n}} options', n })}
        placeholder={field.type === 'select' ? t('wr.field_options_ph', { defaultValue: '3b, 4a' }) : '—'}
        onChange={(e) => onChange({ options: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
      />
      <label className="wr-tog">
        <input
          type="checkbox"
          checked={!!field.required}
          aria-label={t('wr.field_required_n', { defaultValue: 'Field {{n}} required', n })}
          onChange={(e) => onChange({ required: e.target.checked })}
        />
      </label>
      <button type="button" className="wr-btn-quiet" onClick={onRemove} aria-label={t('wr.remove_field', { defaultValue: 'Remove field {{n}}', n })}>
        <Trash2 size={11} />
      </button>
    </>
  );
}

/** Kept for the swatch fallback when a department carries no colour. */
export const MANAGE_FALLBACK_COLOUR = NEUTRAL;
