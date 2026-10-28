// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The pieces every logistics plan panel is built from: the loading and error
// frame of a list, the status badge, the row buttons, and one form dialog
// that is driven by a list of fields.

import { useState, type ReactNode } from 'react';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import clsx from 'clsx';
import type { UseQueryResult } from '@tanstack/react-query';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';

import { planProblem, type Body, type Can, type LinkKind, type PlanCatalogue, type PlanProblem, type Verdict } from './api';
import { useConcept, useLinkOptions, useWords, type Identified, type Resource } from './hooks';
import {
  findingText,
  formProblems,
  moveLabel,
  absent,
  denied,
  frozenOf,
  reasonText,
  stateLabel,
  stateTone,
  toBody,
  toFormValues,
  type Field,
  type FormValue,
  type FormValues,
  type Lifecycle,
} from './rules';
import { tx, type TextKey } from './texts';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── List frame ───────────────────────────────────────────────────────── */

/** Loading, error with retry, or the content: the three faces of every panel. */
export function Loaded<T>({ query, children }: { query: UseQueryResult<T>; children: (data: T) => ReactNode }) {
  const { t } = useWords();
  if (query.isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" data-testid="plan-loading">
        <div className="h-16 animate-pulse rounded-lg bg-surface-secondary" />
        <div className="h-16 animate-pulse rounded-lg bg-surface-secondary" />
      </div>
    );
  }
  if (query.isError || query.data === undefined) {
    return (
      <div role="alert" className="rounded-lg border border-semantic-error/30 bg-semantic-error/5 p-4" data-testid="plan-error">
        <p className="text-sm font-medium text-content-primary">{tx(t, 'load_error')}</p>
        <p className="mt-1 text-sm text-content-secondary">{getErrorMessage(query.error)}</p>
        <Button size="sm" variant="secondary" className="mt-3" onClick={() => void query.refetch()}>
          {tx(t, 'retry')}
        </Button>
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

export function PlanEmpty({
  icon,
  title,
  body,
  action,
  onAction,
  may,
}: {
  icon: ReactNode;
  title: TextKey;
  body: TextKey;
  action?: TextKey;
  onAction?: () => void;
  /** The server's verdict on the action; the button is left out or disabled accordingly. */
  may?: Verdict;
}) {
  const { t } = useWords();
  return (
    <EmptyState
      icon={icon}
      title={tx(t, title)}
      description={tx(t, body)}
      action={
        action && onAction && !absent(may) ? (
          <Button size="sm" onClick={onAction} disabled={denied(may)} title={reasonText(t, may)}>
            <Plus size={14} className="mr-1" />
            {tx(t, action)}
          </Button>
        ) : undefined
      }
    />
  );
}

/** The heading of a panel with its one primary action. */
export function PanelHead({
  title,
  action,
  onAction,
  may,
  children,
}: {
  title: TextKey;
  action?: TextKey;
  onAction?: () => void;
  may?: Verdict;
  children?: ReactNode;
}) {
  const { t } = useWords();
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-base font-semibold text-content-primary">{tx(t, title)}</h3>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        {action && onAction && !absent(may) && (
          <Button size="sm" onClick={onAction} disabled={denied(may)} title={reasonText(t, may)} data-testid={`plan-${action}`}>
            <Plus size={14} className="mr-1" />
            {tx(t, action)}
          </Button>
        )}
      </div>
    </div>
  );
}

export function StateBadge({ state }: { state: string }) {
  const { t } = useWords();
  return (
    <span data-testid="plan-state" data-state={state}>
      <Badge variant={stateTone(state)} size="sm">
        {stateLabel(t, state)}
      </Badge>
    </span>
  );
}

/** A labelled value of a card; nothing at all when the value is empty. */
export function Fact({ label, children }: { label: TextKey; children: ReactNode }) {
  const { t } = useWords();
  if (children === null || children === undefined || children === '' || children === false) return null;
  return (
    <div className="min-w-0">
      <dt className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{tx(t, label)}</dt>
      <dd className="text-sm text-content-primary">{children}</dd>
    </div>
  );
}

export function Card({ children, testId, alert }: { children: ReactNode; testId?: string; alert?: boolean }) {
  return (
    <li
      data-testid={testId}
      className={clsx(
        'rounded-lg border bg-surface-elevated/90 p-3',
        alert ? 'border-semantic-error/40' : 'border-border-light',
      )}
    >
      {children}
    </li>
  );
}

/* ── Row buttons ──────────────────────────────────────────────────────── */

/**
 * Edit, the status moves and delete of one record, as the server's verdicts
 * on that record say: a move that does not exist from the current status is
 * not shown, one that is refused right now is shown disabled with the reason.
 * A record without verdicts offers edit and delete and no move.
 */
export function RowActions<T extends Identified & { state?: string; can?: Can }>({
  resource,
  record,
  lifecycle,
  noEdit,
  noDelete,
}: {
  resource: Resource<T>;
  record: T;
  lifecycle?: Lifecycle;
  noEdit?: boolean;
  noDelete?: boolean;
}) {
  const { t } = useWords();
  const [confirm, setConfirm] = useState(false);
  const busy = resource.busyId === record.id;
  const can = record.can;
  const moves = Object.entries(can?.transitions ?? {}).filter(([, verdict]) => verdict.applies);
  // A record that carries verdicts and none for delete cannot be deleted at all.
  const deletable = !noDelete && (can ? !!can.delete && can.delete.applies : true);
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {moves.map(([target, verdict]) => (
        <Button
          key={target}
          size="sm"
          variant="secondary"
          disabled={busy || !verdict.allowed}
          title={reasonText(t, verdict)}
          data-testid={`plan-move-${target}`}
          onClick={() => void resource.move(record.id, target)}
        >
          {lifecycle ? moveLabel(t, lifecycle, target) : target}
        </Button>
      ))}
      {!noEdit && !absent(can?.edit) && (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy || denied(can?.edit)}
          aria-label={tx(t, 'edit')}
          title={reasonText(t, can?.edit) ?? tx(t, 'edit')}
          onClick={() => resource.open(record)}
        >
          <Pencil size={14} />
        </Button>
      )}
      {deletable && (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy || denied(can?.delete)}
          aria-label={tx(t, 'delete')}
          title={reasonText(t, can?.delete) ?? tx(t, 'delete')}
          onClick={() => setConfirm(true)}
        >
          <Trash2 size={14} />
        </Button>
      )}
      <ConfirmDialog
        open={confirm}
        title={tx(t, 'delete_title')}
        message={tx(t, 'delete_body')}
        confirmLabel={tx(t, 'delete')}
        cancelLabel={tx(t, 'cancel')}
        onCancel={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          void resource.remove(record.id);
        }}
      />
    </div>
  );
}

/* ── Form dialog ──────────────────────────────────────────────────────── */

export interface FormDialogProps {
  title: TextKey;
  fields: Field[];
  /** The record being changed, or nothing for a new one. */
  record?: object | null;
  /** Starting values of a new record. */
  defaults?: object;
  projectId: string;
  catalogue?: PlanCatalogue | null;
  /** Sends the body; a rejection is shown in the dialog with the server's reason. */
  onSubmit: (body: Body) => Promise<unknown>;
  onSaved?: () => void | Promise<void>;
  onClose: () => void;
  /** Always send every field, for the routes that replace a whole record. */
  sendAll?: boolean;
  /** Last word on the body, for a record whose form fields differ from its wire fields. */
  shape?: (body: Body, values: FormValues) => Body;
  /** Said above the fields, for a record part of which can no longer be changed. */
  note?: TextKey;
}

/** A choice among the records of the project the server offers for one kind of link. */
function LinkSelect({
  id,
  label,
  projectId,
  kind,
  value,
  onChange,
}: {
  id: string;
  label: string;
  projectId: string;
  kind: LinkKind;
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useWords();
  const options = useLinkOptions(projectId, kind);
  const rows = options.data ?? [];
  return (
    <>
      <select id={id} aria-label={label} className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{tx(t, 'not_set')}</option>
        {/* A link the list no longer offers stays as it is until the reader changes it. */}
        {value && !rows.some((r) => r.id === value) && <option value={value}>{tx(t, 'link.kept')}</option>}
        {rows.map((r) => (
          <option key={r.id} value={r.id}>
            {r.detail ? `${r.label} (${r.detail})` : r.label}
          </option>
        ))}
      </select>
      {options.isError && (
        <p role="alert" className="mt-1 text-xs text-semantic-error">
          {tx(t, 'link.failed')}
        </p>
      )}
      {options.isSuccess && rows.length === 0 && (
        <p className="mt-1 text-xs text-content-tertiary" data-testid={`plan-link-none-${kind}`}>
          {tx(t, `link.none.${kind}`)}
        </p>
      )}
    </>
  );
}

/** One dialog for every record of the plan, drawn from its list of fields. */
export function FormDialog({
  title,
  fields: everyField,
  record,
  defaults,
  projectId,
  catalogue,
  onSubmit,
  onSaved,
  onClose,
  sendAll,
  shape,
  note,
}: FormDialogProps) {
  const words = useWords();
  const { t } = words;
  // A field the server no longer changes on this record is not offered, so it cannot be sent either.
  const frozen = frozenOf(record);
  const fields = frozen.length > 0 ? everyField.filter((f) => !frozen.includes(f.name)) : everyField;
  const said = note ?? (fields.length < everyField.length ? 'form.frozen_note' : undefined);
  // The zone is taken once: the same clock turns the stored instants into the form and the form back into instants.
  const siteZone = useConcept(projectId).data?.site_timezone;
  const [zone] = useState(siteZone);
  const [initial] = useState<FormValues>(() =>
    toFormValues(fields, (record ?? defaults) as Record<string, unknown> | undefined, zone),
  );
  const [values, setValues] = useState<FormValues>(initial);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<PlanProblem | null>(null);

  const problems = formProblems(fields, values);
  const errorOf = (path: string) => {
    const why = problems[path];
    return tried && why ? tx(t, why) : undefined;
  };

  const send = async () => {
    if (Object.keys(problems).length > 0) {
      setTried(true);
      return;
    }
    const body = toBody(fields, values, record && !sendAll ? initial : null, zone);
    if (record && !sendAll && Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      await onSubmit(shape ? shape(body, values) : body);
      await onSaved?.();
      onClose();
    } catch (err) {
      setProblem(planProblem(err));
    } finally {
      setBusy(false);
    }
  };

  const control = (f: Field, value: FormValue, set: (v: FormValue) => void, id: string, label: string) => {
    const common = { id, 'aria-label': label, className: inputCls };
    switch (f.kind) {
      case 'textarea':
        return (
          <textarea
            {...common}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
            value={value as string}
            onChange={(e) => set(e.target.value)}
          />
        );
      case 'checkbox':
        return (
          <input
            id={id}
            aria-label={label}
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={value === true}
            onChange={(e) => set(e.target.checked)}
          />
        );
      case 'select':
        return (
          <select {...common} value={value as string} onChange={(e) => set(e.target.value)}>
            {(!f.required || value === '') && <option value="">{tx(t, 'not_set')}</option>}
            {f.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        );
      case 'multi': {
        const picked = value as string[];
        return (
          <div id={id} role="group" aria-label={label} className="flex flex-wrap gap-x-3 gap-y-1">
            {f.options.map((o) => (
              <label key={o.value} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border"
                  checked={picked.includes(o.value)}
                  onChange={(e) =>
                    set(e.target.checked ? [...picked, o.value] : picked.filter((x) => x !== o.value))
                  }
                />
                {o.label}
              </label>
            ))}
          </div>
        );
      }
      case 'link':
        return (
          <LinkSelect id={id} label={label} projectId={projectId} kind={f.link} value={value as string} onChange={(v) => set(v)} />
        );
      case 'person':
        return (
          <ProjectPeopleSelect id={id} projectId={projectId} value={value as string} onChange={(userId) => set(userId)} />
        );
      case 'rows':
        return null;
      default:
        return (
          <input
            {...common}
            type={
              f.kind === 'date' ? 'date' : f.kind === 'datetime' ? 'datetime-local' : f.kind === 'time' ? 'time' : f.kind === 'int' ? 'number' : 'text'
            }
            inputMode={f.kind === 'decimal' ? 'decimal' : undefined}
            min={f.kind === 'int' ? 0 : undefined}
            value={value as string}
            onChange={(e) => set(e.target.value)}
            title={f.kind === 'datetime' && zone ? tx(t, 'form.site_time', { zone }) : undefined}
          />
        );
    }
  };

  const rowsEditor = (f: Extract<Field, { kind: 'rows' }>) => {
    const rows = (values[f.name] as FormValues[]) ?? [];
    const setRows = (next: FormValues[]) => setValues((v) => ({ ...v, [f.name]: next }));
    return (
      <div className="space-y-2" data-testid={`plan-rows-${f.name}`}>
        {rows.map((row, i) => (
          <div key={i} className="flex items-start gap-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-2">
            <div className="grid flex-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {f.columns.map((c) => {
                const id = `plan-f-${f.name}-${i}-${c.name}`;
                const label = tx(t, c.label);
                return (
                  <WideModalField
                    key={c.name}
                    label={label}
                    htmlFor={id}
                    required={c.required}
                    error={errorOf(`${f.name}.${i}.${c.name}`)}
                    span={c.wide ? 3 : 1}
                  >
                    {control(c, row[c.name] ?? '', (v) => setRows(rows.map((r, j) => (j === i ? { ...r, [c.name]: v } : r))), id, label)}
                  </WideModalField>
                );
              })}
            </div>
            <Button
              size="sm"
              variant="ghost"
              aria-label={tx(t, 'remove_row')}
              title={tx(t, 'remove_row')}
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
            >
              <X size={14} />
            </Button>
          </div>
        ))}
        <Button size="sm" variant="secondary" onClick={() => setRows([...rows, toFormValues(f.columns)])} data-testid={`plan-add-row-${f.name}`}>
          <Plus size={14} className="mr-1" />
          {tx(t, 'add_row')}
        </Button>
      </div>
    );
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={tx(t, title)}
      busy={busy}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {tx(t, 'cancel')}
          </Button>
          <Button onClick={() => void send()} loading={busy} data-testid="plan-form-save">
            {tx(t, 'save')}
          </Button>
        </div>
      }
    >
      {problem && (
        <div role="alert" className="mb-4 rounded-lg border border-semantic-error/30 bg-semantic-error/5 p-3" data-testid="plan-form-problem">
          <p className="text-sm font-medium text-content-primary">{problem.message}</p>
          {problem.violations.length > 0 && (
            <>
              <p className="mt-2 text-xs font-medium text-content-secondary">{tx(t, 'blockers')}</p>
              <ul className="mt-1 list-disc pl-5 text-sm text-content-primary">
                {problem.violations.map((v, i) => (
                  <li key={`${v.code}-${i}`}>{findingText(words, v, catalogue)}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {said && (
        <p className="mb-4 rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-content-secondary" data-testid="plan-form-note">
          {tx(t, said)}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((f) => {
          const id = `plan-f-${f.name}`;
          const label = tx(t, f.label);
          return (
            <WideModalField
              key={f.name}
              label={label}
              htmlFor={f.kind === 'rows' ? undefined : id}
              required={f.required}
              hint={f.hint ? tx(t, f.hint) : undefined}
              error={errorOf(f.name)}
              span={f.wide || f.kind === 'rows' || f.kind === 'textarea' || f.kind === 'multi' ? 2 : 1}
            >
              {f.kind === 'rows'
                ? rowsEditor(f)
                : control(f, values[f.name] ?? '', (v) => setValues((old) => ({ ...old, [f.name]: v })), id, label)}
            </WideModalField>
          );
        })}
      </div>
    </WideModal>
  );
}
