// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReportTemplateFields — template picker, dynamic template-field editor,
 * and attachments for a field report.
 *
 * Attachments deliberately REUSE the existing documents module:
 *  - `uploadDocument` / `uploadPhoto` from @/features/documents/api do the
 *    actual file storage (no new uploader is built here).
 *  - the returned document id is then linked through the field-reports
 *    `link-documents` endpoint, which already backs the report's
 *    `document_ids` JSON column.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Paperclip,
  Image as ImageIcon,
  FileText,
  Loader2,
  Trash2,
  Upload,
  FolderInput,
} from 'lucide-react';
import { WideModalSection, WideModalField, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { uploadDocument, uploadPhoto, deleteDocument } from '@/features/documents/api';
import AttachExistingFileModal from './AttachExistingFileModal';
import {
  fetchFieldReportTemplates,
  fetchReportDocuments,
  linkReportDocuments,
  type FieldReportTemplate,
  type TemplateFieldDefinition,
} from './api';

export type TemplateFieldValues = Record<string, string | number | boolean>;

const inputCls =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary';
const textareaCls = `${inputCls} resize-y`;

/* ── Template picker ───────────────────────────────────────────────────── */

export function TemplatePicker({
  projectId,
  value,
  onChange,
  onResolve,
  disabled,
}: {
  projectId: string;
  value: string;
  onChange: (templateId: string, template: FieldReportTemplate | null) => void;
  /** Fires once the list loads so an existing report's bound template
   *  can be hydrated without the user re-selecting it. */
  onResolve?: (template: FieldReportTemplate | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useQuery({
    queryKey: ['fieldreports', 'templates', projectId],
    queryFn: () => fetchFieldReportTemplates(projectId),
    enabled: !!projectId,
  });

  const resolvedRef = useRef(false);
  useEffect(() => {
    if (resolvedRef.current || !value || templates.length === 0) return;
    const tpl = templates.find((x) => x.id === value) ?? null;
    if (tpl) {
      resolvedRef.current = true;
      onResolve?.(tpl);
    }
  }, [templates, value, onResolve]);

  return (
    <WideModalField
      label={t('fieldreports.template', { defaultValue: 'Report template' })}
      span={2}
    >
      <select
        value={value}
        disabled={disabled || isLoading}
        onChange={(e) => {
          const id = e.target.value;
          const tpl = templates.find((x) => x.id === id) ?? null;
          onChange(id, tpl);
        }}
        className={inputCls}
        aria-label={t('fieldreports.template', { defaultValue: 'Report template' })}
      >
        <option value="">
          {t('fieldreports.no_template', { defaultValue: 'No template - blank report' })}
        </option>
        {templates.map((tpl) => (
          <option key={tpl.id} value={tpl.id}>
            {tpl.name}
            {tpl.is_builtin
              ? ` · ${t('fieldreports.builtin', { defaultValue: 'built-in' })}`
              : ''}
          </option>
        ))}
      </select>
    </WideModalField>
  );
}

/* ── Dynamic template field editor ─────────────────────────────────────── */

export function TemplateFieldEditor({
  template,
  values,
  onChange,
}: {
  template: FieldReportTemplate;
  values: TemplateFieldValues;
  onChange: (key: string, value: string | number | boolean) => void;
}) {
  const { t } = useTranslation();

  if (!template.fields.length) return null;

  return (
    <WideModalSection
      title={t('fieldreports.template_fields', {
        defaultValue: 'Template: {{name}}',
        name: template.name,
      })}
      columns={2}
    >
      {template.fields.map((f: TemplateFieldDefinition) => {
        const v = values[f.key];
        const isWide = f.type === 'textarea';
        return (
          <WideModalField
            key={f.key}
            label={f.label}
            required={f.required}
            span={isWide ? 2 : 1}
            hint={f.help_text || undefined}
          >
            {f.type === 'textarea' ? (
              <textarea
                rows={3}
                value={String(v ?? '')}
                placeholder={f.placeholder}
                onChange={(e) => onChange(f.key, e.target.value)}
                className={textareaCls}
              />
            ) : f.type === 'select' ? (
              <select
                value={String(v ?? '')}
                onChange={(e) => onChange(f.key, e.target.value)}
                className={inputCls}
                aria-label={f.label}
              >
                <option value="">
                  {t('common.select', { defaultValue: 'Select…' })}
                </option>
                {f.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : f.type === 'checkbox' ? (
              <label className="flex items-center gap-2 text-sm text-content-secondary">
                <input
                  type="checkbox"
                  checked={Boolean(v)}
                  onChange={(e) => onChange(f.key, e.target.checked)}
                  className="h-4 w-4 rounded border-border-light"
                />
                {f.placeholder ||
                  t('fieldreports.yes', { defaultValue: 'Yes' })}
              </label>
            ) : (
              <input
                type={
                  f.type === 'number'
                    ? 'number'
                    : f.type === 'date'
                      ? 'date'
                      : 'text'
                }
                value={String(v ?? '')}
                placeholder={f.placeholder}
                onChange={(e) =>
                  onChange(
                    f.key,
                    f.type === 'number'
                      ? e.target.value === ''
                        ? ''
                        : Number(e.target.value)
                      : e.target.value,
                  )
                }
                className={inputCls}
              />
            )}
          </WideModalField>
        );
      })}
    </WideModalSection>
  );
}

/* ── Attachments (photos + documents) ──────────────────────────────────── */

export function ReportAttachments({
  reportId,
  projectId,
}: {
  reportId: string;
  projectId: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const docInputRef = useRef<HTMLInputElement>(null);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [showExistingPicker, setShowExistingPicker] = useState(false);

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['fieldreports', 'documents', reportId],
    queryFn: () => fetchReportDocuments(reportId),
    enabled: !!reportId,
  });

  const handleFiles = useCallback(
    async (files: FileList | null, asPhoto: boolean) => {
      if (!files || files.length === 0) return;
      setBusy(true);
      try {
        const linkIds: string[] = [];
        for (const file of Array.from(files)) {
          if (asPhoto) {
            const photo = await uploadPhoto(projectId, file, {
              category: 'site',
              caption: file.name,
            });
            // PhotoItem carries the underlying document_id — link that so
            // it flows through the existing report document_ids column.
            if (photo.document_id) linkIds.push(photo.document_id);
          } else {
            const doc = await uploadDocument(projectId, file, 'other');
            linkIds.push(doc.id);
          }
        }
        if (linkIds.length > 0) {
          await linkReportDocuments(reportId, linkIds);
        }
        await qc.invalidateQueries({
          queryKey: ['fieldreports', 'documents', reportId],
        });
        addToast({
          type: 'success',
          title: '',
          message: t('fieldreports.attachment_added', {
            defaultValue: 'Attachment added',
          }),
        });
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message:
            err instanceof Error
              ? err.message
              : t('fieldreports.attach_failed', {
                  defaultValue: 'Attachment failed',
                }),
        });
      } finally {
        setBusy(false);
      }
    },
    [projectId, reportId, qc, addToast, t],
  );

  const handleDelete = useCallback(
    async (docId: string) => {
      setBusy(true);
      try {
        await deleteDocument(docId);
        await qc.invalidateQueries({
          queryKey: ['fieldreports', 'documents', reportId],
        });
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message:
            err instanceof Error
              ? err.message
              : t('fieldreports.delete_failed', {
                  defaultValue: 'Delete failed',
                }),
        });
      } finally {
        setBusy(false);
      }
    },
    [qc, reportId, addToast, t],
  );

  return (
    <WideModalSection
      title={t('fieldreports.attachments', { defaultValue: 'Attachments' })}
      columns={1}
    >
      <WideModalField
        label={t('fieldreports.attachments', { defaultValue: 'Attachments' })}
        className="sm:[&>label]:hidden"
      >
        <div className="w-full space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={photoInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                void handleFiles(e.target.files, true);
                e.target.value = '';
              }}
            />
            <input
              ref={docInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                void handleFiles(e.target.files, false);
                e.target.value = '';
              }}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => photoInputRef.current?.click()}
              className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
            >
              {busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ImageIcon size={14} />
              )}
              {t('fieldreports.attach_photo', { defaultValue: 'Attach photo' })}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => docInputRef.current?.click()}
              className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
            >
              {busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Upload size={14} />
              )}
              {t('fieldreports.attach_document', {
                defaultValue: 'Attach document',
              })}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowExistingPicker(true)}
              className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
            >
              <FolderInput size={14} />
              {t('fieldreports.attach_existing', {
                defaultValue: 'Attach existing file',
              })}
            </button>
          </div>
          <p className="text-[11px] text-content-tertiary">
            {t('fieldreports.attach_existing_hint', {
              defaultValue:
                'Attach a file already in project files instead of uploading it again.',
            })}
          </p>

          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          ) : docs.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <Paperclip size={12} />
              {t('fieldreports.no_attachments', {
                defaultValue: 'No photos or documents attached yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-1">
              {docs.map((d) => (
                <li
                  key={d.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border-light px-3 py-1.5"
                >
                  <a
                    href={`/api/v1/documents/${d.id}/download`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex min-w-0 flex-1 items-center gap-2 text-sm text-content-primary hover:text-oe-blue"
                  >
                    {d.mime_type.startsWith('image/') ? (
                      <ImageIcon size={14} className="shrink-0" />
                    ) : (
                      <FileText size={14} className="shrink-0" />
                    )}
                    <span className="truncate">{d.name}</span>
                    <Badge variant="neutral">
                      {t(`documents.cat_${d.category}`, {
                        defaultValue: d.category.charAt(0).toUpperCase() + d.category.slice(1),
                      })}
                    </Badge>
                  </a>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleDelete(d.id)}
                    className="rounded p-1 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
                    title={t('common.delete', { defaultValue: 'Delete' })}
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </WideModalField>
      {showExistingPicker && (
        <AttachExistingFileModal
          reportId={reportId}
          projectId={projectId}
          attachedIds={docs.map((d) => d.id)}
          onClose={() => setShowExistingPicker(false)}
        />
      )}
    </WideModalSection>
  );
}
