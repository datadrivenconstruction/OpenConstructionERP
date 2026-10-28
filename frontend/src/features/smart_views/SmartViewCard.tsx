// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SmartViewCard — single view shown inside the SmartViewsPanel list.
//
// Click anywhere on the card body to "Apply" the view; the 3-dot menu
// holds Edit / Duplicate / Delete. The "Applied" state is driven by the
// parent panel via the ``applied`` prop, so the orange ring + chip stay
// in lockstep with the actual scene paint.

import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, CheckCircle2, Layers } from 'lucide-react';
import clsx from 'clsx';
import { Badge } from '@/shared/ui';
import type { SmartViewResponse } from './types';

export interface SmartViewCardProps {
  view: SmartViewResponse;
  applied: boolean;
  onApply: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  /** Optional Share entry on the 3-dot menu. Renders only when set so
   *  callers that do not yet wire share (legacy contexts, BIM-less
   *  contexts) get the original card unchanged. */
  onShare?: () => void;
}

export function SmartViewCard({
  view,
  applied,
  onApply,
  onEdit,
  onDuplicate,
  onDelete,
  onShare,
}: SmartViewCardProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  // Close the menu when clicking outside.
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (!cardRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  const scopeLabel = (() => {
    switch (view.scope_type) {
      case 'project':
        return t('smartViews.scope_chip_project', { defaultValue: 'Project' });
      case 'federation':
        return t('smartViews.scope_chip_federation', { defaultValue: 'Federation' });
      case 'user':
      default:
        return t('smartViews.scope_chip_user', { defaultValue: 'My' });
    }
  })();

  return (
    <div
      ref={cardRef}
      className={clsx(
        'group relative rounded-xl border bg-surface-elevated p-3 cursor-pointer',
        'transition-colors',
        applied
          ? 'border-oe-blue ring-2 ring-oe-blue/30 bg-oe-blue/5'
          : 'border-border-light hover:border-border',
      )}
      data-testid={`smart-view-card-${view.id}`}
      data-applied={applied ? '1' : '0'}
      onClick={(e) => {
        // Don't apply when the menu / its trigger was clicked.
        const target = e.target as HTMLElement;
        if (target.closest('[data-smart-view-menu]')) return;
        onApply();
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onApply();
        }
      }}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4
              className="text-sm font-semibold text-content-primary truncate"
              title={view.name}
            >
              {view.name}
            </h4>
            {applied && (
              <span
                className="inline-flex items-center gap-1 text-xs text-oe-blue"
                data-testid={`smart-view-card-applied-${view.id}`}
              >
                <CheckCircle2 size={12} />
                {t('smartViews.applied', { defaultValue: 'Applied' })}
              </span>
            )}
          </div>
          {view.description && (
            <p
              className="mt-1 text-xs text-content-tertiary line-clamp-2"
              title={view.description}
            >
              {view.description}
            </p>
          )}
          <div className="mt-2 flex items-center gap-2 text-xs text-content-tertiary">
            <Badge variant="neutral" size="sm">
              <Layers size={10} />
              {t('smartViews.rule_count', {
                defaultValue: '{{count}} rules',
                count: view.rules.length,
              })}
            </Badge>
            <Badge variant="blue" size="sm">
              {scopeLabel}
            </Badge>
          </div>
        </div>

        <div className="relative" data-smart-view-menu="1">
          <button
            type="button"
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label={t('smartViews.menu', { defaultValue: 'More actions' })}
            data-testid={`smart-view-card-menu-${view.id}`}
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div
              className="absolute end-0 top-full z-20 mt-1 min-w-[140px] rounded-lg border border-border-light bg-surface-elevated py-1 shadow-lg"
              role="menu"
            >
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-start text-sm hover:bg-surface-secondary"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen(false);
                  onEdit();
                }}
                data-testid={`smart-view-card-edit-${view.id}`}
              >
                {t('smartViews.edit', { defaultValue: 'Edit' })}
              </button>
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-start text-sm hover:bg-surface-secondary"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen(false);
                  onDuplicate();
                }}
                data-testid={`smart-view-card-duplicate-${view.id}`}
              >
                {t('smartViews.duplicate', { defaultValue: 'Duplicate' })}
              </button>
              {onShare && (
                <button
                  type="button"
                  className="block w-full px-3 py-1.5 text-start text-sm hover:bg-surface-secondary"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuOpen(false);
                    onShare();
                  }}
                  data-testid={`smart-view-card-share-${view.id}`}
                >
                  {t('smartViews.share_link', {
                    defaultValue: 'Share link',
                  })}
                </button>
              )}
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-start text-sm text-semantic-error hover:bg-semantic-error-bg/40"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen(false);
                  onDelete();
                }}
                data-testid={`smart-view-card-delete-${view.id}`}
              >
                {t('smartViews.delete', { defaultValue: 'Delete' })}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SmartViewCard;
