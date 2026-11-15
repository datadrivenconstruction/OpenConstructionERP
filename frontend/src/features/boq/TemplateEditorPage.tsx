// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Editor for an estimate template: name, description, classification standard,
 * sections and positions (add, remove, reorder, units, default quantities,
 * optional rates). Built-in templates open read only with a "duplicate to
 * edit" action; they are never changed in place.
 *
 * Saving first asks the server's template rules. Warnings are listed and the
 * author may save anyway, because a template with gaps is still a useful start.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, Copy, ListOrdered, Plus, Trash2 } from 'lucide-react';

import { Breadcrumb, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  moveItem,
  renumberSections,
  templatesApi,
  toWriteBody,
  type TemplateIssue,
  type TemplatePosition,
  type TemplateSection,
  type TemplateWriteBody,
} from './templatesApi';

const EMPTY_POSITION: TemplatePosition = {
  ordinal: '',
  description: '',
  unit: '',
  quantity: null,
  qty_factor: null,
  rate: null,
  classification: {},
};

const cell = 'oe-input w-full text-sm';

export function TemplateEditorPage() {
  const { t } = useTranslation();
  const { templateId = '' } = useParams<{ templateId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['boq-template', templateId],
    queryFn: () => templatesApi.get(templateId),
    enabled: !!templateId,
  });

  const [draft, setDraft] = useState<TemplateWriteBody | null>(null);
  const [issues, setIssues] = useState<TemplateIssue[] | null>(null);

  useEffect(() => {
    if (data) {
      setDraft(toWriteBody(data));
      setIssues(null);
    }
  }, [data]);

  const readOnly = data?.builtin ?? true;

  const duplicate = useMutation({
    mutationFn: () => templatesApi.duplicate(templateId),
    onSuccess: (copy) => {
      void queryClient.invalidateQueries({ queryKey: ['boq-templates'] });
      addToast({
        type: 'success',
        title: t('boq_templates.duplicated', { defaultValue: 'Copy created. Edit it here.' }),
      });
      navigate(`/templates/${copy.id}`);
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq_templates.duplicate_failed', { defaultValue: 'Could not copy the template' }),
        message: e.message,
      }),
  });

  const save = useMutation({
    mutationFn: (body: TemplateWriteBody) => templatesApi.update(templateId, body),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['boq-templates'] });
      queryClient.setQueryData(['boq-template', templateId], saved);
      setIssues(saved.warnings);
      addToast({ type: 'success', title: t('boq_templates.saved', { defaultValue: 'Template saved' }) });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq_templates.save_failed', { defaultValue: 'Could not save the template' }),
        message: e.message,
      }),
  });

  const check = useMutation({
    mutationFn: (body: TemplateWriteBody) => templatesApi.validate(body),
    onSuccess: (found, body) => {
      setIssues(found);
      if (found.length === 0) save.mutate(body);
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq_templates.check_failed', { defaultValue: 'Could not check the template' }),
        message: e.message,
      }),
  });

  if (isPending) {
    return <p className="text-sm text-content-tertiary">{t('boq_templates.loading', { defaultValue: 'Loading templates' })}</p>;
  }
  if (isError || !draft) {
    return (
      <p className="text-sm text-semantic-error">
        {error instanceof Error ? error.message : t('boq_templates.load_failed', { defaultValue: 'Could not load the templates' })}
      </p>
    );
  }

  const setSections = (fn: (s: TemplateSection[]) => TemplateSection[]) =>
    setDraft((d) => (d ? { ...d, sections: fn(d.sections) } : d));
  const setSection = (si: number, patch: Partial<TemplateSection>) =>
    setSections((all) => all.map((s, i) => (i === si ? { ...s, ...patch } : s)));
  const setPosition = (si: number, pi: number, patch: Partial<TemplatePosition>) =>
    setSections((all) =>
      all.map((s, i) =>
        i === si ? { ...s, positions: s.positions.map((p, j) => (j === pi ? { ...p, ...patch } : p)) } : s,
      ),
    );

  const blank = (v: string): string | null => (v.trim() === '' ? null : v);

  const issueAt = (si: number, pi?: number) =>
    (issues ?? []).filter((i) => i.path.section === si && i.path.position === pi);

  const ruleText = (i: TemplateIssue) => {
    const key = i.rule_id.split('.').pop() ?? i.rule_id;
    return t(`boq_templates.rule_${key}`, {
      defaultValue: i.rule_id,
      ...(i.params as Record<string, string>),
    });
  };

  const busy = save.isPending || check.isPending;

  return (
    <div className="space-y-5 animate-fade-in pb-12">
      <Breadcrumb
        items={[
          { label: t('boq.templates', { defaultValue: 'BOQ Templates' }), to: '/templates' },
          { label: draft.name || t('boq_templates.untitled', { defaultValue: 'Untitled template' }) },
        ]}
      />

      {readOnly && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border-light bg-surface-secondary px-4 py-3 text-sm"
          data-testid="tpl-readonly-notice"
        >
          <span>
            {t('boq_templates.builtin_notice', {
              defaultValue: 'This is a built-in template and cannot be changed. Make your own copy to edit it.',
            })}
          </span>
          <Button size="sm" icon={<Copy size={14} />} loading={duplicate.isPending} onClick={() => duplicate.mutate()}>
            {t('boq_templates.duplicate_to_edit', { defaultValue: 'Duplicate to edit' })}
          </Button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="oe-overline">{t('boq_templates.template_name', { defaultValue: 'Template name' })}</span>
          <input
            className="oe-input mt-1 w-full"
            value={draft.name}
            maxLength={255}
            disabled={readOnly}
            data-testid="tpl-name"
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </label>
        <label className="block text-sm">
          <span className="oe-overline">{t('boq_templates.standard', { defaultValue: 'Classification standard' })}</span>
          <input
            className="oe-input mt-1 w-full"
            value={draft.classification_standard}
            maxLength={50}
            disabled={readOnly}
            placeholder={t('boq_templates.standard_hint', { defaultValue: 'for example din276, nrm, masterformat' })}
            onChange={(e) => setDraft({ ...draft, classification_standard: e.target.value })}
          />
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="oe-overline">{t('boq_templates.description', { defaultValue: 'Description' })}</span>
          <textarea
            className="oe-input mt-1 w-full"
            rows={2}
            value={draft.description}
            disabled={readOnly}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </label>
      </div>

      {!readOnly && (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon={<Plus size={14} />}
            data-testid="tpl-add-section"
            onClick={() =>
              setSections((all) => [...all, { ordinal: String(all.length + 1).padStart(2, '0'), description: '', classification: {}, positions: [] }])
            }
          >
            {t('boq_templates.add_section', { defaultValue: 'Add section' })}
          </Button>
          <Button size="sm" variant="secondary" icon={<ListOrdered size={14} />} onClick={() => setSections(renumberSections)}>
            {t('boq_templates.renumber_all', { defaultValue: 'Renumber' })}
          </Button>
        </div>
      )}

      {draft.sections.map((sec, si) => (
        <section key={si} className="rounded-xl border border-border-light bg-surface-elevated" data-testid={`tpl-section-${si}`}>
          <div className="flex flex-wrap items-center gap-2 border-b border-border-light bg-surface-tertiary/30 p-3">
            <input
              className={`${cell} w-24`}
              value={sec.ordinal}
              disabled={readOnly}
              aria-label={t('boq_templates.col_ordinal', { defaultValue: 'No.' })}
              onChange={(e) => setSection(si, { ordinal: e.target.value })}
            />
            <input
              className={`${cell} min-w-[12rem] flex-1 font-medium`}
              value={sec.description}
              disabled={readOnly}
              placeholder={t('boq_templates.section_placeholder', { defaultValue: 'Section title' })}
              aria-label={t('boq_templates.section_placeholder', { defaultValue: 'Section title' })}
              onChange={(e) => setSection(si, { description: e.target.value })}
            />
            {!readOnly && (
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" aria-label={t('boq_templates.move_up', { defaultValue: 'Move up' })} icon={<ArrowUp size={14} />} onClick={() => setSections((a) => moveItem(a, si, si - 1))} />
                <Button size="sm" variant="ghost" aria-label={t('boq_templates.move_down', { defaultValue: 'Move down' })} icon={<ArrowDown size={14} />} onClick={() => setSections((a) => moveItem(a, si, si + 1))} />
                <Button size="sm" variant="ghost" aria-label={t('boq_templates.remove_section', { defaultValue: 'Remove section' })} icon={<Trash2 size={14} />} onClick={() => setSections((a) => a.filter((_, i) => i !== si))} />
              </div>
            )}
          </div>
          {issueAt(si, undefined).map((i, k) => (
            <p key={k} className="px-3 pt-2 text-xs text-semantic-warning">{ruleText(i)}</p>
          ))}

          <div className="overflow-x-auto p-3">
            <table className="w-full min-w-[44rem] text-left">
              <thead>
                <tr className="oe-overline">
                  <th className="w-28 pb-1 pr-2">{t('boq_templates.col_ordinal', { defaultValue: 'No.' })}</th>
                  <th className="pb-1 pr-2">{t('boq_templates.col_description', { defaultValue: 'Description' })}</th>
                  <th className="w-20 pb-1 pr-2">{t('boq_templates.col_unit', { defaultValue: 'Unit' })}</th>
                  <th className="w-24 pb-1 pr-2">{t('boq_templates.col_quantity', { defaultValue: 'Quantity' })}</th>
                  <th className="w-24 pb-1 pr-2">{t('boq_templates.col_factor', { defaultValue: 'Per m2' })}</th>
                  <th className="w-24 pb-1 pr-2">{t('boq_templates.col_rate', { defaultValue: 'Rate' })}</th>
                  <th className="w-28 pb-1" />
                </tr>
              </thead>
              <tbody>
                {sec.positions.map((pos, pi) => {
                  const rowIssues = issueAt(si, pi);
                  return (
                    <tr key={pi} data-testid={`tpl-row-${si}-${pi}`} className={rowIssues.length ? 'bg-semantic-warning/10' : ''}>
                      <td className="py-1 pr-2"><input className={cell} value={pos.ordinal} disabled={readOnly} onChange={(e) => setPosition(si, pi, { ordinal: e.target.value })} aria-label={t('boq_templates.col_ordinal', { defaultValue: 'No.' })} /></td>
                      <td className="py-1 pr-2"><input className={cell} value={pos.description} disabled={readOnly} onChange={(e) => setPosition(si, pi, { description: e.target.value })} aria-label={t('boq_templates.col_description', { defaultValue: 'Description' })} /></td>
                      <td className="py-1 pr-2"><input className={cell} value={pos.unit} maxLength={20} disabled={readOnly} onChange={(e) => setPosition(si, pi, { unit: e.target.value })} aria-label={t('boq_templates.col_unit', { defaultValue: 'Unit' })} /></td>
                      <td className="py-1 pr-2"><input className={cell} inputMode="decimal" value={pos.quantity ?? ''} disabled={readOnly} onChange={(e) => setPosition(si, pi, { quantity: blank(e.target.value) })} aria-label={t('boq_templates.col_quantity', { defaultValue: 'Quantity' })} /></td>
                      <td className="py-1 pr-2"><input className={cell} inputMode="decimal" value={pos.qty_factor ?? ''} disabled={readOnly} onChange={(e) => setPosition(si, pi, { qty_factor: blank(e.target.value) })} aria-label={t('boq_templates.col_factor', { defaultValue: 'Per m2' })} /></td>
                      <td className="py-1 pr-2"><input className={cell} inputMode="decimal" value={pos.rate ?? ''} disabled={readOnly} onChange={(e) => setPosition(si, pi, { rate: blank(e.target.value) })} aria-label={t('boq_templates.col_rate', { defaultValue: 'Rate' })} /></td>
                      <td className="py-1">
                        {!readOnly && (
                          <div className="flex gap-1">
                            <Button size="sm" variant="ghost" aria-label={t('boq_templates.move_up', { defaultValue: 'Move up' })} icon={<ArrowUp size={14} />} onClick={() => setSection(si, { positions: moveItem(sec.positions, pi, pi - 1) })} />
                            <Button size="sm" variant="ghost" aria-label={t('boq_templates.move_down', { defaultValue: 'Move down' })} icon={<ArrowDown size={14} />} onClick={() => setSection(si, { positions: moveItem(sec.positions, pi, pi + 1) })} />
                            <Button size="sm" variant="ghost" aria-label={t('boq_templates.remove_position', { defaultValue: 'Remove position' })} icon={<Trash2 size={14} />} onClick={() => setSection(si, { positions: sec.positions.filter((_, j) => j !== pi) })} />
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!readOnly && (
              <Button
                size="sm"
                variant="ghost"
                icon={<Plus size={14} />}
                className="mt-2"
                data-testid={`tpl-add-position-${si}`}
                onClick={() => setSection(si, { positions: [...sec.positions, { ...EMPTY_POSITION }] })}
              >
                {t('boq_templates.add_position', { defaultValue: 'Add position' })}
              </Button>
            )}
          </div>
        </section>
      ))}

      {issues && issues.length > 0 && (
        <div className="rounded-xl border border-semantic-warning/40 bg-semantic-warning/10 px-4 py-3 text-sm" data-testid="tpl-warnings">
          <p className="font-medium">
            {t('boq_templates.warnings_title', { defaultValue: 'Check before saving' })} ({issues.length})
          </p>
          <ul className="mt-1 list-disc pl-5">
            {issues.map((i, k) => (
              <li key={k}>{ruleText(i)}</li>
            ))}
          </ul>
        </div>
      )}

      {!readOnly && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => navigate('/templates')}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {issues && issues.length > 0 && (
            <Button variant="secondary" loading={save.isPending} data-testid="tpl-save-anyway" onClick={() => save.mutate(draft)}>
              {t('boq_templates.save_anyway', { defaultValue: 'Save anyway' })}
            </Button>
          )}
          <Button loading={busy} data-testid="tpl-save" onClick={() => check.mutate(draft)}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      )}
    </div>
  );
}
