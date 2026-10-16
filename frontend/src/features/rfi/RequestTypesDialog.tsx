// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's request type catalogue: presets to load, the types in use,
 * a form to add one, and the register check.
 *
 * Type names come from the catalogue (`name_i18n`), not from the locale
 * files; only the dialog's own chrome is translated here.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { CheckCircle2, AlertTriangle, Download, Plus, Trash2 } from 'lucide-react';

import { Badge, Button, WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { getLanguageByCode } from '@/app/i18n';
import { approvalRoutesKeys, listRoutes } from '@/features/approval-routes/api';
import {
  REQUIRED_FIELD_CHOICES,
  createRequestType,
  deleteRequestType,
  fetchRegisterValidation,
  fetchRequestTypePresets,
  loadRequestTypePreset,
  localizedText,
  requestTypeName,
  sampleNumber,
  updateRequestType,
  type RegisterValidationResult,
  type RequestType,
  type RequiredField,
} from './requestTypes';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** The form label each required field already has in the request form. */
const REQUIRED_FIELD_LABEL_KEYS: Record<RequiredField, [string, string]> = {
  assigned_to: ['rfi.field_assigned_to', 'Assigned To'],
  response_due_date: ['rfi.field_due_date', 'Response Due Date'],
  discipline: ['rfi.field_discipline', 'Discipline'],
  priority: ['rfi.field_priority', 'Priority'],
  linked_drawing_ids: ['rfi.attached_documents', 'Attached documents'],
  cost_impact_value: ['rfi.field_cost_impact_value', 'Cost exposure'],
  schedule_impact_days: ['rfi.field_schedule_impact_days', 'Schedule slip (days)'],
};

export function useRequiredFieldLabel(): (field: string) => string {
  const { t } = useTranslation();
  return (field: string) => {
    const entry = REQUIRED_FIELD_LABEL_KEYS[field as RequiredField];
    return entry ? t(entry[0], { defaultValue: entry[1] }) : field;
  };
}

/** Query key of a project's catalogue, shared by the page, the form and this dialog. */
export const requestTypesKey = (projectId: string) => ['rfi-types', projectId] as const;

interface NewTypeForm {
  code: string;
  prefix: string;
  nameEn: string;
  nameLocal: string;
  sla: string;
  required: string[];
  routeId: string;
}

const EMPTY_NEW_TYPE: NewTypeForm = {
  code: '',
  prefix: '',
  nameEn: '',
  nameLocal: '',
  sla: '',
  required: [],
  routeId: '',
};

export function RequestTypesDialog({
  projectId,
  types,
  onClose,
}: {
  projectId: string;
  types: RequestType[];
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const language = i18n.language || 'en';
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const canManage = useHasPermission('rfi.types.manage');
  const fieldLabel = useRequiredFieldLabel();
  const [form, setForm] = useState<NewTypeForm>(EMPTY_NEW_TYPE);

  const presetsQuery = useQuery({
    queryKey: ['rfi-type-presets'],
    queryFn: fetchRequestTypePresets,
    staleTime: 10 * 60_000,
  });
  const routesQuery = useQuery({
    queryKey: approvalRoutesKeys.routes(projectId, 'rfi'),
    queryFn: () => listRoutes({ projectId, targetKind: 'rfi', includeInactive: false }),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });
  const checkQuery = useQuery({
    queryKey: ['rfi-register-check', projectId],
    queryFn: () => fetchRegisterValidation(projectId),
    enabled: Boolean(projectId),
  });
  const routes = routesQuery.data ?? [];

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: requestTypesKey(projectId) });
    void qc.invalidateQueries({ queryKey: ['rfi-register-check', projectId] });
  };

  const loadMut = useMutation({
    mutationFn: (presetCode: string) => loadRequestTypePreset(presetCode, projectId),
    onSuccess: (result) => {
      refresh();
      addToast({
        type: 'success',
        title: t('rfi.types.loaded', {
          defaultValue: 'Preset loaded: {{created}} added, {{skipped}} already present',
          created: result.created.length,
          skipped: result.skipped.length,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.types.load_failed', { defaultValue: 'Could not load the preset' }),
        message: e.message,
      }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateRequestType>[1] }) =>
      updateRequestType(id, data),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('rfi.types.updated', { defaultValue: 'Request type updated' }) });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.types.update_failed', { defaultValue: 'Could not update the request type' }),
        message: e.message,
      }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRequestType(id),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('rfi.types.deleted', { defaultValue: 'Request type deleted' }) });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.types.update_failed', { defaultValue: 'Could not update the request type' }),
        message: e.message,
      }),
  });

  const createMut = useMutation({
    mutationFn: () => {
      const names: Record<string, string> = { en: form.nameEn.trim() };
      const local = form.nameLocal.trim();
      if (local && language !== 'en') names[language] = local;
      const sla = Number.parseInt(form.sla, 10);
      return createRequestType({
        project_id: projectId,
        code: form.code.trim().toUpperCase(),
        number_prefix: (form.prefix.trim() || form.code.trim()).toUpperCase(),
        name_i18n: names,
        default_response_days: Number.isFinite(sla) && sla > 0 ? sla : null,
        required_fields: form.required,
        default_route_id: form.routeId || null,
        sort_order: 1000,
      });
    },
    onSuccess: () => {
      refresh();
      setForm(EMPTY_NEW_TYPE);
      addToast({ type: 'success', title: t('rfi.types.created', { defaultValue: 'Request type added' }) });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.types.create_failed', { defaultValue: 'Could not add the request type' }),
        message: e.message,
      }),
  });

  const codeValid = /^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(form.code.trim());
  const prefixValid = !form.prefix.trim() || /^[A-Za-z][A-Za-z0-9]{0,9}$/.test(form.prefix.trim());
  const canCreate = canManage && codeValid && prefixValid && form.nameEn.trim().length > 0 && !createMut.isPending;
  const languageName = useMemo(() => getLanguageByCode(language).name, [language]);
  const failing = (checkQuery.data?.results ?? []).filter((r) => !r.passed);
  // The rule messages are English; the reader gets the finding rebuilt from
  // its structured details, and the English line stays in the tooltip.
  const describeFinding = (r: RegisterValidationResult): string => {
    const d = r.details as { rfi_number?: string; missing?: string[]; problem?: string; request_type?: string };
    if (r.rule_id === 'rfi.request_type_required_fields') {
      return t('rfi.types.check_missing', {
        defaultValue: '{{number}} is missing: {{fields}}',
        number: d.rfi_number ?? '',
        fields: (d.missing ?? []).map(fieldLabel).join(', '),
      });
    }
    if (d.problem === 'unknown_type') {
      return t('rfi.types.check_unknown_type', {
        defaultValue: 'Requests name type {{code}}, which is not in the catalogue',
        code: d.request_type ?? '',
      });
    }
    return t('rfi.types.check_bad_type', {
      defaultValue: 'Type {{code}} has an invalid setting',
      code: d.request_type ?? r.element_ref ?? '',
    });
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('rfi.types.title', { defaultValue: 'Request types' })}
      subtitle={t('rfi.types.subtitle', {
        defaultValue:
          'Each type has its own numbering, response time and required fields. Types are data: load a preset or add your own.',
      })}
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
      testId="rfi-request-types-dialog"
    >
      {/* ── Presets ── */}
      <WideModalSection title={t('rfi.types.section_presets', { defaultValue: 'Presets' })} columns={2}>
        {(presetsQuery.data ?? []).map((preset) => (
          <div
            key={preset.code}
            className="rounded-lg border border-border-light bg-surface-primary p-3 flex flex-col gap-2"
            data-testid={`rfi-preset-${preset.code}`}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-semibold text-content-primary">
                {localizedText(preset.name_i18n, language, preset.code)}
              </p>
              <Badge size="sm">
                {t('rfi.types.preset_types', { defaultValue: 'Types: {{n}}', n: preset.types.length })}
              </Badge>
            </div>
            <p className="text-xs text-content-secondary">
              {localizedText(preset.description_i18n, language, '')}
            </p>
            <p className="text-2xs text-content-tertiary">
              {preset.types.map((pt) => pt.code).join(' · ')}
            </p>
            {canManage && (
              <div>
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Download size={14} />}
                  loading={loadMut.isPending && loadMut.variables === preset.code}
                  disabled={loadMut.isPending}
                  onClick={() => loadMut.mutate(preset.code)}
                >
                  {t('rfi.types.load_preset', { defaultValue: 'Load into project' })}
                </Button>
              </div>
            )}
          </div>
        ))}
      </WideModalSection>

      {/* ── Catalogue ── */}
      <WideModalSection title={t('rfi.types.section_catalogue', { defaultValue: 'Types in this project' })}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="rfi-type-catalogue">
            <thead>
              <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pe-3 font-medium">{t('rfi.types.col_type', { defaultValue: 'Type' })}</th>
                <th className="py-2 pe-3 font-medium">{t('rfi.types.col_numbering', { defaultValue: 'Numbering' })}</th>
                <th className="py-2 pe-3 font-medium">
                  {t('rfi.types.col_sla', { defaultValue: 'Response (business days)' })}
                </th>
                <th className="py-2 pe-3 font-medium">
                  {t('rfi.types.col_required', { defaultValue: 'Required before issue' })}
                </th>
                <th className="py-2 pe-3 font-medium">
                  {t('rfi.types.col_route', { defaultValue: 'Default approval route' })}
                </th>
                <th className="py-2 pe-3 font-medium text-end">
                  {t('rfi.types.col_requests', { defaultValue: 'Requests' })}
                </th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {types.map((type) => (
                <tr
                  key={type.code}
                  className={clsx('border-t border-border-light align-top', !type.is_active && 'opacity-60')}
                >
                  <td className="py-2 pe-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-content-secondary">{type.code}</span>
                      <span className="text-content-primary">{requestTypeName(type, language)}</span>
                      {type.is_builtin && (
                        <Badge size="sm" variant="blue">
                          {t('rfi.types.builtin', { defaultValue: 'Built-in' })}
                        </Badge>
                      )}
                      {!type.is_active && (
                        <Badge size="sm" variant="warning">
                          {t('rfi.types.retired', { defaultValue: 'Retired' })}
                        </Badge>
                      )}
                    </div>
                    {type.is_builtin && (
                      <p className="mt-0.5 text-2xs text-content-tertiary">
                        {t('rfi.types.builtin_hint', {
                          defaultValue: 'Every project starts with RFI. Load a preset to manage it like any other type.',
                        })}
                      </p>
                    )}
                  </td>
                  <td className="py-2 pe-3 font-mono text-xs">{sampleNumber(type)}</td>
                  <td className="py-2 pe-3 tabular-nums">{type.response_days}</td>
                  <td className="py-2 pe-3 text-xs text-content-secondary">
                    {type.required_fields.length > 0
                      ? type.required_fields.map(fieldLabel).join(', ')
                      : t('rfi.types.none_required', { defaultValue: 'Nothing extra' })}
                  </td>
                  <td className="py-2 pe-3">
                    {type.id && canManage ? (
                      <select
                        value={type.default_route_id ?? ''}
                        aria-label={t('rfi.types.col_route', { defaultValue: 'Default approval route' })}
                        onChange={(e) =>
                          updateMut.mutate({ id: type.id!, data: { default_route_id: e.target.value || null } })
                        }
                        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs"
                      >
                        <option value="">{t('rfi.types.no_route', { defaultValue: 'No default route' })}</option>
                        {routes.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-xs text-content-tertiary">
                        {routes.find((r) => r.id === type.default_route_id)?.name ??
                          t('rfi.types.no_route', { defaultValue: 'No default route' })}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pe-3 text-end tabular-nums">{type.request_count}</td>
                  <td className="py-2">
                    {type.id && canManage && (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={updateMut.isPending}
                          onClick={() => updateMut.mutate({ id: type.id!, data: { is_active: !type.is_active } })}
                        >
                          {type.is_active
                            ? t('rfi.types.retire', { defaultValue: 'Retire' })
                            : t('rfi.types.reactivate', { defaultValue: 'Reactivate' })}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={14} />}
                          disabled={type.request_count > 0 || deleteMut.isPending}
                          title={
                            type.request_count > 0
                              ? t('rfi.types.delete_blocked', { defaultValue: 'Used by requests; retire it instead' })
                              : t('rfi.types.delete', { defaultValue: 'Delete type' })
                          }
                          aria-label={t('rfi.types.delete', { defaultValue: 'Delete type' })}
                          onClick={() => deleteMut.mutate(type.id!)}
                        />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </WideModalSection>

      {/* ── Add a type ── */}
      {canManage && (
        <WideModalSection title={t('rfi.types.section_add', { defaultValue: 'Add a type' })} columns={2}>
          <WideModalField
            label={t('rfi.types.field_code', { defaultValue: 'Code' })}
            htmlFor="rfi-type-code"
            hint={t('rfi.types.code_hint', { defaultValue: 'Capital letters and digits, e.g. TQ' })}
            required
          >
            <input
              id="rfi-type-code"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))}
              className={inputCls}
              maxLength={32}
            />
          </WideModalField>
          <WideModalField label={t('rfi.types.field_prefix', { defaultValue: 'Number prefix' })} htmlFor="rfi-type-prefix">
            <input
              id="rfi-type-prefix"
              value={form.prefix}
              placeholder={form.code}
              onChange={(e) => setForm((f) => ({ ...f, prefix: e.target.value.toUpperCase() }))}
              className={inputCls}
              maxLength={10}
            />
          </WideModalField>
          <WideModalField
            label={t('rfi.types.field_name_en', { defaultValue: 'Name (English)' })}
            htmlFor="rfi-type-name-en"
            required
          >
            <input
              id="rfi-type-name-en"
              value={form.nameEn}
              onChange={(e) => setForm((f) => ({ ...f, nameEn: e.target.value }))}
              className={inputCls}
              maxLength={200}
            />
          </WideModalField>
          {language !== 'en' && (
            <WideModalField
              label={t('rfi.types.field_name_local', { defaultValue: 'Name ({{language}})', language: languageName })}
              htmlFor="rfi-type-name-local"
            >
              <input
                id="rfi-type-name-local"
                value={form.nameLocal}
                onChange={(e) => setForm((f) => ({ ...f, nameLocal: e.target.value }))}
                className={inputCls}
                maxLength={200}
              />
            </WideModalField>
          )}
          <WideModalField
            label={t('rfi.types.field_sla', { defaultValue: 'Response time (business days)' })}
            htmlFor="rfi-type-sla"
          >
            <input
              id="rfi-type-sla"
              type="number"
              min={1}
              max={365}
              value={form.sla}
              onChange={(e) => setForm((f) => ({ ...f, sla: e.target.value }))}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('rfi.types.col_route', { defaultValue: 'Default approval route' })}
            htmlFor="rfi-type-route"
          >
            <select
              id="rfi-type-route"
              value={form.routeId}
              onChange={(e) => setForm((f) => ({ ...f, routeId: e.target.value }))}
              className={inputCls}
            >
              <option value="">{t('rfi.types.no_route', { defaultValue: 'No default route' })}</option>
              {routes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('rfi.types.col_required', { defaultValue: 'Required before issue' })} span={2}>
            <div className="flex flex-wrap gap-1.5" role="group">
              {REQUIRED_FIELD_CHOICES.map((field) => {
                const on = form.required.includes(field);
                return (
                  <button
                    key={field}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setForm((f) => ({
                        ...f,
                        required: on ? f.required.filter((x) => x !== field) : [...f.required, field],
                      }))
                    }
                    className={clsx(
                      'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                      on
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    {fieldLabel(field)}
                  </button>
                );
              })}
            </div>
          </WideModalField>
          <div className="col-span-2">
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              disabled={!canCreate}
              loading={createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {t('rfi.types.add', { defaultValue: 'Add type' })}
            </Button>
          </div>
        </WideModalSection>
      )}

      {/* ── Register check (validation rule set "rfi") ── */}
      <WideModalSection title={t('rfi.types.section_check', { defaultValue: 'Register check' })}>
        {checkQuery.data && (
          <div className="flex flex-col gap-2" data-testid="rfi-register-check">
            {failing.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-semantic-success">
                <CheckCircle2 size={16} />
                {t('rfi.types.check_passed', {
                  defaultValue: 'Every issued request carries what its type requires.',
                })}
              </p>
            ) : (
              <>
                <p className="flex items-center gap-2 text-sm text-semantic-error">
                  <AlertTriangle size={16} />
                  {t('rfi.types.check_failed', { defaultValue: 'Problems found: {{n}}', n: failing.length })}
                </p>
                <ul className="list-disc ps-5 text-xs text-content-secondary">
                  {failing.slice(0, 20).map((r, i) => (
                    <li key={`${r.rule_id}-${r.element_ref ?? i}`} title={r.message}>
                      {describeFinding(r)}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </WideModalSection>
    </WideModal>
  );
}
