/**
 * Floating asset-info card for the BIM viewer.
 *
 * Rendered only when exactly one element is selected. Shows the current
 * asset-info (manufacturer / model / serial / operational status) and
 * an "Edit" CTA that opens the shared ``AssetEditModal``.
 *
 * The card fetches the element's full row via the asset-list endpoint
 * filtered to a single id — cheap (indexed lookup) and reuses the same
 * payload shape as the Asset Register list. If the element is *not* yet
 * tracked (``is_tracked_asset=false``), the card shows a register CTA
 * instead of the populated fields.
 *
 * Anchored bottom-right of the viewer; ``rightPx`` is shifted left when
 * the right side panel is open so the card stays visible. Plain solid
 * background (no glassmorphism) so the asset fields read clearly over
 * 3D-viewer content.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Package, Edit3, X } from 'lucide-react';

import { AssetEditModal } from './AssetEditModal';
import { ensureBIMElement, listTrackedAssets, type AssetSummary } from './api';
import { useToastStore } from '@/stores/useToastStore';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface ElementAssetCardProps {
  projectId: string;
  elementId: string | null;
  /** The selected element's DB id or stable_id — needed to synth a summary
   *  for the modal when the element is still untracked. */
  element: {
    id: string;
    stable_id: string;
    name?: string | null;
    element_type?: string | null;
    model_id?: string;
    model_name?: string;
  } | null;
  /** Offset from the right edge, in px. Keeps the card clear of the right
   *  sidebar when it is open. */
  rightPx: number;
  /** Offset from the bottom edge, in px. Anchoring from the bottom places
   *  the card visually below the Saved-views panel in the right sidebar. */
  bottomPx: number;
  visible: boolean;
  /** Hide the card for the rest of the session. Wired to the toggle in the
   *  Tools tab via ``useBIMViewerStore.setAssetCardEnabled(false)``. */
  onDismiss?: () => void;
}

export default function ElementAssetCard({
  projectId,
  elementId,
  element,
  rightPx,
  bottomPx,
  visible,
  onDismiss,
}: ElementAssetCardProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState<AssetSummary | null>(null);
  const [resolving, setResolving] = useState(false);

  // Fetch the project's tracked assets and pick out this element. We
  // piggy-back on the list endpoint instead of adding a dedicated GET
  // so we don't fan out the API surface — the list is indexed and
  // cached by React Query (30 s staleTime matches AssetsPage).
  const assetsQuery = useQuery({
    queryKey: ['bim-assets', projectId],
    queryFn: () => listTrackedAssets(projectId),
    enabled: !!projectId && visible && !!elementId,
    staleTime: 30_000,
  });

  const tracked = useMemo(() => {
    if (!elementId) return null;
    return assetsQuery.data?.items.find((a) => a.id === elementId) ?? null;
  }, [assetsQuery.data, elementId]);

  if (!visible || !elementId || !element) return null;

  const handleEditClick = async () => {
    if (tracked) {
      setEditing(tracked);
      return;
    }
    // Element isn't registered yet. The viewer sometimes hands us a
    // client-side stub id (mesh with no oe_bim_element row). Resolve
    // it to a real DB UUID via ensureBIMElement before we let the
    // modal PATCH asset-info — otherwise the backend returns 404.
    let realId = element.id;
    if (!UUID_RE.test(element.id) && element.model_id) {
      setResolving(true);
      try {
        const resolved = await ensureBIMElement(element.model_id, {
          stableId: element.stable_id ?? null,
          meshRef: element.stable_id ?? null,
        });
        realId = resolved.id;
      } catch (err) {
        toast({
          type: 'error',
          title: t('assets.resolve_failed', {
            defaultValue: 'Could not prepare asset row',
          }),
          message: err instanceof Error ? err.message : undefined,
        });
        setResolving(false);
        return;
      }
      setResolving(false);
    }
    setEditing({
      id: realId,
      stable_id: element.stable_id,
      element_type: element.element_type ?? 'Element',
      name: element.name ?? null,
      model_id: element.model_id ?? '',
      model_name: element.model_name ?? '',
      project_id: projectId,
      asset_info: {},
    });
  };

  return (
    <>
      <div
        className="absolute z-30 select-none rounded-lg border border-border-light bg-surface-primary shadow-lg px-3 py-2 min-w-[220px] max-w-[280px] transition-[inset-inline-end] duration-200"
        style={{ insetInlineEnd: rightPx, bottom: bottomPx, backgroundColor: 'var(--oe-bg)' }}
        data-testid="bim-asset-card"
      >
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-1.5">
            <Package size={12} className="text-oe-blue shrink-0" />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
              {t('assets.card_title', { defaultValue: 'Asset info' })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleEditClick}
              disabled={resolving}
              className="inline-flex items-center gap-1 text-[10px] text-oe-blue hover:underline disabled:opacity-50"
              data-testid="bim-asset-edit"
            >
              <Edit3 size={10} />
              {resolving
                ? t('common.loading', { defaultValue: 'Loading…' })
                : tracked
                ? t('common.edit', { defaultValue: 'Edit' })
                : t('assets.register', { defaultValue: 'Register' })}
            </button>
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="rounded p-0.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                aria-label={t('assets.hide_card', { defaultValue: 'Hide asset card' })}
                title={t('assets.hide_card', { defaultValue: 'Hide asset card' })}
                data-testid="bim-asset-dismiss"
              >
                <X size={11} />
              </button>
            )}
          </div>
        </div>

        {tracked ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
            {tracked.asset_info.manufacturer && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.manufacturer', { defaultValue: 'Mfr.' })}
                </dt>
                <dd className="font-medium text-content-primary truncate" title={tracked.asset_info.manufacturer}>
                  {tracked.asset_info.manufacturer}
                </dd>
              </>
            )}
            {tracked.asset_info.model && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.model', { defaultValue: 'Model' })}
                </dt>
                <dd className="font-medium text-content-primary truncate" title={tracked.asset_info.model}>
                  {tracked.asset_info.model}
                </dd>
              </>
            )}
            {tracked.asset_info.serial_number && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.serial_short', { defaultValue: 'S/N' })}
                </dt>
                <dd className="font-mono text-[10px] text-content-primary truncate" title={tracked.asset_info.serial_number}>
                  {tracked.asset_info.serial_number}
                </dd>
              </>
            )}
            {tracked.asset_info.operational_status && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.status_short', { defaultValue: 'Status' })}
                </dt>
                <dd className="text-[11px] text-content-secondary">
                  {tracked.asset_info.operational_status.replace('_', ' ')}
                </dd>
              </>
            )}
            {tracked.asset_info.warranty_until && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.warranty_short', { defaultValue: 'Warranty' })}
                </dt>
                <dd className="text-[11px] text-content-secondary">
                  {tracked.asset_info.warranty_until}
                </dd>
              </>
            )}
          </dl>
        ) : (
          <p className="text-[11px] text-content-tertiary italic">
            {t('assets.not_tracked', {
              defaultValue: 'Not tracked yet — register to capture manufacturer, serial, warranty…',
            })}
          </p>
        )}
      </div>

      {editing && (
        <AssetEditModal
          asset={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
    </>
  );
}
