// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The frame every wizard step shares: one heading scale at the top and one
 * navigation row at the bottom, so moving between steps changes the content
 * and nothing else.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft } from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import { ButtonSizeOverrideContext } from '@/shared/ui/Button';

export function StepHeader({
  title,
  subtitle,
  as: Tag = 'h2',
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** The welcome step is the page's first heading; every other step is h2. */
  as?: 'h1' | 'h2';
  className?: string;
}) {
  return (
    <div className={clsx('flex flex-col items-center text-center', className)}>
      <Tag className="text-2xl font-semibold tracking-tight text-content-primary">{title}</Tag>
      {subtitle && <p className="mt-2 max-w-xl text-sm leading-relaxed text-content-secondary">{subtitle}</p>}
    </div>
  );
}

/**
 * Back on the start edge, the step's own actions on the end edge, primary
 * last, all at form height. A step without Back omits `onBack`.
 */
export function StepNav({
  onBack,
  children,
  className,
}: {
  onBack?: () => void;
  children?: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <ButtonSizeOverrideContext.Provider value="lg">
    <div
      className={clsx(
        // Sticky so the primary action stays in reach on long steps; the negative
        // margins match the step body padding so the bar spans the whole column.
        'sticky bottom-0 z-sticky -mx-4 mt-6 flex w-[calc(100%+2rem)] flex-wrap items-center justify-between gap-3 border-t border-border-light bg-surface-primary/90 px-4 py-4 backdrop-blur sm:-mx-6 sm:w-[calc(100%+3rem)] sm:px-6 lg:-mx-10 lg:w-[calc(100%+5rem)] lg:px-10',
        className,
      )}
    >
      {onBack ? (
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} className="rtl:rotate-180" />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
      ) : (
        <span aria-hidden />
      )}
      {children && <div className="ms-auto flex flex-wrap items-center justify-end gap-2">{children}</div>}
    </div>
    </ButtonSizeOverrideContext.Provider>
  );
}

/**
 * The skin of every pickable card in the wizard (language, start, profile):
 * a hairline border at rest, the accent border and tint once chosen.
 */
export function choiceCard(selected: boolean): string {
  return clsx(
    'rounded-xl border transition-[border-color,background-color,box-shadow] duration-200 ease-oe',
    selected
      ? 'border-oe-blue bg-oe-blue-subtle ring-1 ring-oe-blue'
      : 'border-border-light bg-surface-elevated hover:border-oe-blue/40 hover:shadow-sm',
  );
}
