// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The top-bar entry point to the module builder.
 *
 * It sits in the header rather than in the sidebar because building a module is
 * something you do *from wherever you are* - you notice the platform is missing
 * a register while you are looking at the thing that needs it. The sidebar
 * lists screens; this is an action.
 *
 * Shown to administrators only. Installing writes files onto the server and
 * loads them into the running process, which is `module_builder.install`, an
 * administrator permission. The role read here comes from the auth store and is
 * for deciding what to draw, never for access: the server enforces the
 * permission on the call itself, and a viewer who reached this some other way
 * is refused there.
 *
 * The wizard is loaded lazily. It is a large screen that most sessions never
 * open, and the header is on every page.
 */
import { Suspense, lazy, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Wand2 } from 'lucide-react';
import clsx from 'clsx';

import { useAuthStore } from '@/stores/useAuthStore';

const ModuleBuilderWizard = lazy(() =>
  import('./ModuleBuilderWizard').then((m) => ({ default: m.ModuleBuilderWizard })),
);

export function ModuleBuilderButton({ className }: { className?: string }) {
  const { t } = useTranslation();
  const role = useAuthStore((s) => s.userRole);
  const [open, setOpen] = useState(false);

  if (role !== 'admin') return null;

  const label = t('module_builder.header_button', { defaultValue: 'Build a module' });

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={label}
        title={label}
        data-testid="header-module-builder"
        className={clsx(
          'relative flex h-8 items-center justify-center gap-1.5 rounded-lg',
          // Icon-only below xl, labelled from xl up. Not md, where the other
          // labelled header pill sits: by lg the right-hand cluster is already
          // tight enough that the page title truncates and the search box is
          // held narrow until xl - both are written down in Header.tsx. A
          // second label at md would take that space from the title again,
          // while at xl there is room for both. The label never wraps, because
          // it is longer in several locales and a two-line button would break
          // the header's fixed height.
          'w-8 xl:w-auto xl:px-2.5',
          'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          'transition-colors focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
          className,
        )}
      >
        <Wand2 size={16} strokeWidth={1.9} />
        {/* `aria-label` stays on the button regardless: the accessible name is
            then the same string at every width, rather than appearing and
            disappearing with the breakpoint. */}
        <span className="hidden whitespace-nowrap text-xs font-medium xl:inline">{label}</span>
      </button>

      {open && (
        <Suspense fallback={null}>
          <ModuleBuilderWizard open={open} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  );
}

export default ModuleBuilderButton;
