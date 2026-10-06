// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Add fields and functions" for a module built here.
 *
 * Opens the module builder on the installed module, where everything entries
 * already use is locked and only new fields, checks and functions can be added.
 * That is all the server accepts on a module that holds records, so the button
 * never promises an edit it would then refuse.
 *
 * Shown to administrators, and only by a server that can upgrade in place. As
 * with the builder's own button, the role decides what to draw and the server
 * decides what is allowed. The wizard is loaded lazily.
 */
import { Suspense, lazy, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { PackagePlus } from 'lucide-react';
import clsx from 'clsx';

import { useAuthStore } from '@/stores/useAuthStore';

import { fetchVocabulary, supportsUpgrade } from './api';

const ModuleBuilderWizard = lazy(() =>
  import('./ModuleBuilderWizard').then((m) => ({ default: m.ModuleBuilderWizard })),
);

export interface ExtendModuleButtonProps {
  moduleKey: string;
  basePath: string;
  className?: string;
}

export function ExtendModuleButton({ moduleKey, basePath, className }: ExtendModuleButtonProps) {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [open, setOpen] = useState(false);

  // Shared with the wizard and the builder page, so it is asked for once.
  const vocabularyQuery = useQuery({
    queryKey: ['module-builder', 'vocabulary'],
    queryFn: fetchVocabulary,
    enabled: isAdmin,
    staleTime: 30 * 60_000,
  });

  if (!isAdmin || !supportsUpgrade(vocabularyQuery.data)) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
          className,
        )}
        data-testid={`module-builder-extend-${moduleKey}`}
      >
        <PackagePlus size={13} />
        {t('module_builder.extend', { defaultValue: 'Add fields and functions' })}
      </button>

      {open && (
        <Suspense fallback={null}>
          <ModuleBuilderWizard
            open={open}
            onClose={() => setOpen(false)}
            upgrade={{ key: moduleKey, basePath }}
          />
        </Suspense>
      )}
    </>
  );
}

export default ExtendModuleButton;
