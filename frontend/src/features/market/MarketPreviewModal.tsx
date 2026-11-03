// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Impact preview before a market is added or removed: what will appear, what
 * will disappear and what stays. Reuses the pack focus preview and module list.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { FocusModuleList } from '@/features/solution_packages/FocusModuleList';
import { PackFocusPreview } from '@/features/solution_packages/PackFocusPreview';
import { previewMarketProfile, type MarketProfile, type MarketScope } from './api';
import { diffHidden } from './logic';

export function MarketPreviewModal({
  open,
  current,
  next,
  title,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  open: boolean;
  current: MarketScope;
  next: MarketProfile;
  title: string;
  confirmLabel: string;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['market-scope', 'preview', next],
    queryFn: () => previewMarketProfile(next),
    enabled: open,
  });
  const diff = data ? diffHidden(current.hidden_modules ?? [], data.hidden_modules ?? [], Object.keys(data.module_markets ?? {})) : null;
  const newPack = data?.packs?.find((slug) => !(current.packs ?? []).includes(slug));
  const suggested = data?.suggested_packages?.[0];

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      busy={busy}
      testId="market-preview-modal"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={busy || isLoading}
            data-testid="market-preview-confirm"
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      }
    >
      {isLoading || !diff ? (
        <div className="h-40 animate-pulse rounded-xl bg-surface-secondary" aria-busy="true" />
      ) : (
        <div className="space-y-4">
          {suggested && (
            <p className="text-sm text-content-secondary" data-testid="market-preview-suggested">
              {t(`packages.${suggested}.name`, { defaultValue: suggested.replace(/_/g, ' ') })}
            </p>
          )}
          {newPack && <PackFocusPreview slug={newPack} focus={false} onFocusChange={() => undefined} canChoose={false} />}
          <div className="grid gap-4 sm:grid-cols-3" aria-live="polite">
            {/* Removing a market leads with what disappears. */}
            {[
              ...(diff.disappear.length > diff.appear.length
                ? [['disappear', diff.disappear] as const, ['appear', diff.appear] as const]
                : [['appear', diff.appear] as const, ['disappear', diff.disappear] as const]),
            ].map(([kind, list]) => (
              <div key={kind}>
                <p className="mb-2 text-xs font-semibold text-content-secondary">
                  {kind === 'appear'
                    ? t('market.preview_appear', { defaultValue: 'Will appear ({{count}})', count: list.length })
                    : t('market.preview_disappear', { defaultValue: 'Will disappear ({{count}})', count: list.length })}
                </p>
                <FocusModuleList modules={list} testId={`market-preview-${kind}`} />
              </div>
            ))}
            <p className="text-xs font-semibold text-content-secondary">
              {t('market.preview_unchanged', { defaultValue: 'Unchanged ({{count}})', count: diff.unchanged })}
            </p>
          </div>
          <p className="text-xs text-content-tertiary">
            {t('market.data_safe', { defaultValue: 'Your data is never deleted; hidden modules can be shown again.' })}
          </p>
        </div>
      )}
    </WideModal>
  );
}
