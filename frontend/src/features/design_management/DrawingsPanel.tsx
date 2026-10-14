// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The drawing register. A drawing is a document container of the CDE, so its
// number, revision, status and state are read from there; this screen adds
// what only the register knows (phase, schedule line, designer, dates). A new
// drawing shows the number it will get before it is saved, and a number the
// scheme does not allow is refused with the field that is wrong.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileStack } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  createDrawing,
  readTitleBlock,
  supersedeDrawing,
  updateDrawing,
  type CdeState,
  type Drawing,
  type DrawingCreateInput,
  type DrawingPatchInput,
} from './api';
import {
  CDE_TONE,
  CELL,
  CELL_MUTED,
  PanelHeader,
  Table,
  ToneBadge,
  deliverableOptions,
  phaseField,
  roleOptions,
  roleTitle,
  wbsOptions,
  type DesignContext,
  WriteButton,
} from './DesignBits';
import { FormDialog, str, type FieldSpec, type FormValues } from './FormDialog';
import { NumberPreviewBox, numberPartFields, numberRequest } from './NumberForm';
import { NumberingTools } from './NumberingTools';
import { CDE_STATE, fieldLabel, phaseName, schemeName, ui, vocab, vocabOptions, type TFn } from './labels';
import { changedFields, recipientName, typedFields } from './rules';

type Dialog =
  | { kind: 'create' }
  | { kind: 'edit'; drawing: Drawing }
  | { kind: 'supersede'; drawing: Drawing }
  | { kind: 'title-block'; drawing: Drawing }
  | null;

function drawingValues(d: Drawing | null): FormValues {
  return {
    title: d?.title ?? '',
    scale: d?.scale ?? '',
    sheet_size: d?.sheet_size ?? '',
    phase_code: d?.phase_code ?? '',
    deliverable_id: d?.deliverable_id ?? '',
    wbs_node_id: d?.wbs_node_id ?? '',
    role_id: d?.role_id ?? '',
    planned_first_issue: d?.planned_first_issue ?? '',
    forecast_issue: d?.forecast_issue ?? '',
  };
}

const NULLABLE = ['phase_code', 'deliverable_id', 'wbs_node_id', 'role_id', 'planned_first_issue', 'forecast_issue'] as const;

export function DrawingsPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [search, setSearch] = useState('');
  const [state, setState] = useState<CdeState | ''>('');
  const scheme = ctx.setup.scheme;
  const phases = ctx.setup.phases;

  const shown = useMemo(() => {
    const q = search.trim().toLocaleLowerCase();
    return ctx.drawings.filter((d) => {
      if (state && d.cde_state !== state) return false;
      if (!q) return true;
      return [d.number, d.title, ...(d.aliases ?? [])].some((text) => (text ?? '').toLocaleLowerCase().includes(q));
    });
  }, [ctx.drawings, search, state]);

  const shared: FieldSpec[] = [
    { name: 'role_id', label: ui(t, 'design.ui.drawings.by'), type: 'select', options: roleOptions(ctx) },
    phaseField(ctx, t),
    { name: 'deliverable_id', label: ui(t, 'design.ui.drawings.schedule_line'), type: 'select', options: deliverableOptions(ctx) },
    { name: 'wbs_node_id', label: ui(t, 'design.ui.field.wbs'), type: 'select', options: wbsOptions(ctx) },
    { name: 'sheet_size', label: ui(t, 'design.ui.drawings.sheet_size'), type: 'text' },
    { name: 'scale', label: ui(t, 'design.ui.drawings.scale'), type: 'text' },
    { name: 'planned_first_issue', label: ui(t, 'design.ui.drawings.planned_issue'), type: 'date' },
    { name: 'forecast_issue', label: ui(t, 'design.ui.drawings.forecast_issue'), type: 'date' },
  ];
  const titleField: FieldSpec = { name: 'title', label: ui(t, 'design.ui.drawings.title_field'), type: 'text', required: true };
  const parts = numberPartFields(ctx.labels, typedFields(scheme));
  const createFields: FieldSpec[] = [
    titleField,
    ...shared.slice(0, 4),
    ...parts,
    ...shared.slice(4),
    { name: 'number', label: ui(t, 'design.ui.drawings.own_number'), type: 'text', hint: ui(t, 'design.ui.drawings.own_number_hint') },
  ];
  const createInitial: FormValues = { ...drawingValues(null), number: '', ...Object.fromEntries(parts.map((f) => [f.name, ''])) };
  const violationField = (code: string) => {
    const field = scheme.fields.find((f) => f.code === code);
    return field ? fieldLabel(ctx.labels, field) : code;
  };

  const others = (drawing: Drawing) =>
    ctx.drawings.filter((d) => d.id !== drawing.id).map((d) => ({ value: d.container_id, label: `${d.number} ${d.title}` }));

  return (
    <div className="space-y-4" data-testid="design-drawings-panel">
      <PanelHeader
        title={ui(t, 'design.ui.drawings.title')}
        hint={ui(t, 'design.ui.drawings.hint', { scheme: schemeName(ctx.labels, scheme) })}
        action={
          <WriteButton onClick={() => setDialog({ kind: 'create' })} data-testid="drawing-add">
            {ui(t, 'design.ui.drawings.add')}
          </WriteButton>
        }
      />

      {ctx.drawings.length === 0 ? (
        <EmptyState
          icon={<FileStack size={28} />}
          title={ui(t, 'design.ui.drawings.empty_title')}
          description={ui(t, 'design.ui.drawings.empty_body')}
          action={{ label: ui(t, 'design.ui.drawings.add'), onClick: () => setDialog({ kind: 'create' }) }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              autoComplete="off"
              className="w-64 rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
              placeholder={ui(t, 'design.ui.drawings.search')}
              aria-label={ui(t, 'design.ui.drawings.search')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="drawing-search"
            />
            <select
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
              aria-label={ui(t, 'design.ui.drawings.state_filter')}
              value={state}
              onChange={(e) => setState(e.target.value as CdeState | '')}
            >
              <option value="">{ui(t, 'design.ui.drawings.all_states')}</option>
              {vocabOptions(t, CDE_STATE).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          {shown.length === 0 ? (
            <p className="py-6 text-center text-sm text-content-tertiary">{ui(t, 'design.ui.drawings.none_match')}</p>
          ) : (
            <Table
              testId="drawings-table"
              head={[
                ui(t, 'design.ui.drawings.number'),
                ui(t, 'design.ui.drawings.title_field'),
                ui(t, 'design.ui.drawings.revision'),
                ui(t, 'design.ui.drawings.status'),
                ui(t, 'design.ui.field.phase'),
                ui(t, 'design.ui.drawings.by'),
                ui(t, 'design.ui.drawings.last_issue'),
                '',
              ]}
            >
              {shown.map((d) => {
                const recipients = (d.last_issue?.recipients ?? [])
                  .map((key) => recipientName(key, ctx.roles) ?? ui(t, 'design.ui.issue.distribution_list'))
                  .filter((name, i, all) => all.indexOf(name) === i);
                return (
                  <tr key={d.id} data-testid="drawing-row">
                    <td className={`${CELL} font-mono`}>
                      {d.number}
                      {(d.aliases ?? []).length > 0 && (
                        <p className="font-sans text-2xs text-content-tertiary">
                          {ui(t, 'design.ui.drawings.formerly', { numbers: fmtList(d.aliases) })}
                        </p>
                      )}
                    </td>
                    <td className={CELL}>
                      {d.title}
                      <span className="ml-1 inline-flex flex-wrap gap-1">
                        {d.legacy_scheme && <ToneBadge tone="warning">{ui(t, 'design.ui.drawings.legacy')}</ToneBadge>}
                        {d.title_block_mismatch && (
                          <ToneBadge tone="error" testId="title-block-mismatch">
                            {ui(t, 'design.ui.drawings.title_block_differs', { number: d.title_block_number ?? '' })}
                          </ToneBadge>
                        )}
                        {d.superseded_by_container_id && <ToneBadge tone="neutral">{ui(t, 'design.ui.drawings.superseded')}</ToneBadge>}
                      </span>
                    </td>
                    <td className={`${CELL_MUTED} font-mono`}>{d.revision_code ?? ''}</td>
                    <td className={CELL}>
                      <ToneBadge tone={CDE_TONE[d.cde_state]}>{vocab(t, CDE_STATE, d.cde_state)}</ToneBadge>
                      {d.suitability_code && <span className="ml-1 font-mono text-xs text-content-secondary">{d.suitability_code}</span>}
                    </td>
                    <td className={CELL_MUTED}>{phaseName(ctx.labels, phases, d.phase_code)}</td>
                    <td className={CELL_MUTED}>{roleTitle(ctx, d.role_id)}</td>
                    <td className={CELL_MUTED}>
                      {d.last_issue?.at ? (
                        <>
                          {fmtDate(d.last_issue.at)}
                          <p className="text-2xs text-content-tertiary">{fmtList(recipients)}</p>
                        </>
                      ) : (
                        ui(t, 'design.ui.drawings.not_issued')
                      )}
                    </td>
                    <td className={`${CELL} whitespace-nowrap text-right`}>
                      <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'edit', drawing: d })}>
                        {ui(t, 'design.ui.action.edit')}
                      </WriteButton>
                      <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'title-block', drawing: d })}>
                        {ui(t, 'design.ui.drawings.check_title_block')}
                      </WriteButton>
                      {!d.superseded_by_container_id && (
                        <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'supersede', drawing: d })}>
                          {ui(t, 'design.ui.drawings.supersede')}
                        </WriteButton>
                      )}
                    </td>
                  </tr>
                );
              })}
            </Table>
          )}
        </>
      )}

      <NumberingTools ctx={ctx} />

      {dialog?.kind === 'create' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.drawings.add')}
          subtitle={ui(t, 'design.ui.drawings.add_hint')}
          fields={createFields}
          initial={createInitial}
          submitLabel={ui(t, 'design.ui.drawings.add')}
          violationField={violationField}
          extra={(values) => <NumberPreviewBox ctx={ctx} values={values} />}
          submit={(values) => {
            const body: DrawingCreateInput = { ...numberRequest(values), title: str(values, 'title').trim() };
            for (const key of ['number', 'scale', 'deliverable_id', 'planned_first_issue', 'forecast_issue'] as const) {
              const value = str(values, key).trim();
              if (value) body[key] = value;
            }
            return createDrawing(ctx.projectId, body);
          }}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="drawing-form"
        />
      )}
      {dialog?.kind === 'edit' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.drawings.edit', { number: dialog.drawing.number })}
          fields={[titleField, ...shared]}
          initial={drawingValues(dialog.drawing)}
          submitLabel={ui(t, 'design.ui.action.save')}
          submit={(values) =>
            updateDrawing(ctx.projectId, dialog.drawing.id, changedFields<DrawingPatchInput>(drawingValues(dialog.drawing), values, NULLABLE))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'supersede' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.drawings.supersede_title', { number: dialog.drawing.number })}
          subtitle={ui(t, 'design.ui.drawings.supersede_body')}
          fields={[
            { name: 'by', label: ui(t, 'design.ui.drawings.superseded_by'), type: 'select', required: true, options: others(dialog.drawing) },
          ]}
          initial={{ by: '' }}
          submitLabel={ui(t, 'design.ui.drawings.supersede')}
          submit={(values) => supersedeDrawing(ctx.projectId, dialog.drawing.id, str(values, 'by'))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
      {dialog?.kind === 'title-block' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.drawings.title_block_title', { number: dialog.drawing.number })}
          subtitle={ui(t, 'design.ui.drawings.title_block_body')}
          fields={[{ name: 'text', label: ui(t, 'design.ui.drawings.title_block_text'), type: 'textarea', required: true }]}
          initial={{ text: '' }}
          submitLabel={ui(t, 'design.ui.drawings.check_title_block')}
          submit={(values) => readTitleBlock(ctx.projectId, dialog.drawing.id, str(values, 'text'))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
        />
      )}
    </div>
  );
}
