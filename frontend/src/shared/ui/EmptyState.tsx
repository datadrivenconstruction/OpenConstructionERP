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
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-secondary text-content-tertiary">
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
