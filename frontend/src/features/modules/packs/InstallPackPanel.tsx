// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useId } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { FileArchive, Loader2, RefreshCw, ShieldCheck, UploadCloud } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { PackOwnCopyHint } from '../PartnerPackApplyDialog';
import { canInstallPacks, MAX_PACK_UPLOAD_BYTES, useInstallPack, useRescanPacks } from '../partnerPacks';

/** Shown instead of the install controls to accounts that may only view packs. */
export function ViewerPackNotice() {
  const { t } = useTranslation();
  if (canInstallPacks(useAuthStore((s) => s.userRole))) return null;
  return (
    <div
      role="note"
      data-testid="pack-viewer-notice"
      className="mb-4 flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3.5 py-3 text-sm text-content-secondary"
    >
      <ShieldCheck size={16} className="mt-0.5 shrink-0" />
      <span>
        {t('modules.pp_viewer_notice', {
          defaultValue: 'This account can view packs but not install them. Installing a pack needs an administrator.',
        })}
        <PackOwnCopyHint />
      </span>
    </div>
  );
}

/* ── Install / Rescan panel ────────────────────────────────────────────── */

/**
 * Admin-only control strip for getting a partner pack onto this install:
 * upload a ``.zip`` (file picker or drag-and-drop) which POSTs to
 * ``/v1/partner-pack/install``, or Rescan ``<data-dir>/packs/`` for packs the
 * operator dropped in by hand. Non-admins see nothing — the underlying
 * endpoints are ``RequirePermission("admin")`` server-side, so we mirror that
 * gate here and never render a control that would only ever 403.
 *
 * ``onChanged`` is called after a successful install or rescan so the parent
 * tab can refetch the installed list; the install/rescan hooks also invalidate
 * the shared partner-pack query keys, so the grid updates immediately.
 */
export function InstallPackPanel({ onChanged }: { onChanged: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isAdmin = canInstallPacks(useAuthStore((s) => s.userRole));

  const install = useInstallPack();
  const rescan = useRescanPacks();

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dropDescId = useId();

  // Only administrators can install or rescan packs (RequirePermission("admin")
  // on the backend). Render nothing for everyone else.
  if (!isAdmin) return null;

  const busy = install.isPending || rescan.isPending;

  /** Client-side guard: must be a .zip and under the 25 MiB cap before upload.
   *  Returns a human-readable reason string when rejected, or null when OK. */
  function rejectReason(file: File): string | null {
    const isZip =
      file.type === 'application/zip' ||
      file.type === 'application/x-zip-compressed' ||
      file.type === 'application/octet-stream' || // some browsers send this for .zip
      file.name.toLowerCase().endsWith('.zip');
    if (!isZip) {
      return t('modules.pack_install_not_zip', {
        defaultValue: 'Please choose a .zip file. Packs are distributed as a single .zip archive.',
      });
    }
    if (file.size > MAX_PACK_UPLOAD_BYTES) {
      return t('modules.pack_install_too_large', {
        defaultValue: 'That file is {{size}} MB. Packs must be 25 MB or smaller.',
        size: fmtFixed(file.size / (1024 * 1024), 1),
      });
    }
    return null;
  }

  function handleFile(file: File | undefined | null) {
    if (!file) return;
    const reason = rejectReason(file);
    if (reason) {
      addToast({
        type: 'error',
        title: t('modules.pack_install_rejected', { defaultValue: "Can't install this file" }),
        message: reason,
      });
      return;
    }
    install.mutate(file, {
      onSuccess: (res) => {
        addToast({
          type: 'success',
          title: t('modules.pack_install_ok', { defaultValue: 'Pack installed' }),
          message: t('modules.pack_install_ok_msg', {
            defaultValue: '{{name}} ({{slug}}) v{{version}} is now available. Press Activate to apply it.',
            name: res.partner_name,
            slug: res.slug,
            version: res.pack_version,
          }),
        });
        onChanged();
      },
      onError: (err) => {
        // The backend ``detail`` is already user-safe; show it verbatim.
        addToast({
          type: 'error',
          title: t('modules.pack_install_failed', { defaultValue: 'Install failed' }),
          message: err instanceof Error ? err.message : String(err),
        });
      },
    });
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    handleFile(e.target.files?.[0]);
    // Reset so picking the same file again re-fires change.
    e.target.value = '';
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    if (busy) return;
    handleFile(e.dataTransfer.files?.[0]);
  }

  function handleRescan() {
    rescan.mutate(undefined, {
      onSuccess: (res) => {
        addToast({
          type: 'success',
          title: t('modules.pack_rescan_ok', { defaultValue: 'Rescan complete' }),
          message: t('modules.pack_rescan_count', {
            defaultValue: 'Found {{count}} packs.',
            count: res.count,
          }),
        });
        onChanged();
      },
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('modules.pack_rescan_failed', { defaultValue: 'Rescan failed' }),
          message: err instanceof Error ? err.message : String(err),
        });
      },
    });
  }

  return (
    <Card className="mb-6 animate-card-in" padding="md" style={{ animationDelay: '40ms' }}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        {/* Dropzone + file picker */}
        <div className="min-w-0 flex-1">
          <div
            role="button"
            tabIndex={busy ? -1 : 0}
            aria-label={t('modules.pack_install_dropzone_label', {
              defaultValue: 'Upload a pack .zip - click to choose a file or drop one here',
            })}
            aria-describedby={dropDescId}
            aria-disabled={busy}
            onClick={() => {
              if (!busy) fileInputRef.current?.click();
            }}
            onKeyDown={(e) => {
              if (busy) return;
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            className={clsx(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
              isDragging
                ? 'border-oe-blue bg-oe-blue/5'
                : 'border-border hover:border-oe-blue/50 hover:bg-surface-secondary/40',
              busy && 'cursor-not-allowed opacity-60',
            )}
          >
            {install.isPending ? (
              <Loader2 size={22} className="animate-spin text-oe-blue" />
            ) : (
              <UploadCloud size={22} className="text-content-tertiary" />
            )}
            <div>
              <p className="text-sm font-medium text-content-primary">
                {install.isPending
                  ? t('modules.pack_install_uploading', { defaultValue: 'Installing pack…' })
                  : t('modules.pack_install_cta', { defaultValue: 'Install a pack' })}
              </p>
              <p id={dropDescId} className="mt-0.5 text-xs text-content-tertiary">
                {t('modules.pack_install_hint', {
                  defaultValue: 'Click to choose a .zip, or drop one here. Max 25 MB. The pack is not activated until you Apply it.',
                })}
              </p>
            </div>
            {/* Hidden native input — the dropzone proxies clicks to it. */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip,application/x-zip-compressed"
              className="sr-only"
              aria-label={t('modules.pack_install_input_label', {
                defaultValue: 'Pack .zip file',
              })}
              disabled={busy}
              onChange={onInputChange}
            />
          </div>
        </div>

        {/* Rescan + drop-folder helper */}
        <div className="flex shrink-0 flex-col gap-2 sm:w-64">
          <Button
            variant="secondary"
            size="md"
            disabled={busy}
            icon={
              rescan.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )
            }
            onClick={handleRescan}
          >
            {rescan.isPending
              ? t('modules.pack_rescanning', { defaultValue: 'Rescanning…' })
              : t('modules.pack_rescan', { defaultValue: 'Rescan packs' })}
          </Button>
          <p className="flex items-start gap-1.5 text-2xs text-content-tertiary leading-relaxed">
            <FileArchive size={12} className="mt-0.5 shrink-0" />
            <span>
              {t('modules.pack_rescan_helper', {
                defaultValue:
                  'You can also drop a pack folder or .zip into your data dir under packs/ (next to the database), then click Rescan.',
              })}
            </span>
          </p>
        </div>
      </div>
    </Card>
  );
}
