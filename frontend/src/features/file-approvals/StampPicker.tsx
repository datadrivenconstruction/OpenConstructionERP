// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Grid of stamp-template tiles; clicking a tile selects it.
//
// Used inside SubmitForApprovalModal and as a standalone "manage stamps"
// surface accessible from project settings.

import { useTranslation } from 'react-i18next';
import { Plus, Stamp as StampIcon } from 'lucide-react';
import clsx from 'clsx';

import { useStampTemplates } from './hooks';
import type { StampTemplate } from './types';

interface StampPickerProps {
  projectId: string | null;
  value: string | null;
  onChange: (templateId: string | null) => void;
  onCreateCustom?: () => void;
  /** Allow the picker to render the "No stamp" tile (default true). */
  allowNone?: boolean;
}

export function StampPicker({
  projectId,
  value,
  onChange,
  onCreateCustom,
  allowNone = true,
}: StampPickerProps) {
  const { t } = useTranslation();
  const { data: templates = [], isLoading } = useStampTemplates(projectId);

  if (isLoading) {
    return (
      <p className="text-sm text-content-tertiary py-3 text-center">
        {t('common.loading', { defaultValue: 'Loading…' })}
      </p>
    );
  }

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-3 gap-2"
      role="radiogroup"
      aria-label={t('files.approvals.stamp_picker', {
        defaultValue: 'Stamp template',
      })}
    >
      {allowNone && (
        <button
          type="button"
          role="radio"
          aria-checked={value === null}
          onClick={() => onChange(null)}
          className={clsx(
            'h-24 rounded-lg border text-xs flex flex-col items-center justify-center gap-1',
            'transition-colors',
            value === null
              ? 'border-oe-blue bg-oe-blue-subtle/50 text-oe-blue-text'
              : 'border-border-light hover:bg-surface-secondary',
          )}
        >
          <StampIcon size={20} className="opacity-50" />
          <span>
            {t('files.approvals.no_stamp', { defaultValue: 'No stamp' })}
          </span>
        </button>
      )}
      {templates.map((tmpl) => (
        <StampTile
          key={tmpl.id}
          template={tmpl}
          selected={value === tmpl.id}
          onSelect={() => onChange(tmpl.id)}
        />
      ))}
      {onCreateCustom && (
        <button
          type="button"
          onClick={onCreateCustom}
          className={clsx(
            'h-24 rounded-lg border border-dashed border-border text-xs',
            'flex flex-col items-center justify-center gap-1',
            'text-content-secondary hover:text-content-primary hover:bg-surface-secondary',
          )}
        >
          <Plus size={20} />
          <span>
            {t('files.approvals.create_custom', {
              defaultValue: 'Create custom',
            })}
          </span>
        </button>
      )}
    </div>
  );
}

interface StampTileProps {
  template: StampTemplate;
  selected: boolean;
  onSelect: () => void;
}

function StampTile({ template, selected, onSelect }: StampTileProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={clsx(
        'h-24 rounded-lg border text-xs flex flex-col items-center justify-center gap-1 p-2',
        'transition-colors',
        selected
          ? 'border-oe-blue ring-2 ring-oe-blue/30 bg-oe-blue-subtle/30'
          : 'border-border-light hover:bg-surface-secondary',
      )}
    >
      <div
        className="px-2 py-1 rounded border-2 font-bold text-xs"
        style={{ borderColor: template.color, color: template.color }}
      >
        {template.text.slice(0, 16)}
      </div>
      <span className="text-content-secondary truncate w-full text-center">
        {template.name}
      </span>
    </button>
  );
}
