// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SmartViewShareModal — generate / copy / revoke share-by-link tokens.
//
// Two visual states:
//   • token absent  → primary "Generate share link" CTA
//   • token present → URL input + Copy + Revoke buttons
//
// The token is fetched lazily — the modal does NOT prefetch it on mount
// to avoid a write (rotate!) on someone just peeking at the modal. We
// rely on the parent passing ``initialShareToken`` from the view it
// already loaded (the view payload carries share_token for the author).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link2, Copy, Trash2, RefreshCw } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { copyToClipboard } from '@/shared/lib/browser';
import { useToastStore } from '@/stores/useToastStore';
import {
  buildSmartViewShareUrl,
  createSmartViewShareLink,
  revokeSmartViewShareLink,
} from './api';

export interface SmartViewShareModalProps {
  open: boolean;
  onClose: () => void;
  viewId: string;
  viewName: string;
  /** Existing token from the view payload (null when never shared). */
  initialShareToken: string | null;
  /** Fired after a successful create/revoke so the parent panel can
   *  refetch the view list (the row's share_token column changed). */
  onChanged?: (newToken: string | null) => void;
}

export function SmartViewShareModal({
  open,
  onClose,
  viewId,
  viewName,
  initialShareToken,
  onChanged,
}: SmartViewShareModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [token, setToken] = useState<string | null>(initialShareToken);
  const [pending, setPending] = useState<'create' | 'revoke' | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  // The URL shown to the user. ``buildSmartViewShareUrl`` reads
  // ``window.location.origin`` so it stays accurate across staging /
  // localhost / production without a config bump.
  const url = token ? buildSmartViewShareUrl(token) : '';

  async function handleGenerate(rotate = false): Promise<void> {
    setPending('create');
    try {
      const info = await createSmartViewShareLink(viewId);
      setToken(info.share_token);
      onChanged?.(info.share_token);
      addToast({
        type: 'success',
        title: rotate
          ? t('smartViews.share_rotated', {
              defaultValue: 'New share link generated',
            })
          : t('smartViews.share_generated', {
              defaultValue: 'Share link generated',
            }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('smartViews.error_share_create', {
          defaultValue: 'Could not generate share link',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPending(null);
    }
  }

  async function handleCopy(): Promise<void> {
    if (!url) return;
    try {
      await copyToClipboard(url);
      addToast({
        type: 'success',
        title: t('smartViews.share_copied', {
          defaultValue: 'Link copied to clipboard',
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('smartViews.error_share_copy', {
          defaultValue: 'Copy failed',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  async function handleRevoke(): Promise<void> {
    setPending('revoke');
    try {
      await revokeSmartViewShareLink(viewId);
      setToken(null);
      setConfirmRevoke(false);
      onChanged?.(null);
      addToast({
        type: 'success',
        title: t('smartViews.share_revoked_toast', {
          defaultValue: 'Share link revoked',
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('smartViews.error_share_revoke', {
          defaultValue: 'Could not revoke link',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPending(null);
    }
  }

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('smartViews.share_link', { defaultValue: 'Share link' })}
      subtitle={viewName}
      size="md"
      busy={pending !== null}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={pending !== null}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-testid="smart-view-share-modal">
        {token === null ? (
          // ── State A: not shared yet ─────────────────────────────────
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm text-content-secondary">
              {t('smartViews.share_blurb', {
                defaultValue:
                  'Anyone with the link can view this Smart View read-only. You can revoke the link at any time.',
              })}
            </p>
            <Button
              variant="primary"
              icon={<Link2 size={14} />}
              loading={pending === 'create'}
              onClick={() => handleGenerate(false)}
              data-testid="smart-view-share-generate"
            >
              {t('smartViews.generate_share', {
                defaultValue: 'Generate share link',
              })}
            </Button>
          </div>
        ) : (
          // ── State B: shared ─────────────────────────────────────────
          <div className="flex flex-col gap-3">
            <label
              htmlFor="smart-view-share-url"
              className="text-xs font-medium text-content-secondary"
            >
              {t('smartViews.share_url_label', {
                defaultValue: 'Shareable URL',
              })}
            </label>
            <div className="flex items-center gap-2">
              <input
                id="smart-view-share-url"
                type="text"
                readOnly
                value={url}
                className="flex-1 h-9 rounded-lg border border-border bg-surface-secondary px-3 font-mono text-xs text-content-primary"
                onFocus={(e) => e.currentTarget.select()}
                data-testid="smart-view-share-url"
              />
              <Button
                variant="secondary"
                size="sm"
                icon={<Copy size={14} />}
                onClick={handleCopy}
                data-testid="smart-view-share-copy"
              >
                {t('smartViews.copy', { defaultValue: 'Copy' })}
              </Button>
            </div>
            <div className="flex items-center justify-between gap-2 pt-1">
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw size={12} />}
                loading={pending === 'create'}
                onClick={() => handleGenerate(true)}
                data-testid="smart-view-share-rotate"
              >
                {t('smartViews.share_rotate', {
                  defaultValue: 'Rotate',
                })}
              </Button>
              {!confirmRevoke ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={12} />}
                  onClick={() => setConfirmRevoke(true)}
                  data-testid="smart-view-share-revoke"
                >
                  {t('smartViews.revoke', { defaultValue: 'Revoke' })}
                </Button>
              ) : (
                <div
                  className="flex items-center gap-2"
                  data-testid="smart-view-share-revoke-confirm"
                >
                  <span className="text-xs text-content-tertiary">
                    {t('smartViews.share_revoke_confirm', {
                      defaultValue: 'Revoke this link?',
                    })}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setConfirmRevoke(false)}
                    disabled={pending !== null}
                  >
                    {t('smartViews.cancel', { defaultValue: 'Cancel' })}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    icon={<Trash2 size={12} />}
                    loading={pending === 'revoke'}
                    onClick={handleRevoke}
                    data-testid="smart-view-share-revoke-confirm-button"
                  >
                    {t('smartViews.revoke', { defaultValue: 'Revoke' })}
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </WideModal>
  );
}

export default SmartViewShareModal;
