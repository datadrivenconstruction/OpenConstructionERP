// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the public demonstration says when it refuses a write.
 *
 * Mounted once, at the top of the app, because the refusal can arrive from any
 * screen and every screen would otherwise need its own copy of this answer.
 * It is driven entirely by {@link useDemoReadOnlyStore}, which only the
 * transport sets, and the transport only sets it from what the server replied.
 * There is no hostname test and no build flag anywhere in this path, so an
 * installed copy of the product cannot show this to anybody.
 *
 * A dialog rather than a toast. A toast is the right shape for something that
 * happened in passing; this is the product explaining what it is and then
 * offering the visitor the thing they were actually reaching for, which is a
 * copy of their own.
 */
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Download, Info } from 'lucide-react';
import clsx from 'clsx';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useDemoReadOnlyStore } from '@/stores/useDemoReadOnlyStore';

/** Where the real builds live. Already the download link used elsewhere in the app. */
const DOWNLOAD_URL = 'https://openconstructionerp.com/download';

/**
 * The install options, in the order a visitor is likely to want them.
 *
 * Read off what the release pipelines actually publish, not off what the
 * product is assumed to ship: `.github/workflows/desktop-release.yml` for the
 * Windows NSIS `.exe`, the Apple Silicon `.dmg` and the Linux `.deb`,
 * `.AppImage` and `.rpm`; `.github/workflows/release.yml` for the container
 * image; `.github/workflows/pypi-publish.yml` for the wheel. Anything added to
 * or dropped from those workflows belongs here the same day.
 */
const INSTALL_OPTIONS: { key: string; fallback: string }[] = [
  { key: 'demo_read_only.install_windows', fallback: 'Windows: an installer that carries everything it needs, nothing else to set up' },
  { key: 'demo_read_only.install_macos', fallback: 'macOS: a disk image for Apple Silicon' },
  { key: 'demo_read_only.install_linux', fallback: 'Linux: a .deb for Debian and Ubuntu, an .rpm for Fedora and openSUSE, or an AppImage that runs anywhere' },
  { key: 'demo_read_only.install_docker', fallback: 'Docker: one container image from the public registry' },
  { key: 'demo_read_only.install_python', fallback: 'Python: install the package with pip install openconstructionerp' },
  { key: 'demo_read_only.install_source', fallback: 'From source: clone the repository and run make quickstart' },
];

export function DemoReadOnlyDialog() {
  const { t } = useTranslation();
  const open = useDemoReadOnlyStore((s) => s.open);
  const dismiss = useDemoReadOnlyStore((s) => s.dismiss);
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const dismissRef = useRef<HTMLButtonElement>(null);

  // Put the screen back to what the server holds.
  //
  // The write was refused, so anything the page painted in advance of the
  // answer is now a change that never happened, and a dialog that closes over
  // a row still showing the new value has told the visitor one thing and left
  // them looking at another. Refetching the mounted queries is the general
  // form of that undo: it is what the server actually holds, not a guess at
  // what to reverse.
  //
  // `invalidateQueries()` with no filter defaults to `refetchType: 'active'`,
  // so this touches mounted queries and leaves the rest to refetch when they
  // next mount. That is the whole blast radius, and it is the right one.
  //
  // It cannot reach state that never came from a query: text still sitting in
  // a form inside a modal, or an AG Grid cell mid-edit. Those belong to the
  // component that owns them and are unwound by its own error handling, which
  // still runs because the transport goes on throwing.
  useEffect(() => {
    if (!open) return;
    void queryClient.invalidateQueries();
  }, [open, queryClient]);

  // Escape closes it. Capture phase, like the other dialogs in this tree, so a
  // grid or editor underneath does not eat the key first.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        dismiss();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, dismiss]);

  // Backdrop click closes it too. Nothing here is a decision the visitor has
  // to make, so there is no reason to hold them in it.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        dismiss();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, dismiss]);

  useEffect(() => {
    if (open) dismissRef.current?.focus();
  }, [open]);

  useFocusTrap(dialogRef, open);

  if (!open) return null;

  return (
    // Above every other layer in the tree. The refusal can be raised from
    // inside a modal or from a cell editor in the BOQ grid, both of which sit
    // near the top of the stacking order, and an explanation rendered behind
    // the thing that provoked it explains nothing.
    <div className="fixed inset-0 z-[10000] flex items-center justify-center" data-testid="demo-read-only-dialog">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" />

      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="demo-read-only-title"
        aria-describedby="demo-read-only-example"
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
      >
        <div className="px-6 pt-6 pb-4">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full mb-4 bg-oe-blue/10 text-oe-blue">
            <Info size={20} />
          </div>

          <h2 id="demo-read-only-title" className="text-base font-semibold text-content-primary text-center">
            {t('demo_read_only.title', { defaultValue: 'This is a demonstration' })}
          </h2>

          <p id="demo-read-only-example" className="mt-3 text-sm text-content-secondary leading-relaxed">
            {t('demo_read_only.example_data', {
              defaultValue:
                'The projects here are examples, put in so you can see how the product works with real material in it. Everyone looking at this page sees the same ones, so nothing you change here is kept.',
            })}
          </p>

          <p className="mt-3 text-sm text-content-secondary leading-relaxed">
            {t('demo_read_only.runs_on_your_machine', {
              defaultValue:
                'The product itself runs on your own machine. Installing it takes a few minutes. Your projects, your prices and your drawings stay where you put them and remain yours - they are not sent to us, because there is nowhere for them to be sent.',
            })}
          </p>

          <h3 className="mt-5 text-sm font-semibold text-content-primary">
            {t('demo_read_only.install_heading', { defaultValue: 'Ways to install it' })}
          </h3>

          <ul className="mt-2 space-y-1.5 text-sm text-content-secondary leading-relaxed list-disc pl-5">
            {INSTALL_OPTIONS.map((option) => (
              <li key={option.key}>{t(option.key, { defaultValue: option.fallback })}</li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col-reverse sm:flex-row gap-3 px-6 pb-6">
          <button
            ref={dismissRef}
            type="button"
            onClick={dismiss}
            data-testid="demo-read-only-dismiss"
            className={clsx(
              'flex-1 rounded-lg px-4 py-2.5',
              'text-sm font-medium transition-all',
              'bg-surface-primary text-content-primary',
              'border border-border',
              'hover:bg-surface-secondary active:bg-surface-tertiary',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
            )}
          >
            {t('demo_read_only.keep_looking', { defaultValue: 'Keep looking around' })}
          </button>
          <a
            href={DOWNLOAD_URL}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="demo-read-only-download"
            className={clsx(
              'flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5',
              'text-sm font-medium transition-all',
              'bg-oe-blue text-white hover:bg-oe-blue-hover active:bg-oe-blue-active',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
            )}
          >
            <Download size={16} />
            {t('demo_read_only.get_it', { defaultValue: 'Get it for your machine' })}
          </a>
        </div>
      </div>
    </div>
  );
}
