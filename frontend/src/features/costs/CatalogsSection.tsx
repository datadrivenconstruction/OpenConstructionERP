// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CatalogsSection - "My catalogs" management bar on the Cost Database page.
//
// A catalog is the user's own named price book with a REQUIRED currency.
// This bar lists the catalogs as selectable chips (name · currency · item
// count); selecting one filters the items list below via the backend's
// `catalog_id` query param (mirrors how the region tabs filter by region).
// Per-catalog actions: edit (rename / description / currency), export to
// Excel, delete (with an explicit keep-items vs delete-items choice).

import { useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookOpen,
  Download,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { extractErrorMessageFromBody, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { COMMON_CURRENCIES } from '@/features/boq/boqHelpers';
import {
  createCostCatalog,
  deleteCostCatalog,
  fetchCostCatalogs,
  updateCostCatalog,
  type CatalogDeleteMode,
  type CostCatalog,
} from './api';

/* ── Export helper ─────────────────────────────────────────────────────── */

async function downloadCatalogExcel(catalog: CostCatalog): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `/api/v1/costs/catalogs/${catalog.id}/export-excel/`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const utf8Name = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  // A malformed filename* (bad percent-encoding) must not turn a successful
  // download into an error toast - fall back to the plain filename match.
  let decodedName: string | undefined;
  try {
    decodedName = utf8Name ? decodeURIComponent(utf8Name) : undefined;
  } catch {
    decodedName = undefined;
  }
  const filename =
    decodedName ||
    disposition?.match(/filename="?([^";]+)"?/)?.[1] ||
    `${catalog.name}.xlsx`;
  triggerDownload(blob, filename);
}

/* ── Create / Edit dialog ──────────────────────────────────────────────── */

function CatalogFormDialog({
  catalog,
  onClose,
  onSaved,
}: {
  /** `null` = create mode; a catalog = edit mode. */
  catalog: CostCatalog | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = catalog !== null;

  const [name, setName] = useState(catalog?.name ?? '');
  const [currency, setCurrency] = useState(catalog?.currency ?? '');
  const [description, setDescription] = useState(catalog?.description ?? '');

  // Editing the currency of a non-empty catalog is rejected server-side
  // (409) because the stored rates are denominated in the old currency.
  // Disable the select up front and explain why instead of letting the
  // user hit the error.
  const currencyLocked = isEdit && (catalog?.item_count ?? 0) > 0;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (isEdit) {
        const body: { name?: string; description?: string | null; currency?: string } = {
          name: name.trim(),
          description: description.trim() || null,
        };
        // Only send currency when it actually changed - sending the same
        // code is harmless, but sending a changed one on a non-empty
        // catalog 409s, which the locked select already prevents.
        if (!currencyLocked && currency && currency !== catalog!.currency) {
          body.currency = currency;
        }
        return updateCostCatalog(catalog!.id, body);
      }
      return createCostCatalog({
        name: name.trim(),
        currency,
        description: description.trim() || null,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: isEdit
          ? t('costs_catalogs.updated', { defaultValue: 'Catalog updated' })
          : t('costs_catalogs.created', { defaultValue: 'Catalog created' }),
      });
      onSaved();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: isEdit
          ? t('costs_catalogs.update_failed', { defaultValue: 'Failed to update catalog' })
          : t('costs_catalogs.create_failed', { defaultValue: 'Failed to create catalog' }),
        message: err.message,
      });
    },
  });

  const canSave = name.trim().length > 0 && currency.length === 3 && !saveMutation.isPending;

  // Escape closes the dialog - but never while a save is in flight, so the
  // pending request cannot be silently abandoned mid-spinner.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saveMutation.isPending) onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, saveMutation.isPending]);

  // Enter in any text input submits the form when it is valid (selects and
  // buttons keep their native Enter behaviour).
  const handleEnterSave = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' || !canSave) return;
    if (!(e.target instanceof HTMLElement) || e.target.tagName !== 'INPUT') return;
    e.preventDefault();
    saveMutation.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="catalog-form-dialog-title"
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleEnterSave}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 id="catalog-form-dialog-title" className="text-base font-semibold text-content-primary">
              {isEdit
                ? t('costs_catalogs.edit_title', { defaultValue: 'Edit catalog' })
                : t('costs_catalogs.create_title', { defaultValue: 'Create catalog' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('costs_catalogs.create_desc', {
                defaultValue: 'A catalog groups your own cost items under one required currency.',
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('costs_catalogs.name_label', { defaultValue: 'Name' })} *
            </label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('costs_catalogs.name_placeholder', { defaultValue: 'e.g. My price book 2026' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('costs_catalogs.currency_label', { defaultValue: 'Currency' })} *
            </label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              disabled={currencyLocked}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <option value="">
                {t('costs_catalogs.import_currency_select', { defaultValue: 'Select currency...' })}
              </option>
              {COMMON_CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <p className="text-2xs text-content-tertiary mt-1">
              {currencyLocked
                ? t('costs_catalogs.currency_locked_hint', {
                    defaultValue:
                      'This catalog has {{count}} items. Changing the currency would relabel their rates, so it stays locked while items exist.',
                    count: catalog?.item_count ?? 0,
                  })
                : t('costs_catalogs.currency_hint', {
                    defaultValue: 'Items without their own currency inherit this code.',
                  })}
            </p>
          </div>

          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('costs_catalogs.description_label', { defaultValue: 'Description (optional)' })}
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('costs_catalogs.description_placeholder', { defaultValue: 'What this catalog contains' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-border-light bg-surface-secondary/30">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSave}
            icon={saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : undefined}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending
              ? isEdit
                ? t('costs_catalogs.saving', { defaultValue: 'Saving...' })
                : t('costs_catalogs.creating', { defaultValue: 'Creating...' })
              : isEdit
                ? t('costs_catalogs.save', { defaultValue: 'Save changes' })
                : t('costs_catalogs.create', { defaultValue: 'Create catalog' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Delete dialog (keep items vs delete items) ────────────────────────── */

function DeleteCatalogDialog({
  catalog,
  onClose,
  onDeleted,
}: {
  catalog: CostCatalog;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [mode, setMode] = useState<CatalogDeleteMode>('keep_items');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const deleteMutation = useMutation({
    mutationFn: () => deleteCostCatalog(catalog.id, mode),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('costs_catalogs.deleted', { defaultValue: 'Catalog deleted' }),
        message:
          mode === 'keep_items'
            ? t('costs_catalogs.deleted_kept_items', {
                defaultValue: '{{count}} items kept in the cost database',
                count: data.items_affected,
              })
            : t('costs_catalogs.deleted_with_items', {
                defaultValue: '{{count}} items deleted with the catalog',
                count: data.items_affected,
              }),
      });
      onDeleted();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs_catalogs.delete_failed', { defaultValue: 'Failed to delete catalog' }),
        message: err.message,
      });
    },
  });

  const optionClass = (active: boolean) =>
    `flex items-start gap-2.5 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
      active
        ? 'border-oe-blue/50 bg-oe-blue-subtle/15'
        : 'border-border-light hover:bg-surface-secondary/50'
    }`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-catalog-dialog-title"
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 id="delete-catalog-dialog-title" className="text-base font-semibold text-content-primary">
              {t('costs_catalogs.delete_title', { defaultValue: 'Delete catalog' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('costs_catalogs.delete_question', {
                defaultValue: 'Delete "{{name}}"? Choose what happens to its items.',
                name: catalog.name,
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-2.5">
          <label className={optionClass(mode === 'keep_items')}>
            <input
              type="radio"
              name="catalog-delete-mode"
              checked={mode === 'keep_items'}
              onChange={() => setMode('keep_items')}
              className="mt-0.5 accent-[var(--oe-blue,#2563eb)]"
            />
            <span>
              <span className="block text-sm font-medium text-content-primary">
                {t('costs_catalogs.delete_keep_items', { defaultValue: 'Keep the items' })}
              </span>
              <span className="block text-xs text-content-tertiary mt-0.5">
                {t('costs_catalogs.delete_keep_items_hint', {
                  defaultValue:
                    'Only the catalog is removed. Its {{count}} items stay in the cost database without a catalog.',
                  count: catalog.item_count,
                })}
              </span>
            </span>
          </label>

          <label className={optionClass(mode === 'delete_items')}>
            <input
              type="radio"
              name="catalog-delete-mode"
              checked={mode === 'delete_items'}
              onChange={() => setMode('delete_items')}
              className="mt-0.5 accent-[var(--oe-blue,#2563eb)]"
            />
            <span>
              <span className="block text-sm font-medium text-content-primary">
                {t('costs_catalogs.delete_delete_items', { defaultValue: 'Delete the items too' })}
              </span>
              <span className="block text-xs text-content-tertiary mt-0.5">
                {t('costs_catalogs.delete_delete_items_hint', {
                  defaultValue:
                    'The catalog and all {{count}} items in it are removed from the cost database.',
                  count: catalog.item_count,
                })}
              </span>
            </span>
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-border-light bg-surface-secondary/30">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={deleteMutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="danger"
            size="sm"
            icon={deleteMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending
              ? t('costs_catalogs.deleting', { defaultValue: 'Deleting...' })
              : t('costs_catalogs.delete', { defaultValue: 'Delete' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Section ───────────────────────────────────────────────────────────── */

export function CatalogsSection({
  selectedId,
  onSelect,
}: {
  /** Currently selected catalog id ('' = no catalog filter). */
  selectedId: string;
  /** Select a catalog to filter the items list ('' clears the filter). */
  onSelect: (catalogId: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [showCreate, setShowCreate] = useState(false);
  const [editCatalog, setEditCatalog] = useState<CostCatalog | null>(null);
  const [deleteCatalog, setDeleteCatalog] = useState<CostCatalog | null>(null);
  // Per-catalog in-flight export ids. A single "exportingId" slot raced:
  // export A then B, and A settling killed B's spinner while B still ran.
  const [exportingIds, setExportingIds] = useState<Set<string>>(new Set());

  const { data: catalogs } = useQuery({
    queryKey: ['costs', 'catalogs'],
    queryFn: fetchCostCatalogs,
    retry: false,
    staleTime: 60_000,
  });

  const sorted = useMemo(
    () => [...(catalogs ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [catalogs],
  );

  // If the selected catalog disappears (deleted elsewhere), clear the filter.
  useEffect(() => {
    if (selectedId && catalogs && !catalogs.some((c) => c.id === selectedId)) {
      onSelect('');
    }
  }, [selectedId, catalogs, onSelect]);

  const exportMutation = useMutation({
    mutationFn: (catalog: CostCatalog) => downloadCatalogExcel(catalog),
    onMutate: (catalog) => {
      setExportingIds((prev) => {
        const next = new Set(prev);
        next.add(catalog.id);
        return next;
      });
    },
    onSettled: (_data, _err, catalog) => {
      setExportingIds((prev) => {
        const next = new Set(prev);
        next.delete(catalog.id);
        return next;
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('costs.export_success', { defaultValue: 'Export complete' }),
        message: t('costs.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.export_failed', { defaultValue: 'Export failed' }),
        message: err.message,
      });
    },
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['costs'] });
  };

  return (
    <div className="mb-4" data-testid="costs-catalogs-section">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-content-secondary mr-1">
          <BookOpen size={14} className="text-oe-blue" />
          {t('costs_catalogs.title', { defaultValue: 'My catalogs' })}
        </span>

        {sorted.length === 0 && (
          <span className="text-xs text-content-tertiary">
            {t('costs_catalogs.empty_hint', {
              defaultValue: 'No catalogs yet. Create one to group your own rates, or import a file into a new catalog.',
            })}
          </span>
        )}

        {sorted.map((catalog) => {
          const isActive = selectedId === catalog.id;
          const isExporting = exportingIds.has(catalog.id);
          return (
            <div
              key={catalog.id}
              className={`group inline-flex items-center gap-1 rounded-lg border pl-2.5 pr-1 py-1 transition-colors ${
                isActive
                  ? 'border-oe-blue/50 bg-oe-blue-subtle/20'
                  : 'border-border-light bg-surface-elevated hover:bg-surface-secondary'
              }`}
            >
              <button
                onClick={() => onSelect(isActive ? '' : catalog.id)}
                title={catalog.description || catalog.name}
                className="inline-flex items-center gap-1.5 text-sm"
              >
                <span className={`font-medium ${isActive ? 'text-oe-blue-text' : 'text-content-primary'}`}>
                  {catalog.name}
                </span>
                <Badge variant={isActive ? 'blue' : 'neutral'} size="sm" className="text-2xs">
                  {catalog.currency}
                </Badge>
                <span className="text-2xs tabular-nums text-content-tertiary">
                  {t('costs_catalogs.items_count', {
                    defaultValue: '{{count}} items',
                    count: catalog.item_count,
                  })}
                </span>
              </button>

              {/* Per-catalog actions - visible on hover / when active */}
              <span
                className={`inline-flex items-center transition-opacity ${
                  isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                }`}
              >
                <button
                  onClick={() => setEditCatalog(catalog)}
                  title={t('costs_catalogs.edit', { defaultValue: 'Edit catalog' })}
                  aria-label={t('costs_catalogs.edit', { defaultValue: 'Edit catalog' })}
                  className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary transition-colors"
                >
                  <Pencil size={12} />
                </button>
                <button
                  onClick={() => exportMutation.mutate(catalog)}
                  disabled={isExporting}
                  title={t('costs_catalogs.export_excel', { defaultValue: 'Export to Excel' })}
                  aria-label={t('costs_catalogs.export_excel', { defaultValue: 'Export to Excel' })}
                  className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary transition-colors"
                >
                  {isExporting ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Download size={12} />
                  )}
                </button>
                <button
                  onClick={() => setDeleteCatalog(catalog)}
                  title={t('costs_catalogs.delete', { defaultValue: 'Delete' })}
                  aria-label={t('costs_catalogs.delete', { defaultValue: 'Delete' })}
                  className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error transition-colors"
                >
                  <Trash2 size={12} />
                </button>
              </span>
            </div>
          );
        })}

        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1 rounded-lg border border-dashed border-border px-2.5 py-1.5 text-xs font-medium text-content-tertiary hover:text-oe-blue-text hover:border-oe-blue/40 hover:bg-oe-blue-subtle/10 transition-colors"
        >
          <Plus size={13} />
          {t('costs_catalogs.new_catalog', { defaultValue: 'New catalog' })}
        </button>
      </div>

      {showCreate && (
        <CatalogFormDialog
          catalog={null}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            invalidate();
          }}
        />
      )}

      {editCatalog && (
        <CatalogFormDialog
          catalog={editCatalog}
          onClose={() => setEditCatalog(null)}
          onSaved={() => {
            setEditCatalog(null);
            invalidate();
          }}
        />
      )}

      {deleteCatalog && (
        <DeleteCatalogDialog
          catalog={deleteCatalog}
          onClose={() => setDeleteCatalog(null)}
          onDeleted={() => {
            if (selectedId === deleteCatalog.id) onSelect('');
            setDeleteCatalog(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
