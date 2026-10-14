// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The numbering checks under the drawing register: test one number against
// the project's scheme, test every drawing at once, reserve the next number
// for a drawing that does not exist yet, and, after a scheme change, propose
// new numbers for the drawings that still carry an old one. Nothing is
// renumbered until the proposal is confirmed, and the old numbers stay
// searchable.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, XCircle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  allocateNumber,
  applyRenumber,
  bulkValidateNumbers,
  previewRenumber,
  validateNumber,
  type NumberIssue,
  type RenumberRow,
} from './api';
import { PanelHeader, phaseField, roleOptions, wbsOptions, type DesignContext, WriteButton } from './DesignBits';
import { NumberPreviewBox, numberPartFields, numberRequest } from './NumberForm';
import { FormDialog, type FieldSpec } from './FormDialog';
import { refusalText } from './hooks';
import { errorText, fieldLabel, ui, uiCount, type TFn } from './labels';
import { typedFields } from './rules';

export function NumberingTools({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const addToast = useToastStore((s) => s.addToast);
  const [number, setNumber] = useState('');
  const [reserving, setReserving] = useState(false);
  const [proposal, setProposal] = useState<RenumberRow[] | null>(null);
  const scheme = ctx.setup.scheme;
  const legacy = ctx.drawings.filter((d) => d.legacy_scheme).length;
  const onError = (err: unknown) => addToast({ type: 'error', title: refusalText(t, err) });

  const one = useMutation({ mutationFn: () => validateNumber(ctx.projectId, number.trim()), onError });
  const all = useMutation({ mutationFn: () => bulkValidateNumbers(ctx.projectId), onError });
  const propose = useMutation({ mutationFn: () => previewRenumber(ctx.projectId), onSuccess: setProposal, onError });
  const apply = useMutation({
    mutationFn: (rows: RenumberRow[]) => applyRenumber(ctx.projectId, Object.fromEntries(rows.map((r) => [r.drawing_id, r.new]))),
    onSuccess: () => {
      setProposal(null);
      ctx.onChanged();
    },
    onError,
  });

  const fieldName = (code: string | null) => {
    const field = scheme.fields.find((f) => f.code === code);
    return field ? fieldLabel(ctx.labels, field) : code ?? '';
  };
  const issueList = (issues: NumberIssue[]) => (
    <ul className="ml-4 list-disc text-xs text-content-secondary">
      {issues.map((issue, i) => (
        <li key={`${issue.code}-${i}`}>
          {issue.field && <span className="font-medium">{fieldName(issue.field)}: </span>}
          {errorText(t, issue.code)}
        </li>
      ))}
    </ul>
  );

  const reserveFields: FieldSpec[] = [
    { name: 'role_id', label: ui(t, 'design.ui.drawings.by'), type: 'select', options: roleOptions(ctx) },
    phaseField(ctx, t),
    { name: 'wbs_node_id', label: ui(t, 'design.ui.field.wbs'), type: 'select', options: wbsOptions(ctx) },
    { name: 'sheet_size', label: ui(t, 'design.ui.drawings.sheet_size'), type: 'text' },
    ...numberPartFields(ctx.labels, typedFields(scheme)),
  ];
  const bad = (all.data ?? []).filter((r) => !r.valid);
  const usable = (proposal ?? []).filter((r) => r.missing.length === 0);

  return (
    <section className="space-y-3 rounded-lg border border-border-light p-4" data-testid="numbering-tools">
      <PanelHeader
        title={ui(t, 'design.ui.numbering.title')}
        hint={ui(t, 'design.ui.numbering.hint')}
        action={
          <>
            <Button variant="secondary" size="sm" loading={all.isPending} onClick={() => all.mutate()} data-testid="numbers-check-all">
              {ui(t, 'design.ui.numbering.check_all')}
            </Button>
            <WriteButton variant="secondary" size="sm" onClick={() => setReserving(true)} data-testid="number-reserve">
              {ui(t, 'design.ui.numbering.reserve')}
            </WriteButton>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          autoComplete="off"
          className="w-72 rounded-md border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-sm"
          placeholder={ui(t, 'design.ui.numbering.check_placeholder')}
          aria-label={ui(t, 'design.ui.numbering.check_placeholder')}
          value={number}
          onChange={(e) => {
            setNumber(e.target.value);
            one.reset();
          }}
          data-testid="number-input"
        />
        <Button variant="secondary" size="sm" disabled={!number.trim()} loading={one.isPending} onClick={() => one.mutate()} data-testid="number-check">
          {ui(t, 'design.ui.numbering.check_single')}
        </Button>
      </div>
      {one.data && (
        <div role="status" data-testid="number-result" className="text-sm">
          {one.data.valid ? (
            <p className="flex items-center gap-1.5 text-semantic-success">
              <CheckCircle2 size={14} aria-hidden />
              {ui(t, 'design.ui.numbering.one_valid')}
            </p>
          ) : (
            <>
              <p className="flex items-center gap-1.5 text-semantic-error">
                <XCircle size={14} aria-hidden />
                {ui(t, 'design.ui.numbering.one_invalid')}
              </p>
              {issueList(one.data.issues)}
            </>
          )}
        </div>
      )}

      {all.data && (
        <div role="status" data-testid="numbers-result" className="space-y-2 text-sm">
          <p className={bad.length === 0 ? 'text-semantic-success' : 'text-content-primary'}>
            {bad.length === 0
              ? uiCount(t, 'design.ui.numbering.all_valid', all.data.length)
              : ui(t, 'design.ui.numbering.some_invalid', { bad: bad.length, total: all.data.length })}
          </p>
          {bad.map((row) => (
            <div key={row.drawing_id} className="rounded-md bg-surface-secondary p-2">
              <p className="font-mono text-content-primary">{row.number}</p>
              {issueList(row.issues)}
            </div>
          ))}
        </div>
      )}

      {legacy > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm" data-testid="legacy-numbers">
          <p className="text-content-primary">{uiCount(t, 'design.ui.numbering.legacy', legacy)}</p>
          <WriteButton need="manage" variant="secondary" size="sm" loading={propose.isPending} onClick={() => propose.mutate()} data-testid="renumber-propose">
            {ui(t, 'design.ui.numbering.propose')}
          </WriteButton>
        </div>
      )}

      {proposal && (
        <WideModal
          open
          size="md"
          onClose={() => setProposal(null)}
          busy={apply.isPending}
          title={ui(t, 'design.ui.numbering.proposal_title')}
          subtitle={ui(t, 'design.ui.numbering.proposal_body')}
          testId="renumber-dialog"
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setProposal(null)} disabled={apply.isPending}>
                {ui(t, 'design.ui.form.cancel')}
              </Button>
              <WriteButton need="manage" disabled={usable.length === 0} loading={apply.isPending} onClick={() => apply.mutate(usable)} data-testid="renumber-apply">
                {uiCount(t, 'design.ui.numbering.apply', usable.length)}
              </WriteButton>
            </div>
          }
        >
          {proposal.length === 0 ? (
            <p className="text-sm text-content-secondary">{ui(t, 'design.ui.numbering.proposal_empty')}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {proposal.map((row) => (
                <li key={row.drawing_id} className="flex flex-wrap items-center gap-2 font-mono">
                  <span className="text-content-secondary">{row.old}</span>
                  <span aria-hidden>→</span>
                  <span className="text-content-primary">{row.new}</span>
                  {row.missing.length > 0 && (
                    <span className="font-sans text-xs text-semantic-warning">
                      {ui(t, 'design.ui.numbering.proposal_skipped', { fields: fmtList(row.missing.map(fieldName)) })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </WideModal>
      )}

      {reserving && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.numbering.reserve')}
          subtitle={ui(t, 'design.ui.numbering.reserve_body')}
          fields={reserveFields}
          initial={Object.fromEntries(reserveFields.map((f) => [f.name, '']))}
          submitLabel={ui(t, 'design.ui.numbering.reserve')}
          violationField={fieldName}
          extra={(values) => <NumberPreviewBox ctx={ctx} values={values} />}
          submit={async (values) => {
            const result = await allocateNumber(ctx.projectId, numberRequest(values));
            addToast({ type: 'success', title: ui(t, 'design.ui.numbering.reserved', { number: result.number }) }, { duration: 15000 });
          }}
          onClose={() => setReserving(false)}
          onDone={ctx.onChanged}
          testId="reserve-form"
        />
      )}
    </section>
  );
}
