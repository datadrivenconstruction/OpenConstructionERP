// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Before installing a pack: exactly which modules it turns on, grouped and
 * explained, which demo data comes with it, and whether the menu should keep
 * only those modules afterwards.
 */
import { useTranslation } from 'react-i18next';
import { Boxes, FolderKanban } from 'lucide-react';
import { useFocusPreview } from './api';
import { FocusModuleList } from './FocusModuleList';

export function PackFocusPreview({
  slug,
  focus,
  onFocusChange,
  canChoose,
}: {
  slug: string;
  focus: boolean;
  onFocusChange: (v: boolean) => void;
  canChoose: boolean;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useFocusPreview(slug);
  if (isLoading) return <div className="h-40 animate-pulse rounded-xl bg-surface-secondary" aria-busy="true" />;
  if (isError || !data) return null;

  return (
    <section className="rounded-xl border border-border-light bg-surface-elevated p-4 sm:p-5" data-testid="pack-focus-preview">
      <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Boxes size={15} aria-hidden className="text-oe-blue" />
        {t('packs.focus_preview_title', { defaultValue: 'Modules this pack turns on: {{n}}', n: data.modules.length })}
      </h3>
      <p className="mb-3 mt-0.5 text-xs text-content-tertiary">
        {data.source === 'fallback'
          ? t('packs.focus_preview_fallback', {
              defaultValue: 'The pack names no modules of its own, so it gets the standard estimating and tender set.',
            })
          : t('packs.focus_preview_declared', { defaultValue: 'The modules the pack itself names, with what they need.' })}
      </p>
      <FocusModuleList modules={data.modules} testId="pack-focus-preview-list" />

      <div className="mt-4 rounded-lg bg-surface-secondary/60 p-3">
        <p className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary">
          <FolderKanban size={13} aria-hidden />
          {data.demo_template_ids.length
            ? t('packs.focus_demo_n', { defaultValue: 'Demo data: {{n}} filled-in projects, so no screen starts empty', n: data.demo_template_ids.length })
            : t('packs.focus_demo_none', { defaultValue: 'No demo project; start from your own project.' })}
        </p>
      </div>

      {canChoose && (
        <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={focus}
            onChange={(e) => onFocusChange(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-border"
            data-testid="pack-focus-toggle"
          />
          <span>
            {t('packs.focus_toggle', {
              defaultValue: 'After install, show only these modules in the menu ({{hidden}} others hidden, not removed)',
              hidden: data.hidden.length,
            })}
          </span>
        </label>
      )}
    </section>
  );
}
