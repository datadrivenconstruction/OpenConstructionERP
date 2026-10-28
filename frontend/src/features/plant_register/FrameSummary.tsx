// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The frame summary: what the equipment frame document of the project says
// in numbers, whether the register is ready for the gate to execution and, if
// not, exactly what is still open. The exports and the overdue reminders live
// here because this is the view a project lead takes to a gate meeting.

import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { BellRing, CheckCircle2, Download, XCircle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtList, fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  downloadExport,
  escalate,
  type ExportFormat,
  type ExportKind,
  type Finding,
  type FrameSummary as FrameSummaryData,
  type PlantCatalogue,
  type Readiness,
} from './api';
import { FINDING_SEVERITY, ITEM_CLASS, catalogueName, vocab, type KeyText, type LabelContext } from './labels';
import { Refusal, Section, ToneBadge, WriteButton } from './PlantBits';

export const EXPORT_NAME: Record<Exclude<ExportKind, 'paper'>, KeyText> = {
  register: ['plant.export.register', 'Long-lead register'],
  limits: ['plant.export.limits', 'Delivery limit matrix'],
  spares: ['plant.export.spares', 'Spares list'],
  frame: ['plant.export.frame', 'Frame summary'],
};

const EXPORTS = Object.keys(EXPORT_NAME) as Array<Exclude<ExportKind, 'paper'>>;

const SEVERITY_TONE = { error: 'error', warning: 'warning', info: 'neutral' } as const;

export interface FrameSummaryProps {
  projectId: string;
  summary: FrameSummaryData;
  readiness: Readiness | null;
  findings: Finding[];
  catalogue: PlantCatalogue;
  labels: LabelContext;
}

function Tile({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="frame-tile">
      <dt className="text-xs text-content-secondary">{label}</dt>
      <dd className={alert && value > 0 ? 'text-2xl font-semibold text-semantic-error' : 'text-2xl font-semibold text-content-primary'}>
        {fmtNumber(value, 0)}
      </dd>
    </div>
  );
}

export function FrameSummary({ projectId, summary, readiness, findings, catalogue, labels }: FrameSummaryProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const failing = findings.filter((f) => !f.passed);

  const download = useMutation({
    mutationFn: (job: { kind: ExportKind; format: ExportFormat }) => downloadExport(projectId, job.kind, job.format),
  });
  const remind = useMutation({
    mutationFn: () => escalate(projectId),
    onSuccess: (result) =>
      addToast({
        type: 'success',
        title:
          result.overdue.length + result.due_soon.length + result.expired_slots.length === 0
            ? t('plant.frame.remind_none', { defaultValue: 'No order is overdue or due soon, so no reminder was sent.' })
            : t('plant.frame.remind_done', {
                defaultValue: 'Reminders sent. Overdue orders: {{orders}}. Orders due soon: {{soon}}. Expired slots: {{slots}}.',
                orders: result.overdue.length,
                soon: result.due_soon.length,
                slots: result.expired_slots.length,
              }),
      }),
  });

  // A project without a phase model has no gate and no frame document, so
  // neither is named and the document is not listed as missing.
  const gates = readiness?.gates_in_use !== false;
  const open: Array<[string, string]> = [];
  if (readiness) {
    if (readiness.error_findings.length > 0) {
      open.push([
        'errors',
        t('plant.frame.open_errors', {
          defaultValue: 'Findings that must be fixed: {{number}}',
          number: readiness.error_findings.length,
        }),
      ]);
    }
    if (readiness.critical_open.length > 0) {
      open.push([
        'critical',
        t('plant.frame.open_critical', {
          defaultValue: 'Critical items without a confirmed route and an approved decision paper: {{items}}',
          items: fmtList(readiness.critical_open),
        }),
      ]);
    }
    if (readiness.long_lead_open.length > 0) {
      open.push([
        'long_lead',
        t('plant.frame.open_long_lead', {
          defaultValue: 'Long-lead items without a fresh lead time or past their order date: {{items}}',
          items: fmtList(readiness.long_lead_open),
        }),
      ]);
    }
    if (gates && !readiness.frame_document_attached) {
      open.push([
        'frame',
        t('plant.frame.open_frame', { defaultValue: 'The equipment frame document is not attached in the document area yet.' }),
      ]);
    }
  }

  return (
    <div className="space-y-4" data-testid="plant-frame">
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label={t('plant.frame.items', { defaultValue: 'Items' })} value={summary.item_count} />
        <Tile label={t('plant.frame.critical', { defaultValue: 'Critical' })} value={summary.critical_count} />
        <Tile label={t('plant.frame.long_lead', { defaultValue: 'Long-lead' })} value={summary.long_lead_count} />
        <Tile label={t('plant.frame.overdue', { defaultValue: 'Order overdue' })} value={summary.overdue_count} alert />
      </dl>

      {readiness && (
        <Section
          title={
            gates
              ? t('plant.frame.readiness', { defaultValue: 'Ready for the gate to execution' })
              : t('plant.frame.readiness_no_gates', { defaultValue: 'Ready to build' })
          }
          hint={
            gates
              ? t('plant.frame.readiness_hint', {
                  defaultValue: 'What the project gate checks on equipment before construction starts.',
                })
              : t('plant.frame.no_gates', {
                  defaultValue: 'This project does not use gates. The list shows what the plant register itself still needs.',
                })
          }
          testId="frame-readiness"
        >
          {readiness.ready ? (
            <p className="flex items-center gap-2 text-sm text-content-primary" data-testid="readiness-ready">
              <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
              {gates
                ? t('plant.frame.ready', { defaultValue: 'Everything the gate asks of the plant register is in place.' })
                : t('plant.frame.ready_no_gates', { defaultValue: 'Nothing is open in the plant register.' })}
            </p>
          ) : (
            <ul className="space-y-1.5" data-testid="readiness-open">
              {open.map(([key, text]) => (
                <li key={key} className="flex items-start gap-2 text-sm text-content-primary" data-open={key}>
                  <XCircle size={16} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
                  {text}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      <Section
        title={t('plant.frame.findings', { defaultValue: 'Checks' })}
        hint={t('plant.frame.findings_hint', { defaultValue: 'The rules the register is checked against, and what they found.' })}
        testId="frame-findings"
      >
        {failing.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="findings-clean">
            {t('plant.frame.findings_clean', { defaultValue: 'No finding. Every check passes.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {failing.map((f, i) => {
              const severity = f.severity in SEVERITY_TONE ? (f.severity as keyof typeof SEVERITY_TONE) : 'info';
              return (
                <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2 text-sm" data-testid="finding-row">
                  <ToneBadge tone={SEVERITY_TONE[severity]}>{vocab(t, FINDING_SEVERITY, severity)}</ToneBadge>
                  <span className="min-w-0 flex-1 text-content-primary">
                    {f.message}
                    {f.suggestion && <span className="block text-xs text-content-secondary">{f.suggestion}</span>}
                  </span>
                  {f.element_ref && <span className="font-mono text-xs text-content-tertiary">{f.element_ref}</span>}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={t('plant.frame.by_class', { defaultValue: 'By kind of equipment' })}>
          <Counts
            rows={Object.entries(summary.by_item_class).map(([code, n]): [string, number] => [
              vocab(t, ITEM_CLASS, code as keyof typeof ITEM_CLASS),
              n,
            ])}
          />
        </Section>
        <Section title={t('plant.frame.by_route', { defaultValue: 'By procurement route' })}>
          <Counts
            rows={Object.entries(summary.by_route).map(([code, n]): [string, number] => [
              code === 'unset'
                ? t('plant.frame.route_unset', { defaultValue: 'No route yet' })
                : catalogueName(labels, catalogue, 'procurement_routes', code),
              n,
            ])}
          />
        </Section>
      </div>

      <Section
        title={t('plant.frame.documents', { defaultValue: 'Take it with you' })}
        hint={t('plant.frame.documents_hint', { defaultValue: 'The register as a document, for a meeting or the project file.' })}
        testId="frame-exports"
        action={
          <WriteButton
            size="sm"
            variant="secondary"
            icon={<BellRing size={14} />}
            loading={remind.isPending}
            data-testid="frame-remind"
            title={t('plant.frame.remind_hint', {
              defaultValue: 'Notifies the responsible people about orders past or close to their date and reservations past their deadline.',
            })}
            onClick={() => remind.mutate()}
          >
            {t('plant.frame.remind', { defaultValue: 'Send order reminders' })}
          </WriteButton>
        }
      >
        <Refusal error={remind.error ?? download.error} className="mb-3" />
        <ul className="divide-y divide-border-light">
          {EXPORTS.map((kind) => (
            <li key={kind} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm" data-testid="export-row">
              <span className="text-content-primary">{vocab(t, EXPORT_NAME, kind)}</span>
              <span className="flex gap-1">
                {(['pdf', 'xlsx'] as const).map((format) => (
                  <Button
                    key={format}
                    size="sm"
                    variant="ghost"
                    icon={<Download size={14} />}
                    loading={download.isPending && download.variables?.kind === kind && download.variables.format === format}
                    onClick={() => download.mutate({ kind, format })}
                  >
                    {format === 'pdf'
                      ? t('plant.common.pdf', { defaultValue: 'PDF' })
                      : t('plant.common.xlsx', { defaultValue: 'Excel' })}
                  </Button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function Counts({ rows }: { rows: Array<[string, number]> }) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return <p className="text-sm text-content-tertiary">{t('plant.frame.no_items', { defaultValue: 'No items yet.' })}</p>;
  }
  return (
    <ul className="space-y-1">
      {rows.map(([label, n]) => (
        <li key={label} className="flex items-center justify-between gap-3 text-sm">
          <span className="text-content-secondary">{label}</span>
          <span className="font-medium tabular-nums text-content-primary">{fmtNumber(n, 0)}</span>
        </li>
      ))}
    </ul>
  );
}
