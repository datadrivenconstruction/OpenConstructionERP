// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * "Raise a request": department (cards) → request types (chips) → the
 * UNION of those types' fields, the job, the disciplines' cost centres
 * and hours, dates, priority, links, people. Validation is inline; the
 * raise mints the reference server-side and the toast carries it.
 *
 * One item is often several things at once - a panel that needs SCADA,
 * PLC programming AND an FDS - so the type chips are a multi-select. At
 * least one is required, the chosen order is kept, and the form asks the
 * de-duplicated union of their fields, which is exactly what the server
 * validates against (`field_specs`). `request_type` still goes with the
 * body as the first of them so a backend that predates the multi-type
 * contract accepts the same raise.
 *
 * Attachments are added after the raise, on the request itself: a file
 * needs an id to hang from, and the drawer opens on the new request.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { qAsk } from '../comms-intelligence/qAsk';
import { PRIORITIES, createRequest, type CreateRequestBody, type Department, type LinkRef, type Priority, type RequestField, type WorkRequest } from './api';
import { Avatar } from './bits';
import { useInvalidateWr, useProjects, useTemplates, useUsers } from './hooks';
import { PRIORITY_LABEL, errorText, fieldSpecsOf, memberPool, resolveColour, typeKeysOf, typesOf, unionDisciplines, unionFields, type Me } from './lib';
import { Picker } from './Pickers';
import { fmtList } from '@/shared/lib/formatters';

export function RaiseRequestDialog({
  open,
  departments,
  me,
  defaultDepartment,
  defaultProjectId,
  defaultDue,
  onClose,
  onRaised,
}: {
  open: boolean;
  departments: Department[];
  me: Me | null;
  defaultDepartment?: string;
  defaultProjectId?: string | null;
  /** Prefills "Due" - the month view raises a request ON a day. */
  defaultDue?: string | null;
  onClose: () => void;
  onRaised: (req: WorkRequest) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const invalidate = useInvalidateWr();
  const projects = useProjects();
  const users = useUsers();
  const active = departments.filter((d) => d.active);

  const [dept, setDept] = useState<string>(defaultDepartment && defaultDepartment !== 'all' ? defaultDepartment : '');
  const department = departments.find((d) => d.key === dept);
  const offered = useMemo(() => typesOf(department), [department]);
  /** In the order they were picked - the server keeps it, so the chips do. */
  const [typeKeys, setTypeKeys] = useState<string[]>([]);
  const [projectId, setProjectId] = useState<string>(defaultProjectId ?? '');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const [costCentres, setCostCentres] = useState<Record<string, string>>({});
  const [estimated, setEstimated] = useState<Record<string, string>>({});
  const [quoted, setQuoted] = useState('');
  const [infoBy, setInfoBy] = useState('');
  const [due, setDue] = useState(defaultDue ?? '');
  const [priority, setPriority] = useState<Priority>('normal');
  const [links, setLinks] = useState<LinkRef[]>([]);
  const [assignees, setAssignees] = useState<string[]>([]);
  const [responsible, setResponsible] = useState<string | null>(null);
  const [draft, setDraft] = useState(false);
  const [picker, setPicker] = useState<{ at: HTMLElement; what: 'project' | 'assignees' | 'responsible' | 'template' } | null>(null);
  /** Which template this was started from, if any - shown as a chip. */
  const [fromTemplate, setFromTemplate] = useState<WorkRequest | null>(null);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  /**
   * Types a template asked for, waiting for the department switch that
   * makes them legal.
   *
   * The effect below resets the types whenever the department's offered
   * list changes - which is exactly what "start from a template" triggers
   * when the template belongs to another department, and it wiped the
   * template's own types a tick after they were set. The ref survives the
   * render in between; the effect consumes it once and never again.
   */
  const pendingTypesRef = useRef<string[] | null>(null);

  // A department with one live type picks it for you; changing department
  // clears the rest, because a type key only means anything inside one.
  useEffect(() => {
    const pending = pendingTypesRef.current;
    if (pending) {
      pendingTypesRef.current = null;
      // Still filtered against what the department offers: a type the
      // template carries that has since been retired is not smuggled in.
      setTypeKeys(pending.filter((k) => offered.some((o) => o.key === k)));
      return;
    }
    setTypeKeys(offered.length === 1 ? [offered[0]?.key ?? ''] : []);
  }, [offered]);

  /** The chosen types, resolved and still in the chosen order. */
  const chosen = useMemo(
    () => typeKeys.map((k) => offered.find((t) => t.key === k)).filter((t): t is NonNullable<typeof t> => !!t),
    [typeKeys, offered],
  );
  // The union is what the server validates against, so it is what the
  // form asks - a switchboard that also needs an FDS asks both sets once.
  const formFields = useMemo(() => unionFields(chosen), [chosen]);
  const disciplines = useMemo(() => unionDisciplines(chosen), [chosen]);

  const toggleType = (key: string) =>
    setTypeKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]));

  useEffect(() => {
    if (open) setProjectId(defaultProjectId ?? '');
  }, [open, defaultProjectId]);

  // "Raise a request due this day" opens the dialog with the day already
  // in it; the field stays editable, and a dialog opened with no day
  // never clears one the typist has since chosen.
  useEffect(() => {
    if (open && defaultDue) setDue(defaultDue);
  }, [open, defaultDue]);

  /**
   * The templates, only once somebody opens the picker. Scoped to the
   * chosen department when there is one, so "start from a template" on
   * the Workshop offers Workshop shapes rather than the whole company's.
   */
  const templates = useTemplates(dept || undefined, picker?.what === 'template');

  /**
   * Start from a template: everything a raise asks for, except the job
   * and the dates. Deliberately NOT the job - a template is a shape, and
   * a shape that drags last quarter's job number with it is how the wrong
   * job gets billed. The dates go the same way: a due date copied off a
   * template is a date nobody chose.
   */
  const applyTemplate = (tpl: WorkRequest) => {
    const tplDept = departments.find((d) => d.key === tpl.department);
    setFromTemplate(tpl);
    const keys = typeKeysOf(tpl);
    // A department switch re-runs the type effect below; the ref carries
    // the template's types across it. Same department, no switch, no ref.
    if (tpl.department !== dept) pendingTypesRef.current = keys;
    else pendingTypesRef.current = null;
    setDept(tpl.department);
    setTypeKeys(keys);
    setTitle(tpl.title ?? '');
    setDescription(tpl.description ?? '');
    // Only the fields the template's own types actually ask for.
    const asked = new Set(fieldSpecsOf(tpl, tplDept).map((f) => f.key));
    const next: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(tpl.fields ?? {})) if (asked.has(k)) next[k] = v;
    setFields(next);
    setCostCentres({ ...(tpl.cost_centres ?? {}) });
    setEstimated(Object.fromEntries(Object.entries(tpl.estimated_hours ?? {}).map(([k, v]) => [k, String(v)])));
    setQuoted(tpl.quoted_hours === null || tpl.quoted_hours === undefined ? '' : String(tpl.quoted_hours));
    setPriority(tpl.priority ?? 'normal');
    setLinks([...(tpl.links ?? [])]);
  };

  const pool = useMemo(() => memberPool(department, users.data ?? []), [department, users.data]);
  const project = (projects.data ?? []).find((p) => p.id === projectId);
  const userName = (id: string) => {
    const u = (users.data ?? []).find((x) => x.id === id);
    return u ? u.full_name || u.email : id;
  };

  const errors: Record<string, string> = {};
  if (!dept) errors.dept = t('wr.err_dept', { defaultValue: 'Pick a department.' });
  if (dept && typeKeys.length === 0) errors.type = t('wr.err_type', { defaultValue: 'Pick at least one request type.' });
  if (!projectId) errors.project = t('wr.err_project', { defaultValue: 'Pick the job.' });
  if (!title.trim()) errors.title = t('wr.err_title', { defaultValue: 'Give it a title.' });
  for (const f of formFields) {
    const v = fields[f.key];
    if (f.required && (v === undefined || v === null || v === '' || v === false)) errors[`f:${f.key}`] = t('wr.err_required', { defaultValue: 'Required.' });
  }
  // Only the rows on screen can fail: a bad number under a discipline the
  // chosen types no longer ask for would otherwise block the raise with an
  // error nobody could see, let alone fix.
  for (const d of disciplines) {
    const v = estimated[d] ?? '';
    if (v !== '' && !Number.isFinite(Number(v))) errors[`h:${d}`] = t('wr.err_number', { defaultValue: 'Must be a number.' });
  }
  if (quoted !== '' && !Number.isFinite(Number(quoted))) errors.quoted = t('wr.err_number', { defaultValue: 'Must be a number.' });
  const valid = Object.keys(errors).length === 0;

  const submit = async () => {
    setTouched(true);
    if (!valid) return;
    // Same rule as the fields: only the disciplines the chosen types still
    // ask for are sent, so deselecting a type drops its row rather than
    // smuggling the hours somebody typed under it into the raise.
    const asks = new Set(disciplines);
    const est: Record<string, number> = {};
    for (const [d, v] of Object.entries(estimated)) if (v !== '' && asks.has(d)) est[d] = Number(v);
    const cc: Record<string, string> = {};
    for (const [d, v] of Object.entries(costCentres)) if (v.trim() && asks.has(d)) cc[d] = v.trim();
    // Only the union's own keys go up: a value typed under a type that was
    // then deselected is not part of the form the server will validate.
    const asked = new Set(formFields.map((f) => f.key));
    const sent: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(fields)) if (asked.has(k)) sent[k] = v;
    const body: CreateRequestBody = {
      project_id: projectId,
      department: dept,
      // The first is the legacy single field; the array is the contract.
      request_type: typeKeys[0] ?? '',
      request_types: typeKeys,
      title: title.trim(),
      description: description.trim() || undefined,
      cost_centres: cc,
      estimated_hours: est,
      quoted_hours: quoted === '' ? null : Number(quoted),
      info_required_by: infoBy || null,
      due_date: due || null,
      priority,
      links,
      fields: sent,
      assignee_ids: assignees,
      responsible_user_id: responsible,
      draft,
    };
    setBusy(true);
    setServerError(null);
    try {
      const created = await createRequest(body);
      void invalidate();
      addToast({
        type: 'success',
        title: t('wr.raised_toast', { defaultValue: 'Raised {{ref}}', ref: created.reference }),
        message: created.title,
        action: { label: t('wr.open', { defaultValue: 'Open' }), onClick: () => onRaised(created) },
      });
      onRaised(created);
    } catch (err) {
      setServerError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const addLink = async () => {
    const r = await qAsk({
      title: t('wr.add_link_title', { defaultValue: 'Add a link' }),
      fields: [
        { label: t('wr.link_label', { defaultValue: 'Label' }) },
        { label: t('wr.link_url', { defaultValue: 'URL' }), placeholder: 'https://…' },
      ],
      okLabel: t('wr.add', { defaultValue: 'Add' }),
    });
    const url = r?.[1]?.trim();
    if (!url) return;
    setLinks((l) => [...l, { label: r?.[0]?.trim() || url, url }]);
  };

  if (!open) return null;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="xl"
      testId="wr-raise"
      title={t('wr.raise_title', { defaultValue: 'Raise a request' })}
      subtitle={t('wr.raise_sub', { defaultValue: 'Tell another department what you need, by when, and what it is worth.' })}
      footer={
        // The three controls used to sit flush in one row with the server's
        // error squeezed beside them on a single unwrapping line. The error
        // is now its own full-width row above, and the draft toggle is
        // separated from the two buttons by a rule rather than by a gap.
        <div className="wr wr-foot">
          {serverError && (
            <div className="wr-banner err wr-foot-err" role="alert">
              <span>{serverError}</span>
            </div>
          )}
          <div className="wr-foot-row">
            <label className="wr-tog wr-foot-draft">
              <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
              {t('wr.save_draft', { defaultValue: 'Save as draft' })}
            </label>
            <div className="wr-foot-acts">
              <button type="button" className="wr-btn-quiet" onClick={onClose} disabled={busy}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button type="button" className="wr-btn-quiet on" onClick={() => void submit()} disabled={busy} data-testid="wr-raise-submit">
                {busy ? t('wr.raising', { defaultValue: 'Raising…' }) : t('wr.raise', { defaultValue: 'Raise' })}
              </button>
            </div>
          </div>
        </div>
      }
    >
      <div className="wr flex flex-col gap-4">
        {/* ── Start from a template ───────────────────────────────
            A department raises the same shape over and over - the same
            types, the same questions, the same discipline split. This is
            that shape, once, rather than a blank form every time. */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="wr-lab">{t('wr.start_from', { defaultValue: 'Start from' })}</span>
          {fromTemplate ? (
            <span className="wr-chip" title={fromTemplate.title} data-testid="wr-template-chip">
              <span className="tag" style={{ background: 'transparent' }}>
                {t('wr.is_template', { defaultValue: 'template' })}
              </span>
              <span className="lbl">{fromTemplate.title}</span>
            </span>
          ) : (
            <span className="wr-hint">{t('wr.blank_request', { defaultValue: 'A blank request' })}</span>
          )}
          <button
            type="button"
            className="wr-btn-quiet"
            onClick={(e) => setPicker({ at: e.currentTarget, what: 'template' })}
            data-testid="wr-template-btn"
          >
            {fromTemplate ? t('wr.template_change', { defaultValue: 'Pick another template…' }) : t('wr.template_use', { defaultValue: 'Use a template…' })}
          </button>
          {fromTemplate && (
            <button
              type="button"
              className="wr-btn-quiet"
              onClick={() => setFromTemplate(null)}
              title={t('wr.template_detach_hint', { defaultValue: 'Keep what has been filled in, forget where it came from' })}
            >
              {t('wr.template_detach', { defaultValue: 'Detach' })}
            </button>
          )}
        </div>

        <div>
          <div className="wr-lab mb-2">
            {t('wr.department', { defaultValue: 'Department' })} {touched && errors.dept && <span className="err ml-2 normal-case tracking-normal">{errors.dept}</span>}
          </div>
          {active.length === 0 ? (
            <div className="wr-empty">{t('wr.no_departments', { defaultValue: 'No active departments are configured.' })}</div>
          ) : (
            <div className="wr-deptcards">
              {active.map((d) => (
                <button key={d.key} type="button" className="wr-deptcard" aria-pressed={dept === d.key} style={{ ['--dc' as string]: resolveColour(d.colour) }} onClick={() => setDept(d.key)}>
                  <b>{d.name}</b>
                  {d.description && <span>{d.description}</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {department && (
          <div>
            <div className="wr-lab mb-2">
              {t('wr.request_types', { defaultValue: 'Request types' })}{' '}
              <span className="wr-hint ml-1 normal-case tracking-normal">
                {t('wr.request_types_hint', { defaultValue: 'pick every one that applies' })}
              </span>
              {touched && errors.type && <span className="err ml-2 normal-case tracking-normal">{errors.type}</span>}
            </div>
            <div className="wr-typechips" role="group" aria-label={t('wr.request_types', { defaultValue: 'Request types' })}>
              {offered.map((rt) => (
                <button
                  key={rt.key}
                  type="button"
                  className="wr-typechip"
                  aria-pressed={typeKeys.includes(rt.key)}
                  onClick={() => toggleType(rt.key)}
                  data-testid={`wr-type-${rt.key}`}
                >
                  <span className="tick" aria-hidden>
                    {typeKeys.includes(rt.key) ? '✓' : '+'}
                  </span>
                  {rt.label}
                </button>
              ))}
              {offered.length === 0 && <span className="wr-hint">{t('wr.no_types', { defaultValue: 'This department has no request types configured.' })}</span>}
            </div>
            {typeKeys.length > 1 && (
              <p className="wr-hint mt-1.5">
                {t('wr.types_union_hint', {
                  defaultValue_one: '{{count}} type - the form below asks its questions once.',
                  defaultValue_other: '{{count}} types - the form below asks each one’s questions once.',
                  defaultValue: '{{count}} types - the form below asks each one’s questions once.',
                  count: typeKeys.length,
                })}
              </p>
            )}
          </div>
        )}

        <div className="wr-form">
          <div className="wr-field">
            <label>
              {t('wr.job', { defaultValue: 'Job' })} <span className="req">*</span>
            </label>
            <button type="button" className={clsx('wr-in text-left', touched && errors.project && 'miss')} onClick={(e) => setPicker({ at: e.currentTarget, what: 'project' })} data-testid="wr-raise-job">
              {project ? (
                <>
                  <b className="wr-mono">{project.project_code ?? ''}</b> {project.name}
                </>
              ) : (
                <span className="wr-hint">{projects.isLoading ? t('wr.loading', { defaultValue: 'Loading…' }) : t('wr.pick_job', { defaultValue: 'Pick the job…' })}</span>
              )}
            </button>
            {touched && errors.project && <span className="err">{errors.project}</span>}
          </div>
          <div className="wr-field">
            <label>{t('wr.raised_by', { defaultValue: 'Raised by' })}</label>
            <div className="flex items-center gap-2 py-1 text-sm">
              {me ? (
                <>
                  <Avatar person={me} size={18} /> {me.name}
                </>
              ) : (
                <span className="wr-hint">{t('wr.you', { defaultValue: 'you' })}</span>
              )}
            </div>
          </div>
          <div className="wr-field wide">
            <label htmlFor="wr-raise-title">
              {t('wr.title_lbl', { defaultValue: 'Title' })} <span className="req">*</span>
            </label>
            <input id="wr-raise-title" className={clsx('wr-in', touched && errors.title && 'miss')} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('wr.title_ph', { defaultValue: 'e.g. MSB-1 switchboard build, Form 3b, 2500A' })} />
            {touched && errors.title && <span className="err">{errors.title}</span>}
          </div>
          <div className="wr-field wide">
            <label htmlFor="wr-raise-desc">{t('wr.desired_outcome', { defaultValue: 'Description / desired outcome' })}</label>
            <textarea id="wr-raise-desc" className="wr-in" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>

          {formFields.map((f) => (
            <DynamicField key={f.key} field={f} value={fields[f.key]} error={touched ? errors[`f:${f.key}`] : undefined} onChange={(v) => setFields((s) => ({ ...s, [f.key]: v }))} />
          ))}

          {disciplines.length > 0 && (
            <div className="wr-field wide">
              <label>{t('wr.per_discipline', { defaultValue: 'Estimated · cost centre' })}</label>
              <div className="wr-disc">
                <span className="h">{t('wr.discipline', { defaultValue: 'Discipline' })}</span>
                <span className="h">{t('wr.cost_centre', { defaultValue: 'Cost centre' })}</span>
                <span className="h">{t('wr.est_hours', { defaultValue: 'Est. hours' })}</span>
                {disciplines.map((d) => (
                  <DisciplineRow key={d} name={d} cc={costCentres[d] ?? ''} hours={estimated[d] ?? ''} error={touched ? errors[`h:${d}`] : undefined} onCc={(v) => setCostCentres((s) => ({ ...s, [d]: v }))} onHours={(v) => setEstimated((s) => ({ ...s, [d]: v }))} />
                ))}
              </div>
            </div>
          )}

          <div className="wr-field">
            <label htmlFor="wr-raise-quoted">{t('wr.quoted_hours', { defaultValue: 'Quoted hours' })}</label>
            <input id="wr-raise-quoted" className={clsx('wr-in', touched && errors.quoted && 'miss')} inputMode="decimal" value={quoted} onChange={(e) => setQuoted(e.target.value.replace(/[^\d.,]/g, ''))} placeholder="—" />
            {touched && errors.quoted && <span className="err">{errors.quoted}</span>}
          </div>
          <div className="wr-field">
            <label>{t('wr.priority_lbl', { defaultValue: 'Priority' })}</label>
            <div className="wr-seg" role="group" aria-label={t('wr.priority_lbl', { defaultValue: 'Priority' })}>
              {PRIORITIES.map((p) => (
                <button key={p} type="button" aria-pressed={priority === p} onClick={() => setPriority(p)}>
                  {t(`wr.priority.${p}`, { defaultValue: PRIORITY_LABEL[p] })}
                </button>
              ))}
            </div>
          </div>
          <div className="wr-field">
            <label htmlFor="wr-raise-info">{t('wr.info_by', { defaultValue: 'Info required by' })}</label>
            <input id="wr-raise-info" type="date" className="wr-in" value={infoBy} onChange={(e) => setInfoBy(e.target.value)} />
          </div>
          <div className="wr-field">
            <label htmlFor="wr-raise-due">{t('wr.due', { defaultValue: 'Due' })}</label>
            <input id="wr-raise-due" type="date" className="wr-in" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>

          <div className="wr-field">
            <label>{t('wr.assignees', { defaultValue: 'Assignees' })}</label>
            <button type="button" className="wr-in text-left" onClick={(e) => setPicker({ at: e.currentTarget, what: 'assignees' })}>
              {assignees.length ? fmtList(assignees.map(userName)) : <span className="wr-hint">{department?.member_ids.length ? t('wr.pick_from_dept', { defaultValue: 'Pick from the department…' }) : t('wr.pick_anyone', { defaultValue: 'Pick anyone…' })}</span>}
            </button>
          </div>
          <div className="wr-field">
            <label>{t('wr.responsible', { defaultValue: 'Responsible' })}</label>
            <button type="button" className="wr-in text-left" onClick={(e) => setPicker({ at: e.currentTarget, what: 'responsible' })}>
              {responsible ? userName(responsible) : <span className="wr-hint">{t('wr.pick_responsible', { defaultValue: 'Who is responsible?' })}</span>}
            </button>
          </div>

          <div className="wr-field wide">
            <label>{t('wr.links', { defaultValue: 'Links' })}</label>
            <div className="flex flex-wrap items-center gap-1.5">
              {links.map((l, i) => (
                <span key={`${l.url}-${i}`} className="wr-chip" title={l.url}>
                  <span className="lbl">{l.label}</span>
                  <button type="button" className="wr-btn-quiet" aria-label={t('wr.remove_link', { defaultValue: 'Remove link' })} onClick={() => setLinks((s) => s.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </span>
              ))}
              <button type="button" className="wr-btn-quiet" onClick={() => void addLink()}>
                {t('wr.add_link', { defaultValue: 'Add link…' })}
              </button>
              <span className="wr-hint">{t('wr.attach_after', { defaultValue: 'Files can be attached once the request is raised.' })}</span>
            </div>
          </div>
        </div>
      </div>

      {picker && (
        <Picker
          anchor={picker.at}
          multi={picker.what === 'assignees'}
          selected={
            picker.what === 'project'
              ? projectId
                ? [projectId]
                : []
              : picker.what === 'template'
                ? fromTemplate
                  ? [fromTemplate.id]
                  : []
                : picker.what === 'assignees'
                  ? assignees
                  : responsible
                    ? [responsible]
                    : []
          }
          options={
            picker.what === 'project'
              ? (projects.data ?? []).map((p) => ({ id: p.id, label: p.name, sub: p.project_code ?? '' }))
              : picker.what === 'template'
                ? (templates.data ?? []).map((tpl) => ({ id: tpl.id, label: tpl.title, sub: [departments.find((d) => d.key === tpl.department)?.name, tpl.reference].filter(Boolean).join(' · ') }))
                : pool.map((u) => ({ id: u.id, label: u.full_name || u.email, sub: u.email, lead: <Avatar person={{ id: u.id, name: u.full_name || u.email }} size={18} /> }))
          }
          placeholder={
            picker.what === 'project'
              ? t('wr.pick_job_search', { defaultValue: 'Search jobs by code or name…' })
              : picker.what === 'template'
                ? t('wr.pick_template', { defaultValue: 'Which shape are you raising?' })
                : t('wr.pick_search', { defaultValue: 'Search…' })
          }
          emptyText={
            picker.what === 'template'
              ? templates.isLoading
                ? t('wr.loading', { defaultValue: 'Loading…' })
                : templates.isError
                  ? errorText(templates.error)
                  : t('wr.no_templates', { defaultValue: 'No templates yet - mark a request as a template from its menu and it will be offered here.' })
              : undefined
          }
          onClose={() => setPicker(null)}
          onChange={(ids) => {
            if (picker.what === 'project') setProjectId(ids[0] ?? '');
            else if (picker.what === 'template') {
              const tpl = (templates.data ?? []).find((x) => x.id === ids[0]);
              if (tpl) applyTemplate(tpl);
            } else if (picker.what === 'assignees') setAssignees(ids);
            else setResponsible(ids[0] ?? null);
          }}
        />
      )}
    </WideModal>
  );
}

function DisciplineRow({ name, cc, hours, error, onCc, onHours }: { name: string; cc: string; hours: string; error?: string; onCc: (v: string) => void; onHours: (v: string) => void }) {
  const { t } = useTranslation();
  return (
    <>
      <span>{name}</span>
      <input className="wr-in" value={cc} onChange={(e) => onCc(e.target.value)} placeholder={t('wr.cost_centre_ph', { defaultValue: 'e.g. 25406-SB' })} aria-label={`${name} cost centre`} />
      <span className="flex flex-col">
        <input className={clsx('wr-in', error && 'miss')} inputMode="decimal" value={hours} onChange={(e) => onHours(e.target.value.replace(/[^\d.,]/g, ''))} placeholder="0" aria-label={`${name} hours`} />
        {error && <span className="err">{error}</span>}
      </span>
    </>
  );
}

function DynamicField({ field, value, error, onChange }: { field: RequestField; value: unknown; error?: string; onChange: (v: unknown) => void }) {
  const id = `wr-f-${field.key}`;
  const str = value === undefined || value === null ? '' : String(value);
  return (
    <div className={clsx('wr-field', field.type === 'area' && 'wide')}>
      <label htmlFor={id}>
        {field.label} {field.required && <span className="req">*</span>}
      </label>
      {field.type === 'area' ? (
        <textarea id={id} className={clsx('wr-in', error && 'miss')} value={str} onChange={(e) => onChange(e.target.value)} />
      ) : field.type === 'bool' ? (
        <label className="wr-tog py-1.5">
          <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {value ? 'Yes' : 'No'}
        </label>
      ) : field.type === 'select' ? (
        <select id={id} className={clsx('wr-in', error && 'miss')} value={str} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className={clsx('wr-in', error && 'miss')}
          type={field.type === 'date' ? 'date' : field.type === 'url' ? 'url' : 'text'}
          inputMode={field.type === 'number' ? 'decimal' : undefined}
          value={str}
          onChange={(e) => onChange(field.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value.replace(',', '.'))) : e.target.value)}
        />
      )}
      {error && <span className="err">{error}</span>}
    </div>
  );
}
