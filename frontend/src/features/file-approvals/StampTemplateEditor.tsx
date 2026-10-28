// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Modal form to create a custom stamp template.
//
// Renders an inline SVG preview so users see the resulting stamp before
// saving. The placeholder text ``{{text}}`` / ``{{approver}}`` / ``{{date}}``
// is rendered with sample values in the preview, then sent as a literal
// template to the backend (which expands them at burn time).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import { useCreateStampTemplate } from './hooks';
import type { StampTemplatePayload } from './types';

interface StampTemplateEditorProps {
  open: boolean;
  onClose: () => void;
  projectId: string | null;
  /** Called with the new template id after a successful save. */
  onCreated?: (templateId: string) => void;
}

const DEFAULT_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="220" height="80" viewBox="0 0 220 80">
  <rect x="2" y="2" width="216" height="76" fill="none" stroke="{COLOR}" stroke-width="3"/>
  <text x="14" y="32" font-family="Helvetica" font-size="16" font-weight="bold" fill="{COLOR}">{{text}}</text>
  <text x="14" y="52" font-family="Helvetica" font-size="10" fill="{COLOR}">Approved by {{approver}}</text>
  <text x="14" y="68" font-family="Helvetica" font-size="10" fill="{COLOR}">{{date}}</text>
</svg>`;

export function StampTemplateEditor({
  open,
  onClose,
  projectId,
  onCreated,
}: StampTemplateEditorProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const create = useCreateStampTemplate();

  const [name, setName] = useState('');
  const [text, setText] = useState('CUSTOM');
  const [color, setColor] = useState('#7c3aed');
  const [svg, setSvg] = useState(DEFAULT_SVG);

  function reset() {
    setName('');
    setText('CUSTOM');
    setColor('#7c3aed');
    setSvg(DEFAULT_SVG);
  }

  async function handleSave() {
    if (!name.trim()) {
      addToast({
        type: 'error',
        title: t('files.approvals.stamp_name_required', {
          defaultValue: 'Stamp name is required',
        }),
      });
      return;
    }
    const payload: StampTemplatePayload = {
      project_id: projectId,
      name: name.trim(),
      text: text.trim() || 'STAMP',
      color: /^#[0-9A-Fa-f]{6}$/.test(color) ? color : '#16a34a',
      svg_template: svg.replaceAll('{COLOR}', color),
      is_active: true,
    };
    try {
      const created = await create.mutateAsync(payload);
      addToast({
        type: 'success',
        title: t('files.approvals.stamp_created', {
          defaultValue: 'Stamp "{{name}}" created',
          name: created.name,
        }),
      });
      onCreated?.(created.id);
      reset();
      onClose();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('files.approvals.stamp_create_failed', {
          defaultValue: 'Failed to create stamp',
        }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }

  // Compute preview SVG with sample placeholder values expanded.
  const previewSvg = svg
    .replaceAll('{COLOR}', color)
    .replaceAll('{{text}}', text || 'STAMP')
    .replaceAll('{{approver}}', 'Sample User')
    .replaceAll('{{date}}', new Date().toISOString().slice(0, 10));

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('files.approvals.editor_title', {
        defaultValue: 'Create stamp template',
      })}
      size="lg"
      busy={create.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={create.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('files.approvals.stamp_name', { defaultValue: 'Name' })}
          required
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={128}
            className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
            placeholder="Project Hold"
          />
        </WideModalField>
        <WideModalField
          label={t('files.approvals.stamp_text', {
            defaultValue: 'Label text',
          })}
          required
        >
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={255}
            className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm"
            placeholder="HOLD"
          />
        </WideModalField>
        <WideModalField
          label={t('files.approvals.stamp_color', { defaultValue: 'Color' })}
        >
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-12 rounded-md border border-border"
              aria-label={t('files.approvals.stamp_color_picker', {
                defaultValue: 'Color picker',
              })}
            />
            <input
              type="text"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              maxLength={7}
              className="h-9 px-3 rounded-md border border-border bg-surface-primary text-sm font-mono flex-1"
            />
          </div>
        </WideModalField>
        <WideModalField
          label={t('files.approvals.stamp_preview', { defaultValue: 'Preview' })}
        >
          {/*
            Render the user-pasted SVG inside a sandboxed iframe. The empty
            `sandbox=""` attribute strips ALL capabilities (scripts, forms,
            same-origin, popups, top-navigation), so any <script> embedded in
            a malicious stamp template cannot execute when another user
            opens the editor.  srcDoc keeps the content fully inline — no
            network round-trip, no separate origin to manage.
          */}
          <iframe
            sandbox=""
            srcDoc={previewSvg}
            className="h-24 w-full border border-border-light rounded-md bg-surface-secondary/30"
            title={t('files.approvals.stamp_preview', { defaultValue: 'Preview' })}
            aria-label={t('fileApprovals.stamps.previewLabel', {
              defaultValue: 'Stamp preview',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('files.approvals.stamp_svg', {
            defaultValue: 'SVG markup',
          })}
          hint={t('files.approvals.stamp_svg_hint', {
            defaultValue:
              'Use {{text}} / {{approver}} / {{date}} placeholders. {COLOR} is replaced with the chosen color.',
          })}
          span={2}
        >
          <textarea
            value={svg}
            onChange={(e) => setSvg(e.target.value)}
            rows={6}
            className="px-3 py-2 rounded-md border border-border bg-surface-primary text-xs font-mono resize-y"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
