// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The framework a project works with, and the two documents the module
// produces from it. The framework brings the stakeholder categories, the
// analysis methods, the roles and the kinds of decision; choosing it is the
// first step on an empty project. Statutory references a framework carries
// are references only: the module never claims the project complies.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, FileCheck2 } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import {
  downloadExport,
  fileFrameDocument,
  putSettings,
  type ExportDocument,
  type ExportFormat,
  type FrameworkSummary,
  type SettingsInput,
  type StakeholderSettings,
} from './api';
import { FIELD_CLASS, GatedButton, RefusalBox, useWrite } from './StakeholderBits';
import { useFrameworks } from './hooks';
import { FILE_BLOCK, itemName, vocab, type LabelContext } from './labels';

/** The name of a framework in the catalogue list. */
export function frameworkName(labels: LabelContext, fw: Pick<FrameworkSummary, 'id' | 'name'>): string {
  return itemName(labels, { code: fw.id, name_key: fw.name?.key ?? '', labels: fw.name?.text ?? null });
}

export interface FrameworkSettingsProps {
  projectId: string;
  /** Null on a project that has not chosen a framework yet. */
  settings: StakeholderSettings | null;
  /** Before the first choice: the flag the server sent with the empty state. */
  canPin?: boolean;
  labels: LabelContext;
  onSaved: () => void;
}

export function FrameworkSettings({ projectId, settings, canPin = true, labels, onSaved }: FrameworkSettingsProps) {
  const { t } = useTranslation();
  const frameworksQ = useFrameworks();
  const [picked, setPicked] = useState<string | null>(settings ? `${settings.framework_source}:${settings.framework_id}` : null);
  const [method, setMethod] = useState(settings?.analysis_method ?? '');
  const [days, setDays] = useState(String(settings?.review_interval_days ?? 90));

  const write = useWrite((body: SettingsInput) => putSettings(projectId, body), onSaved);

  if (frameworksQ.isLoading) return <SkeletonTable rows={3} columns={2} />;
  if (frameworksQ.isError) {
    return (
      <ErrorState
        title={t('stakeholders.ui.framework.load_failed', { defaultValue: 'The frameworks could not be loaded' })}
        hint={getErrorMessage(frameworksQ.error)}
        onRetry={() => frameworksQ.refetch()}
      />
    );
  }

  const frameworks = (frameworksQ.data ?? []).filter((f) => f.state !== 'retired' && (f.source === 'shipped' || f.latest_version));
  const keyOf = (f: FrameworkSummary) => `${f.source}:${f.id}`;
  // Before anything is pinned the server picks by the project's country; the first of the list is only the visible default.
  const chosen = frameworks.find((f) => keyOf(f) === picked) ?? null;
  const unchangedFramework = !!settings && picked === `${settings.framework_source}:${settings.framework_id}`;

  const submit = () => {
    const body: SettingsInput = {};
    if (chosen && !unchangedFramework) {
      body.framework_source = chosen.source;
      body.framework_id = chosen.id;
    }
    if (settings) {
      if (unchangedFramework && method) body.analysis_method = method;
      if (Number(days) >= 1) body.review_interval_days = Number(days);
    }
    write.run(body);
  };

  // Follows the server flag: the one on the settings, or before the first
  // choice the one sent with the empty state.
  const allowed = settings ? settings.can.manage_organisation : canPin;

  return (
    <section className="space-y-4 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="framework-settings">
      <div>
        <h2 className="text-sm font-semibold text-content-primary">
          {t('stakeholders.ui.framework.title', { defaultValue: 'Stakeholder framework' })}
        </h2>
        <p className="text-xs text-content-secondary">
          {t('stakeholders.ui.framework.hint', {
            defaultValue: 'It brings the stakeholder categories, the ways to analyse them, the project roles and the kinds of decision. Leave the choice open and the framework for the project country is used.',
          })}
        </p>
      </div>
      <RefusalBox refusal={write.refusal} />

      {frameworks.length === 0 ? (
        <p className="text-sm text-content-secondary">{t('stakeholders.ui.framework.none', { defaultValue: 'No framework is available.' })}</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t('stakeholders.ui.framework.title', { defaultValue: 'Stakeholder framework' })}>
          {frameworks.map((f) => (
            <li key={keyOf(f)}>
              <label
                className={clsx(
                  'flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm',
                  picked === keyOf(f) ? 'border-oe-blue' : 'border-border-light',
                )}
              >
                <input
                  type="radio"
                  name="stakeholder-framework"
                  className="mt-1"
                  checked={picked === keyOf(f)}
                  disabled={!allowed}
                  onChange={() => setPicked(keyOf(f))}
                  data-testid="framework-option"
                />
                <span>
                  <span className="block font-medium text-content-primary">{frameworkName(labels, f)}</span>
                  <span className="block text-xs text-content-tertiary">
                    {f.source === 'tenant'
                      ? t('stakeholders.ui.framework.own', { defaultValue: 'Your organisation' })
                      : t('stakeholders.ui.framework.shipped', { defaultValue: 'Built in' })}
                  </span>
                  {f.review_status.endsWith('unconfirmed') && (
                    <span className="block text-xs text-content-tertiary">
                      {t('stakeholders.ui.framework.unconfirmed', { defaultValue: 'References not yet confirmed by an expert' })}
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {settings && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.framework.method', { defaultValue: 'Analysis method the register shows' })}
            <select
              className={FIELD_CLASS}
              value={method}
              disabled={!allowed || !unchangedFramework}
              onChange={(e) => setMethod(e.target.value)}
              data-testid="settings-method"
            >
              {settings.framework.analysis_methods.map((m) => (
                <option key={m.code} value={m.code}>
                  {itemName(labels, m)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            {t('stakeholders.ui.framework.interval', { defaultValue: 'Assess external stakeholders again after (days)' })}
            <input
              type="number"
              min={1}
              max={3650}
              className={FIELD_CLASS}
              value={days}
              disabled={!allowed}
              onChange={(e) => setDays(e.target.value)}
            />
          </label>
        </div>
      )}

      <GatedButton allowed={allowed} capability="organisation" loading={write.busy} onClick={submit} data-testid="framework-save">
        {settings
          ? t('stakeholders.ui.framework.save', { defaultValue: 'Save settings' })
          : chosen
            ? t('stakeholders.ui.framework.start_with', { defaultValue: 'Start with this framework' })
            : t('stakeholders.ui.framework.start_default', { defaultValue: 'Start with the framework for the project country' })}
      </GatedButton>
    </section>
  );
}

const DOCUMENT_TITLE: Record<ExportDocument, readonly [string, string]> = {
  register: ['stakeholders.ui.export.register', 'Stakeholder and communication plan'],
  organisation: ['stakeholders.ui.export.organisation', 'Project organisation and mandates'],
};

export const EXPORT_KEY_MAPS = { DOCUMENT_TITLE };

/** Download a document as PDF or XLSX, or file it in the CDE as the revision the next gate reads. */
export function ExportBar({ projectId, settings, document }: { projectId: string; settings: StakeholderSettings; document: ExportDocument }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [reason, setReason] = useState('');
  const [impact, setImpact] = useState('');
  const file = useWrite(
    () =>
      fileFrameDocument(projectId, { document, format: 'pdf', change_reason: reason.trim(), change_impact: impact.trim() }),
    () => {
      setReason('');
      setImpact('');
      addToast({
        type: 'success',
        title: t('stakeholders.ui.export.filed', { defaultValue: 'Filed as a new revision of the frame document.' }),
      });
    },
  );
  // A binding frame document changes only through a change request, so the
  // server asks for a reason. The fields appear once it has said so.
  const asksReason = file.refusal?.code === 'change_reason_required';
  // Whether filing exists here and whether it works now is the server's answer. A project run
  // without gates has no frame documents, so only the downloads are shown there.
  const filing = settings.can_file[document];

  const download = async (format: ExportFormat) => {
    setBusy(format);
    try {
      await downloadExport(projectId, document, format);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid={`export-${document}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto text-sm text-content-secondary">
          {t(DOCUMENT_TITLE[document][0], { defaultValue: DOCUMENT_TITLE[document][1] })}
        </span>
        {(['pdf', 'xlsx'] as const).map((format) => (
          <Button
            key={format}
            size="sm"
            variant="ghost"
            icon={<Download size={13} />}
            loading={busy === format}
            onClick={() => download(format)}
            data-testid={`export-${document}-${format}`}
          >
            {format.toUpperCase()}
          </Button>
        ))}
        {filing.applies && (
          <Button
            size="sm"
            variant="secondary"
            icon={<FileCheck2 size={13} />}
            loading={file.busy}
            disabled={!filing.allowed || (asksReason && !reason.trim())}
            onClick={() => file.run(undefined)}
            data-testid={`export-${document}-file`}
          >
            {t('stakeholders.ui.export.file', { defaultValue: 'File for the gate' })}
          </Button>
        )}
      </div>
      {filing.applies && !filing.allowed && (
        <p className="text-xs text-content-tertiary" data-testid={`export-${document}-blocked`} data-reason={filing.reason ?? undefined}>
          {vocab(t, FILE_BLOCK, filing.reason ?? 'no_permission')}
        </p>
      )}
      {asksReason ? (
        <div className="space-y-2" data-testid={`export-${document}-reason`}>
          <p className="text-sm text-content-secondary">
            {t('stakeholders.ui.export.binding_hint', {
              defaultValue: 'This document is already binding. A new revision goes through a change request, so say why it changes.',
            })}
          </p>
          <label className="block text-xs text-content-secondary">
            {t('stakeholders.ui.export.change_reason', { defaultValue: 'Why the document changes' })}
            <textarea rows={2} className={FIELD_CLASS} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="block text-xs text-content-secondary">
            {t('stakeholders.ui.export.change_impact', { defaultValue: 'What the change affects (optional)' })}
            <textarea rows={2} className={FIELD_CLASS} value={impact} onChange={(e) => setImpact(e.target.value)} />
          </label>
        </div>
      ) : (
        <RefusalBox refusal={file.refusal} />
      )}
    </section>
  );
}
