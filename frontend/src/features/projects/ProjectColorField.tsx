// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project colour picker: one swatch per palette colour, plus "automatic" which
 * clears the stored colour so the one derived from the id shows. Saved on the
 * project, so the whole team sees the same colour.
 */
import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Sparkles } from 'lucide-react';
import { PROJECT_PALETTE, defaultProjectColor, isProjectColor } from '@/shared/lib/projectColor';

export function ProjectColorField({
  projectId,
  value,
  onChange,
  disabled = false,
}: {
  projectId: string;
  value: string | null | undefined;
  onChange: (next: string | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const labelId = useId();
  const stored = isProjectColor(value) ? value.toLowerCase() : null;
  const auto = defaultProjectColor(projectId);

  const swatch = (color: string | null, label: string) => {
    const active = stored === color;
    const paint = color ?? auto;
    return (
      <button
        key={color ?? 'auto'}
        type="button"
        role="radio"
        aria-checked={active}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={() => onChange(color)}
        className={`relative flex h-8 w-8 items-center justify-center rounded-full border-2 transition-transform disabled:opacity-60 ${
          active ? 'scale-110 border-content-primary' : 'border-transparent hover:scale-105'
        }`}
        style={{ background: paint }}
      >
        {active && <Check size={14} className="text-white drop-shadow" />}
        {color === null && !active && <Sparkles size={13} className="text-white drop-shadow" />}
      </button>
    );
  };

  return (
    <div>
      <p id={labelId} className="mb-1.5 text-sm font-medium text-content-primary">
        {t('projects.color.label', { defaultValue: 'Project colour' })}
      </p>
      <div role="radiogroup" aria-labelledby={labelId} className="flex flex-wrap gap-2">
        {swatch(null, t('projects.color.auto', { defaultValue: 'Automatic' }))}
        {PROJECT_PALETTE.map((c) => swatch(c, c))}
      </div>
      <p className="mt-1.5 text-xs text-content-tertiary">
        {t('projects.color.hint', {
          defaultValue:
            'Shown as a stripe at the top while you work in this project and as a dot in project lists. Everyone on the team sees it.',
        })}
      </p>
    </div>
  );
}

/** Small round marker of a project's colour, for lists and pickers. */
export function ProjectColorDot({ color, className = '' }: { color: string | null; className?: string }) {
  if (!color) return null;
  return <span aria-hidden className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${className}`} style={{ background: color }} />;
}
