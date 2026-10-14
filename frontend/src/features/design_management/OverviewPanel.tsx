// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The home view of design management: for each phase, what still stands
// between the design and the gate (schedule lines not accepted, reports not
// accepted, major review comments still open), the findings of the design
// checks, and the four registers as files.

import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, CircleAlert, Download, Gauge } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import { downloadRegister, fileFrameDocument, listReadiness, listValidation, type ExportRegister } from './api';
import { ListState, PanelHeader, ToneBadge, hasRows, type DesignContext, WriteButton } from './DesignBits';
import { refusalText, useDesignList } from './hooks';
import { labelOf, ui, uiCount, type TFn } from './labels';
import type { UiKey } from './text';

const REGISTERS: Array<{ register: ExportRegister; title: UiKey }> = [
  { register: 'register', title: 'design.ui.overview.register_drawings' },
  { register: 'matrix', title: 'design.ui.overview.register_matrix' },
  { register: 'reports', title: 'design.ui.overview.register_reports' },
  { register: 'permit', title: 'design.ui.overview.register_permit' },
];

export function OverviewPanel({ ctx, onOpenGovernance }: { ctx: DesignContext; onOpenGovernance: () => void }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const addToast = useToastStore((s) => s.addToast);
  const readiness = useDesignList(ctx.projectId, 'readiness', listReadiness);
  const validation = useDesignList(ctx.projectId, 'validation', listValidation);
  const onError = (err: unknown) => addToast({ type: 'error', title: refusalText(t, err) });

  const download = useMutation({
    mutationFn: (args: { register: ExportRegister; format: 'pdf' | 'xlsx' }) => downloadRegister(ctx.projectId, args.register, args.format),
    onError,
  });
  const file = useMutation({
    mutationFn: (register: ExportRegister) => fileFrameDocument(ctx.projectId, register),
    onSuccess: () => {
      addToast({ type: 'success', title: ui(t, 'design.ui.overview.filed') });
      ctx.onChanged();
    },
    onError,
  });
  const noGates = ctx.setup.gates_in_use === false;
  const failed = (validation.data ?? []).filter((f) => !f.passed);

  return (
    <div className="space-y-5" data-testid="design-overview-panel">
      <PanelHeader title={ui(t, 'design.ui.overview.title')} hint={ui(t, 'design.ui.overview.hint')} />
      <ListState
        query={readiness}
        failedKey="design.ui.overview.load_failed"
        emptyIcon={<Gauge size={28} />}
        emptyTitle={ui(t, 'design.ui.overview.empty_title')}
        emptyBody={ui(t, 'design.ui.overview.empty_body')}
        emptyAction={{ label: ui(t, 'design.ui.overview.open_governance'), onClick: onOpenGovernance }}
      />
      {hasRows(readiness) && (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="readiness-list">
          {(readiness.data ?? []).map((phase) => (
            <li key={phase.code ?? 'project'} className="rounded-lg border border-border-light p-3" data-testid="readiness-card" data-met={phase.met}>
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-medium text-content-primary">{phase.code ? labelOf(ctx.labels, phase.name, phase.code) : ui(t, 'design.ui.overview.whole_project')}</h3>
                <ToneBadge tone={phase.met ? 'success' : 'warning'}>
                  {phase.met ? ui(t, 'design.ui.overview.ready') : ui(t, 'design.ui.overview.not_ready')}
                </ToneBadge>
              </div>
              {phase.met ? (
                <p className="mt-1 text-sm text-content-secondary">{ui(t, 'design.ui.overview.nothing_open')}</p>
              ) : (
                <ul className="mt-1 space-y-1 text-sm text-content-secondary">
                  {phase.open_deliverables.length > 0 && (
                    <li>
                      {uiCount(t, 'design.ui.overview.open_lines', phase.open_deliverables.length)}
                      <span className="ml-1 font-mono text-xs">{fmtList(phase.open_deliverables)}</span>
                    </li>
                  )}
                  {phase.open_reports.length > 0 && (
                    <li>
                      {uiCount(t, 'design.ui.overview.open_reports', phase.open_reports.length)}
                      <span className="ml-1 font-mono text-xs">{fmtList(phase.open_reports)}</span>
                    </li>
                  )}
                  {phase.open_major_comments > 0 && <li>{uiCount(t, 'design.ui.overview.open_comments', phase.open_major_comments)}</li>}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      <section className="space-y-2" data-testid="design-checks">
        <PanelHeader title={ui(t, 'design.ui.overview.checks_title')} hint={ui(t, 'design.ui.overview.checks_hint')} />
        {validation.isLoading ? (
          <p className="text-sm text-content-tertiary">{ui(t, 'design.ui.loading')}</p>
        ) : validation.isError ? (
          <p role="alert" className="text-sm text-semantic-error">
            {refusalText(t, validation.error)}
          </p>
        ) : failed.length === 0 ? (
          <p className="flex items-center gap-1.5 text-sm text-semantic-success" data-testid="checks-passed">
            <CheckCircle2 size={14} aria-hidden />
            {ui(t, 'design.ui.overview.checks_passed')}
          </p>
        ) : (
          <ul className="space-y-2">
            {failed.map((finding, i) => (
              <li key={`${finding.rule_id}-${finding.element_ref ?? i}`} className="flex gap-2 rounded-md bg-surface-secondary p-2 text-sm" data-testid="check-finding">
                <CircleAlert size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
                <div>
                  <p className="text-content-primary">{finding.message}</p>
                  {finding.suggestion && <p className="text-xs text-content-secondary">{finding.suggestion}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2" data-testid="design-registers">
        <PanelHeader title={ui(t, 'design.ui.overview.registers_title')} hint={ui(t, 'design.ui.overview.registers_hint')} />
        <ul className="divide-y divide-border-light rounded-lg border border-border-light">
          {REGISTERS.map(({ register, title }) => (
            <li key={register} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
              <span className="text-content-primary">{ui(t, title)}</span>
              <span className="ml-auto flex flex-wrap gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={14} />}
                  disabled={download.isPending}
                  onClick={() => download.mutate({ register, format: 'pdf' })}
                  data-testid={`export-${register}-pdf`}
                >
                  {ui(t, 'design.ui.overview.as_pdf')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={14} />}
                  disabled={download.isPending}
                  onClick={() => download.mutate({ register, format: 'xlsx' })}
                >
                  {ui(t, 'design.ui.overview.as_sheet')}
                </Button>
                {!noGates && (
                  <WriteButton need="manage" size="sm" variant="ghost" disabled={file.isPending} onClick={() => file.mutate(register)} data-testid={`file-${register}`}>
                    {ui(t, 'design.ui.overview.file_in_cde')}
                  </WriteButton>
                )}
              </span>
            </li>
          ))}
        </ul>
        {noGates && (
          <p className="mt-2 text-xs text-content-secondary" data-testid="no-frame-document">
            {ui(t, 'design.ui.overview.no_frame_document')}
          </p>
        )}
      </section>
    </div>
  );
}
