// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tab-strip BIM model picker. One pill per model in the project, plus
// a ghost "+ Upload" tab that links to /bim. Reused by /match-elements,
// /quantities, and the BIM viewer page.

import clsx from 'clsx';
import { Box, Plus, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

export interface BIMModelOption {
  id: string;
  name: string;
  model_format: string | null;
  element_count: number;
  storey_count: number;
  status: string;
  created_at: string | null;
}

export interface BIMModelPickerProps {
  models: BIMModelOption[];
  activeModelId: string | null;
  onSelect: (modelId: string) => void;
  uploadHref?: string;
  isLoading?: boolean;
  emptyMessage?: string;
  className?: string;
}

function statusIcon(status: string) {
  if (status === 'ready') return <CheckCircle2 className="w-3 h-3 text-emerald-500" />;
  if (status === 'processing' || status === 'pending')
    return <Loader2 className="w-3 h-3 animate-spin text-content-tertiary" />;
  if (status === 'failed' || status === 'error')
    return <AlertTriangle className="w-3 h-3 text-rose-500" />;
  return <Box className="w-3 h-3 text-content-tertiary" />;
}

export function BIMModelPicker({
  models,
  activeModelId,
  onSelect,
  uploadHref = '/bim',
  isLoading,
  emptyMessage,
  className,
}: BIMModelPickerProps) {
  const { t } = useTranslation();

  if (isLoading && models.length === 0) {
    return (
      <div
        className={clsx(
          'flex items-center gap-2 text-sm text-content-tertiary py-2',
          className,
        )}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('bim.loading_models', { defaultValue: 'Loading BIM models…' })}
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <div className={clsx('flex items-center gap-3 py-2', className)}>
        <span className="text-sm text-content-tertiary">
          {emptyMessage ??
            t('bim.no_models_in_project', {
              defaultValue: 'No BIM models in this project yet.',
            })}
        </span>
        <Link
          to={uploadHref}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-oe-blue/40 text-oe-blue text-xs hover:bg-oe-blue/5"
        >
          <Plus className="w-3.5 h-3.5" />
          {t('bim.upload_model', { defaultValue: 'Upload BIM model' })}
        </Link>
      </div>
    );
  }

  return (
    <div className={clsx('flex flex-wrap items-center gap-1.5', className)}>
      {models.map((m) => {
        const isActive = m.id === activeModelId;
        const isReady = m.status === 'ready';
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => isReady && onSelect(m.id)}
            disabled={!isReady}
            title={
              !isReady
                ? t('bim.model_not_ready', {
                    defaultValue: 'Model not ready yet ({{status}})',
                    status: m.status,
                  })
                : `${m.name} · ${m.element_count} elements · ${m.storey_count} storeys`
            }
            className={clsx(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition max-w-[32ch]',
              isActive
                ? 'border-oe-blue bg-oe-blue/5 text-content-primary shadow-sm'
                : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue/40',
              !isReady && 'opacity-60 cursor-not-allowed',
            )}
          >
            {statusIcon(m.status)}
            <span className="truncate font-medium">{m.name}</span>
            <span className="text-xs opacity-60 tabular-nums shrink-0">
              {m.element_count}
            </span>
            {m.model_format && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-tertiary text-content-tertiary uppercase shrink-0 font-medium">
                {m.model_format}
              </span>
            )}
          </button>
        );
      })}
      <Link
        to={uploadHref}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-content-tertiary hover:border-oe-blue/40 hover:text-oe-blue"
      >
        <Plus className="w-3.5 h-3.5" />
        {t('bim.upload_short', { defaultValue: 'Upload' })}
      </Link>
    </div>
  );
}
