// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SmartViewPresetsTab — out-of-box preset catalogue.
//
// Renders the 6 built-in presets as install cards. Click "Install" →
// POST /smart-views/presets/{id}/install → toast + refetch the user's
// view list under the active scope.
//
// Counter-intuitive design: the preset list is fetched from the backend
// (not bundled in the JS) so a server-side preset tweak ships instantly
// without a frontend release. The payload is tiny (6 entries × ~6 keys)
// and React-Query caches it, so the perf hit is a one-time ~1 KB.

import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Sparkles, Layers, Plus } from 'lucide-react';
import { Button, Badge, Skeleton } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { installSmartViewPreset, listSmartViewPresets } from './api';
import type { SmartViewPresetSummary, SmartViewScopeType } from './types';

export interface SmartViewPresetsTabProps {
  /** Active scope target — same as the panel's other tabs. */
  scopeType: SmartViewScopeType;
  scopeId: string;
  /** Fired after a successful install so the parent panel can flip back
   *  to its list tab (the new card lives there). */
  onInstalled?: () => void;
}

export function SmartViewPresetsTab({
  scopeType,
  scopeId,
  onInstalled,
}: SmartViewPresetsTabProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const listQuery = useQuery({
    queryKey: ['smart-view-presets'],
    queryFn: listSmartViewPresets,
    // The catalogue is static across users — long stale window is safe.
    staleTime: 5 * 60 * 1000,
  });

  const installMutation = useMutation({
    mutationFn: (presetId: string) =>
      installSmartViewPreset(presetId, { scope_type: scopeType, scope_id: scopeId }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['smart-views', scopeType, scopeId],
      });
      addToast({
        type: 'success',
        title: t('smartViews.preset_installed', {
          defaultValue: 'Preset installed',
        }),
      });
      onInstalled?.();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('smartViews.error_preset_install', {
          defaultValue: 'Could not install preset',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  /* ── Render ───────────────────────────────────────────────────────── */

  if (listQuery.isLoading) {
    return (
      <div
        className="grid grid-cols-1 gap-2 px-3 py-2"
        data-testid="smart-view-presets-loading"
      >
        <Skeleton height={72} />
        <Skeleton height={72} />
        <Skeleton height={72} />
      </div>
    );
  }

  if (listQuery.isError) {
    return (
      <div
        className="m-3 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/40 p-3 text-sm text-semantic-error"
        data-testid="smart-view-presets-error"
      >
        {t('smartViews.error_presets_load', {
          defaultValue: 'Could not load presets.',
        })}
      </div>
    );
  }

  const presets: SmartViewPresetSummary[] = listQuery.data ?? [];

  return (
    <div
      className="grid grid-cols-1 gap-2 px-3 py-2"
      data-testid="smart-view-presets"
    >
      {presets.map((p) => (
        <PresetCard
          key={p.preset_id}
          preset={p}
          installing={
            installMutation.isPending && installMutation.variables === p.preset_id
          }
          onInstall={() => installMutation.mutate(p.preset_id)}
        />
      ))}
    </div>
  );
}

interface PresetCardProps {
  preset: SmartViewPresetSummary;
  installing: boolean;
  onInstall: () => void;
}

function PresetCard({ preset, installing, onInstall }: PresetCardProps) {
  const { t } = useTranslation();
  return (
    <div
      className="rounded-xl border border-border-light bg-surface-elevated p-3 transition-colors hover:border-border"
      data-testid={`smart-view-preset-${preset.preset_id}`}
    >
      <div className="flex items-start gap-2">
        <div className="mt-0.5 text-oe-blue">
          <Sparkles size={14} />
        </div>
        <div className="flex-1 min-w-0">
          <h4
            className="text-sm font-semibold text-content-primary truncate"
            title={preset.name}
          >
            {preset.name}
          </h4>
          <p
            className="mt-1 text-xs text-content-tertiary line-clamp-2"
            title={preset.description}
          >
            {preset.description}
          </p>
          <div className="mt-2 flex items-center gap-2 text-xs text-content-tertiary">
            <Badge variant="neutral" size="sm">
              <Layers size={10} />
              {t('smartViews.rule_count', {
                defaultValue: '{{count}} rules',
                count: preset.rule_count,
              })}
            </Badge>
            <Badge variant="blue" size="sm">
              {preset.category}
            </Badge>
          </div>
        </div>
        <Button
          size="sm"
          variant="primary"
          icon={<Plus size={12} />}
          onClick={onInstall}
          loading={installing}
          data-testid={`smart-view-preset-install-${preset.preset_id}`}
        >
          {t('smartViews.install', { defaultValue: 'Install' })}
        </Button>
      </div>
    </div>
  );
}

export default SmartViewPresetsTab;
