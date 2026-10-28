// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { isValidElement, type ReactNode } from 'react';
import { Button } from './Button';

interface ActionObject {
  label: string;
  onClick: () => void;
}

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ActionObject | ReactNode;
  className?: string;
}

/* Standardised empty-state copy (Probe-D P2-11). All callers should
 * resolve i18n keys via this helper to keep the wording aligned across
 * modules: "No {entity} yet" / "Create your first {entity}". The
 * shared keys live under `empty.*` in the locale dictionaries; if a key
 * is missing it falls back to the English template.
 *
 * Usage:
 *   const c = standardEmptyCopy(t, 'project');
 *   <EmptyState title={c.title} description={c.description}
 *               action={{ label: c.actionLabel, onClick: ... }} />
 */
export function standardEmptyCopy(
  t: (key: string, options?: Record<string, unknown>) => string,
  entity: string,
  entityPluralLabel?: string,
): { title: string; description: string; actionLabel: string } {
  const plural = entityPluralLabel ?? `${entity}s`;
  return {
    title: t('empty.no_yet', {
      defaultValue: 'No {{plural}} yet',
      plural,
    }),
    description: t('empty.no_yet_description', {
      defaultValue: 'Get started by creating your first {{entity}}.',
      entity,
    }),
    actionLabel: t('empty.create_first', {
      defaultValue: 'Create your first {{entity}}',
      entity,
    }),
  };
}

function isActionObject(action: unknown): action is ActionObject {
  return (
    typeof action === 'object' &&
    action !== null &&
    !isValidElement(action) &&
    'label' in action &&
    'onClick' in action
  );
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center py-16 px-6 text-center',
        className,
      )}
    >
      {icon && (
        /* Inset Depth chip — subtle inset shadow, no color fill. Replaces the
           old soft surface-secondary block. r=8px (rounded-md) per 2026-05-11
           design-system tightening. */
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary shadow-[inset_0_2px_4px_rgba(0,0,0,0.06),inset_0_-1px_0_rgba(255,255,255,0.6)]">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-semibold text-content-primary">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-content-secondary">{description}</p>
      )}
      {action && (
        <div className="mt-5">
          {isActionObject(action) ? (
            <Button variant="primary" onClick={action.onClick}>
              {action.label}
            </Button>
          ) : (
            action
          )}
        </div>
      )}
    </div>
  );
}
