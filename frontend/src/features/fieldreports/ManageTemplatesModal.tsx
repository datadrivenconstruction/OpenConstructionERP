// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ManageTemplatesModal — list built-in + custom report templates and
 * create / delete project-scoped custom ones.
 *
 * Built-in templates are read-only (marked, no delete). Custom templates
 * are project-scoped and go through the same auth / IDOR guard as every
 * other field-reports endpoint.
 */

import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X, Loader2, Lock } from 'lucide-react';
import {
  WideModal,
  WideModalSection,
  WideModalField,
  Button,
  Badge,
  EmptyState,
  ConfirmDialog,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useConfirm } from '@/shared/hooks/useConfirm';
import {
  fetchFieldReportTemplates,
  createFieldReportTemplate,
  deleteFieldReportTemplate,
  REPORT_TYPES,
  TEMPLATE_FIELD_TYPES,
  type FieldReportTemplate,
  type TemplateFieldType,
  type ReportType,
} from './api';

// English wording for the computed `fieldreports.fieldtype_*` keys, so the
// `defaultValue` reads like every other one in this file rather than handing
// back the enum token. It does not fire today: en.ts carries all six keys and
// the other locales reach them through the English fallback. It fires if a key
// is ever dropped or a seventh field type is added ahead of its translation,
// which is the moment `textarea` would otherwise appear on screen.
const FIELDREPORTS_FIELDTYPE_LABELS: Record<string, string> = {
  text: 'Text',
  textarea: 'Long text',
  number: 'Number',
  select: 'Dropdown',
  date: 'Date',
  checkbox: 'Checkbox',
};


const inputCls =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary';

interface DraftField {
  key: string;
  label: string;
  type: TemplateFieldType;
  required: boolean;
  options: string;
}

function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 60);
}

export function ManageTemplatesModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const { data: templates = [], isLoading } = useQuery({
    queryKey: ['fieldreports', 'templates', projectId],
    queryFn: () => fetchFieldReportTemplates(projectId),
    enabled: !!projectId,
  });

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [reportType, setReportType] = useState<ReportType>('daily');
  const [fields, setFields] = useState<DraftField[]>([
    { key: '', label: '', type: 'text', required: false, options: '' },
  ]);

  const resetForm = useCallback(() => {
    setName('');
    setDescription('');
    setReportType('daily');
    setFields([
      { key: '', label: '', type: 'text', required: false, options: '' },
    ]);
    setCreating(false);
  }, []);

  const createMut = useMutation({
    mutationFn: createFieldReportTemplate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fieldreports', 'templates'] });
      addToast({
        type: 'success',
        title: '',
        message: t('fieldreports.template_created', {
          defaultValue: 'Template created',
        }),
      });
      resetForm();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteFieldReportTemplate(id, projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fieldreports', 'templates'] });
      addToast({
        type: 'success',
        title: '',
        message: t('fieldreports.template_deleted', {
          defaultValue: 'Template deleted',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleAddField = useCallback(() => {
    setFields((prev) => [
      ...prev,
      { key: '', label: '', type: 'text', required: false, options: '' },
    ]);
  }, []);

  const handleRemoveField = useCallback((idx: number) => {
    setFields((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleFieldChange = useCallback(
    (idx: number, patch: Partial<DraftField>) => {
      setFields((prev) =>
        prev.map((f, i) => (i === idx ? { ...f, ...patch } : f)),
      );
    },
    [],
  );

  const handleSave = useCallback(() => {
    const cleaned = fields
      .filter((f) => f.label.trim() !== '')
      .map((f) => ({
        key: (f.key.trim() || slugify(f.label)) as string,
        label: f.label.trim(),
        type: f.type,
        required: f.required,
        options:
          f.type === 'select'
            ? f.options
                .split(',')
                .map((o) => o.trim())
                .filter(Boolean)
            : [],
        placeholder: '',
        help_text: '',
      }));
    if (!name.trim() || cleaned.length === 0) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('fieldreports.template_validation', {
          defaultValue: 'A name and at least one field are required.',
        }),
      });
      return;
    }
    createMut.mutate({
      project_id: projectId,
      name: name.trim(),
      description: description.trim() || null,
      report_type: reportType,
      fields: cleaned,
      is_active: true,
    });
  }, [
    fields,
    name,
    description,
    reportType,
    projectId,
    createMut,
    addToast,
    t,
  ]);

  const handleDelete = useCallback(
    async (tpl: FieldReportTemplate) => {
      const ok = await confirm({
        title: t('fieldreports.delete_template_title', {
          defaultValue: 'Delete template?',
        }),
        message: t('fieldreports.delete_template_msg', {
          defaultValue: 'Delete "{{name}}"? Existing reports keep their data.',
          name: tpl.name,
        }),
      });
      if (ok) deleteMut.mutate(tpl.id);
    },
    [confirm, deleteMut, t],
  );

  return (
    <WideModal
      open
      onClose={onClose}
      size="2xl"
      title={t('fieldreports.manage_templates', {
        defaultValue: 'Report Templates',
      })}
      subtitle={t('fieldreports.manage_templates_sub', {
        defaultValue:
          'Built-in templates are ready to use. Add custom ones for this project.',
      })}
      footer={
        <>
          <Button size="sm" variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {creating ? (
            <Button
              size="sm"
              onClick={handleSave}
              disabled={createMut.isPending}
            >
              {createMut.isPending && (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              )}
              {t('fieldreports.save_template', {
                defaultValue: 'Save template',
              })}
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => setCreating(true)}
              icon={<Plus size={14} />}
            >
              {t('fieldreports.new_template', {
                defaultValue: 'New template',
              })}
            </Button>
          )}
        </>
      }
    >
      {/* Existing templates list */}
      {!creating && (
        <WideModalSection columns={1}>
          <WideModalField
            label={t('fieldreports.templates', { defaultValue: 'Templates' })}
            className="sm:[&>label]:hidden"
          >
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-content-tertiary">
                <Loader2 size={14} className="animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : templates.length === 0 ? (
              <EmptyState
                title={t('fieldreports.no_templates', {
                  defaultValue: 'No templates',
                })}
                description={t('fieldreports.no_templates_desc', {
                  defaultValue: 'Create your first custom template.',
                })}
              />
            ) : (
              <ul className="w-full space-y-2">
                {templates.map((tpl) => (
                  <li
                    key={tpl.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border-light px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-content-primary">
                          {tpl.name}
                        </span>
                        {tpl.is_builtin ? (
                          <Badge variant="blue">
                            {t('fieldreports.builtin', {
                              defaultValue: 'built-in',
                            })}
                          </Badge>
                        ) : (
                          <Badge variant="neutral">
                            {t('fieldreports.custom', {
                              defaultValue: 'custom',
                            })}
                          </Badge>
                        )}
                      </div>
                      <p className="truncate text-xs text-content-tertiary">
                        {t(`fieldreports.type_${tpl.report_type}`, {
                          defaultValue: tpl.report_type.replace(/_/g, ' '),
                        })}{' '}
                        ·{' '}
                        {t('fieldreports.field_count', {
                          defaultValue: '{{count}} fields',
                          count: tpl.fields.length,
                        })}
                      </p>
                    </div>
                    {tpl.is_builtin ? (
                      <span
                        className="p-1.5 text-content-quaternary"
                        title={t('fieldreports.builtin_readonly', {
                          defaultValue: 'Built-in templates are read-only',
                        })}
                      >
                        <Lock size={14} />
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleDelete(tpl)}
                        disabled={deleteMut.isPending}
                        className="rounded p-1.5 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
                        title={t('common.delete', { defaultValue: 'Delete' })}
                        aria-label={t('common.delete', {
                          defaultValue: 'Delete',
                        })}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </WideModalField>
        </WideModalSection>
      )}

      {/* Create form */}
      {creating && (
        <>
          <WideModalSection columns={2}>
            <WideModalField
              label={t('fieldreports.template_name', {
                defaultValue: 'Template name',
              })}
              required
            >
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
                placeholder={t('fieldreports.template_name_ph', {
                  defaultValue: 'e.g. Weekly Quality Walk',
                })}
              />
            </WideModalField>
            <WideModalField
              label={t('fieldreports.report_type', {
                defaultValue: 'Report Type',
              })}
            >
              <select
                value={reportType}
                onChange={(e) => setReportType(e.target.value as ReportType)}
                className={inputCls}
                aria-label={t('fieldreports.report_type', {
                  defaultValue: 'Report Type',
                })}
              >
                {REPORT_TYPES.map((rt) => (
                  <option key={rt} value={rt}>
                    {t(`fieldreports.type_${rt}`, {
                      defaultValue: rt.replace(/_/g, ' '),
                    })}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('fieldreports.template_desc', {
                defaultValue: 'Description',
              })}
              span={2}
            >
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className={inputCls}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('fieldreports.template_fields_title', {
              defaultValue: 'Fields',
            })}
            columns={1}
          >
            <WideModalField
              label={t('fieldreports.template_fields_title', {
                defaultValue: 'Fields',
              })}
              className="sm:[&>label]:hidden"
            >
              <div className="w-full space-y-2">
                {fields.map((f, idx) => (
                  <div
                    key={`tplfield-${idx}`}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <input
                      type="text"
                      value={f.label}
                      onChange={(e) =>
                        handleFieldChange(idx, { label: e.target.value })
                      }
                      placeholder={t('fieldreports.field_label', {
                        defaultValue: 'Field label',
                      })}
                      className={`${inputCls} flex-1 min-w-[160px]`}
                    />
                    <select
                      value={f.type}
                      onChange={(e) =>
                        handleFieldChange(idx, {
                          type: e.target.value as TemplateFieldType,
                        })
                      }
                      aria-label={t('fieldreports.field_type', {
                        defaultValue: 'Field type',
                      })}
                      className={`${inputCls} w-32`}
                    >
                      {TEMPLATE_FIELD_TYPES.map((ft) => (
                        <option key={ft} value={ft}>
                          {t(`fieldreports.fieldtype_${ft}`, {
                            defaultValue: FIELDREPORTS_FIELDTYPE_LABELS[ft] ?? ft,
                          })}
                        </option>
                      ))}
                    </select>
                    {f.type === 'select' && (
                      <input
                        type="text"
                        value={f.options}
                        onChange={(e) =>
                          handleFieldChange(idx, { options: e.target.value })
                        }
                        placeholder={t('fieldreports.field_options', {
                          defaultValue: 'Options, comma-separated',
                        })}
                        className={`${inputCls} flex-1 min-w-[160px]`}
                      />
                    )}
                    <label className="flex items-center gap-1.5 text-xs text-content-secondary">
                      <input
                        type="checkbox"
                        checked={f.required}
                        onChange={(e) =>
                          handleFieldChange(idx, {
                            required: e.target.checked,
                          })
                        }
                        className="h-4 w-4 rounded border-border-light"
                      />
                      {t('fieldreports.required', {
                        defaultValue: 'Required',
                      })}
                    </label>
                    <button
                      type="button"
                      onClick={() => handleRemoveField(idx)}
                      className="rounded p-1 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error"
                      title={t('common.remove', { defaultValue: 'Remove' })}
                      aria-label={t('common.remove', {
                        defaultValue: 'Remove',
                      })}
                    >
                      <X size={16} />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={handleAddField}
                  className="flex items-center gap-1.5 text-sm text-oe-blue hover:text-oe-blue/80 transition-colors"
                >
                  <Plus size={14} />
                  {t('fieldreports.add_field', { defaultValue: 'Add field' })}
                </button>
              </div>
            </WideModalField>
          </WideModalSection>
        </>
      )}
      <ConfirmDialog {...confirmProps} />
    </WideModal>
  );
}
