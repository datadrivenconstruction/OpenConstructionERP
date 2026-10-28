// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cost database - the invitation shown wherever the user has none yet.
//
// This is the first thing a new estimator meets on /costs, and it is the same
// prompt the dashboard shows while nothing has been imported, so the sentences
// live here once and both surfaces read alike. It is an invitation, not an
// error: no warning colour, no warning icon, and it says what a cost database
// is for before it says what to press.
//
// Two densities:
//   `page`    - the /costs surface. Importing a ready-made base is the large,
//               obvious action; building your own price list stays underneath.
//   `compact` - a single band, for the dashboard and for the /costs region tab
//               bar. One line and one button.
//
// Everything it offers is already built: `onImport` goes to /costs/import,
// which loads a regional base by country and currency or takes a spreadsheet
// of your own, and `onCreateOwn` opens the page's Add Item form.
//
// Tailwind's JIT only keeps classes it can see as complete tokens, so every
// class string here is a full literal - never built by concatenation.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Database, Download, Plus, ArrowRight } from 'lucide-react';
import { Button, Card } from '@/shared/ui';

export interface CostDatabaseInviteProps {
  /** Open the importer (`/costs/import`). */
  onImport: () => void;
  /** Start an own price list. Omit it and the second path is not offered -
   *  the compact band deliberately carries a single action. */
  onCreateOwn?: () => void;
  variant?: 'page' | 'compact';
  className?: string;
}

export function CostDatabaseInvite({
  onImport,
  onCreateOwn,
  variant = 'page',
  className,
}: CostDatabaseInviteProps) {
  const { t } = useTranslation();

  const title = t('costs.empty_state.title', { defaultValue: 'Start your cost database' });
  const importCta = t('costs.empty_state.import_cta', { defaultValue: 'Import a database' });

  if (variant === 'compact') {
    return (
      <Card
        padding="none"
        className={clsx('animate-fade-in', className)}
        data-testid="cost-database-invite-compact"
      >
        <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
            <Database size={20} strokeWidth={1.75} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-content-secondary">
              {t('costs.empty_state.compact_subtitle', {
                defaultValue:
                  'A cost database holds the unit rates you price work with. Load one and every rate becomes searchable here, ready to drop into a bill of quantities.',
              })}
            </p>
          </div>
          <Button
            variant="primary"
            size="md"
            icon={<Download size={15} />}
            onClick={onImport}
            className="shrink-0 self-start sm:self-auto"
          >
            {importCta}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card
      padding="none"
      className={clsx('mx-auto max-w-3xl animate-fade-in', className)}
      data-testid="costs-empty-state"
    >
      <div className="flex flex-col items-center px-6 pt-8 pb-6 text-center">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary shadow-[inset_0_2px_4px_rgba(0,0,0,0.06),inset_0_-1px_0_rgba(255,255,255,0.6)]">
          <Database size={28} strokeWidth={1.5} />
        </div>
        <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
        <p className="mt-1.5 max-w-md text-sm text-content-secondary">
          {t('costs.empty_state.subtitle', {
            defaultValue:
              'A cost database holds the unit rates you price work with. Pick how you want to begin - you can do both, and add more any time.',
          })}
        </p>
      </div>

      {/* Primary path. Tinted panel, full-size button, and the one line about
          what the import leaves behind - this is the action a first-time user
          should not have to look for. */}
      <div className="px-4 sm:px-6">
        <div className="rounded-xl border border-oe-blue/20 bg-oe-blue-subtle/30 p-5 sm:p-6">
          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue text-content-inverse">
              <Download size={18} />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-content-primary">
                {t('costs.empty_state.import_title', { defaultValue: 'Import a ready-made base' })}
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-content-secondary">
                {t('costs.empty_state.import_desc', {
                  defaultValue:
                    'Load a regional construction cost database with tens of thousands of priced items for materials, labour and equipment. Search it and pull rates straight into your estimates.',
                })}
              </p>
            </div>
          </div>
          <Button
            variant="primary"
            size="lg"
            icon={<ArrowRight size={16} />}
            iconPosition="right"
            onClick={onImport}
            className="mt-5 w-full sm:w-auto"
          >
            {importCta}
          </Button>
          <p className="mt-3 text-xs leading-relaxed text-content-tertiary">
            {t('costs.empty_state.after_import', {
              defaultValue:
                'Once a database is loaded its rates are searchable here, and they carry their currency and classification with them into a bill of quantities.',
            })}
          </p>
        </div>
      </div>

      {/* Second path - quieter, still one click away. */}
      {onCreateOwn && (
        <div className="p-4 sm:p-6">
          <div className="flex flex-col gap-3 rounded-xl border border-border-light bg-surface-secondary/30 p-5 sm:flex-row sm:items-center sm:gap-5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
              <Plus size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('costs.empty_state.create_title', { defaultValue: 'Create your own' })}
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-content-secondary">
                {t('costs.empty_state.create_desc', {
                  defaultValue:
                    'Build your own price list from scratch. Add each rate - code, description, unit and price - and reuse it across every project. Best when you already know your own prices.',
                })}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={onCreateOwn}
              className="shrink-0 self-start sm:self-auto"
            >
              {t('costs.empty_state.create_cta', { defaultValue: 'Add your first rate' })}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
