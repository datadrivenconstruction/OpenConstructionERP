// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Price lists tab: a vendor's price lists with list price, discount and net
 * price per item, the import wizard (Excel / CSV / SAP export, preview first)
 * and the contractor's discount agreements with that vendor.
 *
 * Reading order on screen is the estimator's question: "what do I pay?" The
 * net price is the bold column; list price and discount explain it.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertOctagon,
  ExternalLink,
  FileSpreadsheet,
  Paperclip,
  Percent,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';
import { Badge, Button, EmptyState, SkeletonTable } from '@/shared/ui';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { downloadDocumentBlob, uploadDocument } from '@/features/documents/api';
import { projectsApi } from '@/features/projects/api';
import {
  addItemAttachment,
  commitPriceListImport,
  createVendorDiscount,
  deleteItemAttachment,
  deleteVendorDiscount,
  isSafeProductUrl,
  listCatalogItems,
  listItemAttachments,
  listPriceListEntries,
  listVendorDiscounts,
  listVendorPriceLists,
  previewPriceListImport,
  type CreateDiscountPayload,
  type DiscountAgreement,
  type DiscountSource,
  type ImportAction,
  type ImportField,
  type ImportPreview,
  type ItemAttachment,
  type PriceList,
  type Vendor,
} from './api';
import { apiGet } from '@/shared/lib/api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type TFn = (k: string, opts?: Record<string, unknown>) => string;

function sourceLabel(t: TFn, s: DiscountSource): string {
  switch (s) {
    case 'item_fixed':
      return t('supplier_catalogs.source_item_fixed', { defaultValue: 'Fixed net price' });
    case 'item':
      return t('supplier_catalogs.source_item', { defaultValue: 'Item discount' });
    case 'category':
      return t('supplier_catalogs.source_category', { defaultValue: 'Category discount' });
    case 'overall':
      return t('supplier_catalogs.source_overall', { defaultValue: 'Overall discount' });
    case 'manual':
      return t('supplier_catalogs.source_manual', { defaultValue: 'Agreed by hand' });
    default:
      return t('supplier_catalogs.source_none', { defaultValue: 'No discount' });
  }
}

function pct(v: number | string | null | undefined): string {
  if (v == null || v === '') return '';
  const n = Number(v);
  return `${Number.isInteger(n) ? n : n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')} %`;
}

/* ── Item links: webshop page and documents ────────────────────────────── */

export function ItemLinks({
  productUrl,
  attachmentCount,
  onOpenDocuments,
}: {
  productUrl?: string | null;
  attachmentCount?: number;
  onOpenDocuments: () => void;
}) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1.5">
      {isSafeProductUrl(productUrl) && (
        <a
          href={productUrl}
          target="_blank"
          rel="noopener noreferrer nofollow"
          title={t('supplier_catalogs.open_product_page', { defaultValue: 'Open product page in the vendor shop' })}
          className="text-oe-blue hover:text-oe-blue/80"
        >
          <ExternalLink size={14} />
        </a>
      )}
      <button
        type="button"
        onClick={onOpenDocuments}
        title={t('supplier_catalogs.item_documents', { defaultValue: 'Datasheets and drawings' })}
        className={clsx(
          'inline-flex items-center gap-0.5 text-xs',
          attachmentCount ? 'text-oe-blue' : 'text-content-tertiary hover:text-content-secondary',
        )}
      >
        <Paperclip size={14} />
        {attachmentCount ? <span className="tabular-nums">{attachmentCount}</span> : null}
      </button>
    </span>
  );
}

export function ItemDocumentsModal({
  item,
  onClose,
}: {
  item: { id: string; sku: string; name: string };
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [projectId, setProjectId] = useState('');
  const [kind, setKind] = useState<ItemAttachment['kind']>('datasheet');
  const [file, setFile] = useState<File | null>(null);
  const q = useQuery({ queryKey: ['sc', 'attachments', item.id], queryFn: () => listItemAttachments(item.id) });
  const projectsQ = useQuery({ queryKey: ['projects', 'list'], queryFn: projectsApi.list });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['sc', 'attachments', item.id] });
    qc.invalidateQueries({ queryKey: ['sc', 'items'] });
    qc.invalidateQueries({ queryKey: ['sc', 'pl-entries'] });
  };
  const add = useMutation({
    mutationFn: async () => {
      if (!file || !projectId) throw new Error(t('supplier_catalogs.doc_pick_both', { defaultValue: 'Choose a project and a file' }));
      const doc = await uploadDocument(projectId, file, 'other');
      return addItemAttachment(item.id, { document_id: doc.id, kind, title: file.name });
    },
    onSuccess: () => {
      setFile(null);
      refresh();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const remove = useMutation({
    mutationFn: (a: ItemAttachment) => deleteItemAttachment(item.id, a.id),
    onSuccess: refresh,
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const open = async (a: ItemAttachment) => {
    try {
      const blob = await downloadDocumentBlob(a.document_id);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    }
  };
  const kinds: ItemAttachment['kind'][] = ['datasheet', 'drawing', 'certificate', 'other'];
  const kindLabel = (k: ItemAttachment['kind']) =>
    ({
      datasheet: t('supplier_catalogs.kind_datasheet', { defaultValue: 'Datasheet' }),
      drawing: t('supplier_catalogs.kind_drawing', { defaultValue: 'Drawing' }),
      certificate: t('supplier_catalogs.kind_certificate', { defaultValue: 'Certificate' }),
      other: t('supplier_catalogs.kind_other', { defaultValue: 'Other' }),
    })[k];
  const rows = q.data ?? [];
  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.item_documents', { defaultValue: 'Datasheets and drawings' })}
      subtitle={`${item.sku} · ${item.name}`}
      size="lg"
    >
      <p className="text-xs text-content-secondary mb-3">
        {t('supplier_catalogs.item_documents_hint', {
          defaultValue: 'Files are stored in the Documents of a project. Only people with access to that project can open them.',
        })}
      </p>
      {q.isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-content-tertiary py-2">
          {t('supplier_catalogs.no_item_documents', { defaultValue: 'No documents linked yet.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light mb-4">
          {rows.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-sm">
              <button type="button" className="text-oe-blue hover:underline truncate text-left" onClick={() => void open(a)}>
                {a.title}
              </button>
              <span className="flex items-center gap-2 shrink-0">
                <Badge variant="neutral">{kindLabel(a.kind)}</Badge>
                <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => remove.mutate(a)}>
                  {t('supplier_catalogs.unlink', { defaultValue: 'Unlink' })}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <WideModalSection columns={2}>
        <WideModalField label={t('supplier_catalogs.doc_project', { defaultValue: 'Store in project' })}>
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className={inputCls}>
            <option value="">{t('supplier_catalogs.choose', { defaultValue: 'Choose…' })}</option>
            {(projectsQ.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.doc_kind', { defaultValue: 'Type' })}>
          <select value={kind} onChange={(e) => setKind(e.target.value as ItemAttachment['kind'])} className={inputCls}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(k)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.doc_file', { defaultValue: 'File' })} span={2}>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
        </WideModalField>
      </WideModalSection>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" icon={<Upload size={14} />} loading={add.isPending} onClick={() => add.mutate()}>
          {t('supplier_catalogs.doc_attach', { defaultValue: 'Attach' })}
        </Button>
      </div>
    </WideModal>
  );
}

/* ── Panel ─────────────────────────────────────────────────────────────── */

export function PriceListsPanel({ vendors }: { vendors: Vendor[] }) {
  const { t } = useTranslation();
  const activeVendors = useMemo(() => vendors.filter((v) => v.status !== 'blacklisted'), [vendors]);
  const [vendorId, setVendorId] = useState('');
  const [priceListId, setPriceListId] = useState('');
  const [search, setSearch] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [discountsOpen, setDiscountsOpen] = useState(false);
  const [docsItem, setDocsItem] = useState<{ id: string; sku: string; name: string } | null>(null);
  const effectiveVendorId = vendorId || activeVendors[0]?.id || '';
  const vendor = activeVendors.find((v) => v.id === effectiveVendorId);

  const listsQ = useQuery({
    queryKey: ['sc', 'price-lists', effectiveVendorId],
    queryFn: () => listVendorPriceLists(effectiveVendorId),
    enabled: !!effectiveVendorId,
  });
  const lists = listsQ.data ?? [];
  useEffect(() => {
    if (lists.length && !lists.some((l) => l.id === priceListId)) setPriceListId(lists[0].id);
    if (!lists.length) setPriceListId('');
  }, [lists, priceListId]);

  const entriesQ = useQuery({
    queryKey: ['sc', 'pl-entries', priceListId, search],
    queryFn: () => listPriceListEntries(priceListId, { search: search || undefined, limit: 200 }),
    enabled: !!priceListId,
  });
  const pl = lists.find((l) => l.id === priceListId);

  if (activeVendors.length === 0) {
    return (
      <EmptyState
        icon={<FileSpreadsheet size={22} />}
        title={t('supplier_catalogs.pl_no_vendors', { defaultValue: 'Add a vendor first' })}
        description={t('supplier_catalogs.pl_no_vendors_desc', {
          defaultValue: 'Price lists belong to a vendor. Create the vendor in the Vendors tab, then import its price list here.',
        })}
      />
    );
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-content-tertiary min-w-[220px]">
          {t('supplier_catalogs.vendor', { defaultValue: 'Vendor' })}
          <select value={effectiveVendorId} onChange={(e) => setVendorId(e.target.value)} className={inputCls}>
            {activeVendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.code} · {v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-tertiary min-w-[240px]">
          {t('supplier_catalogs.price_list', { defaultValue: 'Price list' })}
          <select
            value={priceListId}
            onChange={(e) => setPriceListId(e.target.value)}
            className={inputCls}
            disabled={!lists.length}
          >
            {lists.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.entry_count ?? 0}){l.expired ? ` · ${t('supplier_catalogs.expired', { defaultValue: 'expired' })}` : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="flex-1" />
        <Button variant="secondary" icon={<Percent size={14} />} onClick={() => setDiscountsOpen(true)}>
          {t('supplier_catalogs.my_discounts', { defaultValue: 'My discounts' })}
        </Button>
        <Button variant="primary" icon={<Upload size={14} />} onClick={() => setImportOpen(true)}>
          {t('supplier_catalogs.import_price_list', { defaultValue: 'Import price list' })}
        </Button>
      </div>

      <p className="text-xs text-content-secondary">
        {t('supplier_catalogs.net_explainer', {
          defaultValue: 'List price is what the vendor publishes. Net price is what you pay after your discounts, and it is the price purchase orders use.',
        })}
      </p>

      {pl && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
          <span>
            {t('supplier_catalogs.valid', { defaultValue: 'Valid' })}: {pl.valid_from || '…'} – {pl.valid_to || '…'}
          </span>
          <span>· {pl.currency}</span>
          {pl.expired && (
            <Badge variant="error">
              {t('supplier_catalogs.pl_expired_badge', { defaultValue: 'Expired: not used for new orders' })}
            </Badge>
          )}
        </div>
      )}

      {listsQ.isLoading ? (
        <SkeletonTable rows={5} columns={6} />
      ) : !lists.length ? (
        <EmptyState
          icon={<FileSpreadsheet size={22} />}
          title={t('supplier_catalogs.pl_empty', { defaultValue: 'No price list for this vendor yet' })}
          description={t('supplier_catalogs.pl_empty_desc', {
            defaultValue: 'Import the vendor file (Excel, CSV or an SAP condition export). You see every change before anything is saved.',
          })}
          action={{
            label: t('supplier_catalogs.import_price_list', { defaultValue: 'Import price list' }),
            onClick: () => setImportOpen(true),
          }}
        />
      ) : (
        <>
          <div className="relative max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('supplier_catalogs.pl_search', { defaultValue: 'SKU, name, vendor SKU, MPN' })}
              className={clsx(inputCls, 'pl-8')}
            />
          </div>
          {entriesQ.isError ? (
            <EmptyState
              icon={<AlertOctagon size={20} />}
              title={t('supplier_catalogs.load_failed', { defaultValue: 'Could not load data' })}
              description={getErrorMessage(entriesQ.error)}
            />
          ) : entriesQ.isLoading ? (
            <SkeletonTable rows={6} columns={7} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left">{t('supplier_catalogs.sku', { defaultValue: 'SKU' })}</th>
                    <th className="px-3 py-2 text-left">{t('supplier_catalogs.name', { defaultValue: 'Name' })}</th>
                    <th className="px-3 py-2 text-left">{t('supplier_catalogs.vendor_sku', { defaultValue: 'Vendor SKU' })}</th>
                    <th className="px-3 py-2 text-right">{t('supplier_catalogs.list_price', { defaultValue: 'List price' })}</th>
                    <th className="px-3 py-2 text-left">{t('supplier_catalogs.discount', { defaultValue: 'Discount' })}</th>
                    <th className="px-3 py-2 text-right">{t('supplier_catalogs.net_price', { defaultValue: 'Net price' })}</th>
                    <th className="px-3 py-2 text-left">{t('supplier_catalogs.links', { defaultValue: 'Links' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {(entriesQ.data?.items ?? []).map((r) => (
                    <tr key={r.entry_id} className="border-t border-border-light hover:bg-surface-secondary">
                      <td className="px-3 py-2 font-mono text-xs text-content-secondary">{r.sku}</td>
                      <td className="px-3 py-2 text-content-primary truncate max-w-[280px]">{r.name}</td>
                      <td className="px-3 py-2 font-mono text-xs text-content-secondary">{r.vendor_sku || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                        <MoneyDisplay amount={String(r.gross_price)} currency={pl?.currency ?? 'EUR'} />
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {r.discount_source === 'none' ? (
                          <span className="text-content-tertiary">—</span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5">
                            {r.discount_pct != null && <span className="tabular-nums">-{pct(r.discount_pct)}</span>}
                            <Badge variant="blue">{sourceLabel(t, r.discount_source)}</Badge>
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums font-semibold text-content-primary">
                        <MoneyDisplay amount={String(r.net_price)} currency={pl?.currency ?? 'EUR'} />
                        <span className="ml-1 text-xs font-normal text-content-tertiary">/ {r.unit_of_measure}</span>
                      </td>
                      <td className="px-3 py-2">
                        <ItemLinks
                          productUrl={r.product_url}
                          attachmentCount={r.attachment_count}
                          onOpenDocuments={() => setDocsItem({ id: r.catalog_item_id, sku: r.sku, name: r.name })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {entriesQ.data && entriesQ.data.total > entriesQ.data.items.length && (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('supplier_catalogs.pl_showing', {
                    defaultValue: 'Showing {{shown}} of {{total}} items. Search to narrow the list.',
                    shown: entriesQ.data.items.length,
                    total: entriesQ.data.total,
                  })}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {importOpen && vendor && (
        <ImportPriceListModal
          vendor={vendor}
          priceLists={lists}
          onClose={() => setImportOpen(false)}
          onDone={(id) => {
            setImportOpen(false);
            setPriceListId(id);
          }}
        />
      )}
      {discountsOpen && vendor && (
        <DiscountsModal vendor={vendor} priceLists={lists} onClose={() => setDiscountsOpen(false)} />
      )}
      {docsItem && <ItemDocumentsModal item={docsItem} onClose={() => setDocsItem(null)} />}
    </div>
  );
}

/* ── Import wizard ─────────────────────────────────────────────────────── */

const MAPPABLE: ImportField[] = [
  'vendor_sku',
  'mpn',
  'gtin',
  'sku',
  'unit_price',
  'price_unit',
  'currency',
  'valid_from',
  'valid_to',
  'unit',
  'min_order_qty',
  'lead_time_days',
  'discount_pct',
];

function fieldLabel(t: TFn, f: ImportField): string {
  const labels: Record<ImportField, string> = {
    vendor_sku: t('supplier_catalogs.f_vendor_sku', { defaultValue: 'Vendor SKU / material no.' }),
    mpn: t('supplier_catalogs.f_mpn', { defaultValue: 'Manufacturer part no. (MPN)' }),
    gtin: t('supplier_catalogs.f_gtin', { defaultValue: 'GTIN / EAN' }),
    sku: t('supplier_catalogs.f_sku', { defaultValue: 'Our SKU' }),
    unit_price: t('supplier_catalogs.f_unit_price', { defaultValue: 'List price' }),
    price_unit: t('supplier_catalogs.f_price_unit', { defaultValue: 'Price per (quantity)' }),
    currency: t('supplier_catalogs.f_currency', { defaultValue: 'Currency' }),
    valid_from: t('supplier_catalogs.f_valid_from', { defaultValue: 'Valid from' }),
    valid_to: t('supplier_catalogs.f_valid_to', { defaultValue: 'Valid to' }),
    unit: t('supplier_catalogs.f_unit', { defaultValue: 'Unit' }),
    min_order_qty: t('supplier_catalogs.f_moq', { defaultValue: 'Minimum order' }),
    lead_time_days: t('supplier_catalogs.f_lead_time', { defaultValue: 'Lead time (days)' }),
    discount_pct: t('supplier_catalogs.f_discount', { defaultValue: 'Discount %' }),
    name: t('supplier_catalogs.f_name', { defaultValue: 'Name' }),
    notes: t('supplier_catalogs.f_notes', { defaultValue: 'Notes' }),
  };
  return labels[f];
}

function actionBadge(t: TFn, a: ImportAction) {
  const map: Record<ImportAction, { v: 'success' | 'blue' | 'neutral' | 'warning' | 'error'; label: string }> = {
    create: { v: 'success', label: t('supplier_catalogs.act_create', { defaultValue: 'New' }) },
    update: { v: 'blue', label: t('supplier_catalogs.act_update', { defaultValue: 'Price changed' }) },
    unchanged: { v: 'neutral', label: t('supplier_catalogs.act_unchanged', { defaultValue: 'Unchanged' }) },
    unmatched: { v: 'warning', label: t('supplier_catalogs.act_unmatched', { defaultValue: 'Item not found' }) },
    error: { v: 'error', label: t('supplier_catalogs.act_error', { defaultValue: 'Error' }) },
  };
  return <Badge variant={map[a].v}>{map[a].label}</Badge>;
}

export function rowError(t: TFn, code: string): string {
  const [kind] = code.split(':');
  switch (kind) {
    case 'missing_price':
      return t('supplier_catalogs.err_missing_price', { defaultValue: 'no price' });
    case 'missing_key':
      return t('supplier_catalogs.err_missing_key', { defaultValue: 'no SKU, MPN or GTIN' });
    case 'bad_number':
      return t('supplier_catalogs.err_bad_number', { defaultValue: 'number not readable' });
    case 'bad_date':
      return t('supplier_catalogs.err_bad_date', { defaultValue: 'date not readable' });
    case 'negative_price':
      return t('supplier_catalogs.err_negative_price', { defaultValue: 'negative price' });
    case 'unknown_unit':
      return t('supplier_catalogs.err_unknown_unit', { defaultValue: 'unit not recognised' });
    case 'discount_out_of_range':
      return t('supplier_catalogs.err_discount_out_of_range', { defaultValue: 'discount must be 0 to 100' });
    case 'duplicate_vendor_sku':
      return t('supplier_catalogs.err_duplicate_sku', { defaultValue: 'vendor SKU repeats in the file' });
    case 'duplicate_item':
      return t('supplier_catalogs.err_duplicate_item', { defaultValue: 'item appears twice' });
    default:
      return code;
  }
}

function ImportPriceListModal({
  vendor,
  priceLists,
  onClose,
  onDone,
}: {
  vendor: Vendor;
  priceLists: PriceList[];
  onClose: () => void;
  onDone: (priceListId: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [preset, setPreset] = useState('');
  const [target, setTarget] = useState('');
  const [name, setName] = useState('');
  const [validFrom, setValidFrom] = useState('');
  const [validTo, setValidTo] = useState('');
  const [mapping, setMapping] = useState<Partial<Record<ImportField, string>>>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const runPreview = async (m: Partial<Record<ImportField, string>> = mapping) => {
    if (!file) return;
    setBusy(true);
    try {
      const p = await previewPriceListImport(vendor.id, file, {
        mapping: m,
        preset: preset || undefined,
        priceListId: target || undefined,
        currency: vendor.currency,
      });
      setPreview(p);
      setMapping(p.mapping);
      if (!validFrom && p.valid_from) setValidFrom(p.valid_from);
      if (!validTo && p.valid_to) setValidTo(p.valid_to);
      if (!name) setName(file.name.replace(/\.[^.]+$/, ''));
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const commit = useMutation({
    mutationFn: () =>
      commitPriceListImport(vendor.id, file as File, {
        mapping,
        preset: preset || undefined,
        priceListId: target || undefined,
        currency: preview?.currencies.length === 1 ? preview.currencies[0] : vendor.currency,
        name: name || undefined,
        validFrom: validFrom || undefined,
        validTo: validTo || undefined,
      }),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('supplier_catalogs.import_done', {
          defaultValue: 'Price list saved: {{created}} new, {{updated}} changed',
          created: res.counts.create,
          updated: res.counts.update,
        }),
      });
      qc.invalidateQueries({ queryKey: ['sc', 'price-lists'] });
      qc.invalidateQueries({ queryKey: ['sc', 'pl-entries'] });
      onDone(res.price_list_id);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const writable = preview ? preview.counts.create + preview.counts.update : 0;
  const blocked = !!preview?.duplicate_vendor_skus.length || (!!validFrom && !!validTo && validTo < validFrom);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.import_title', { defaultValue: 'Import price list' })}
      subtitle={`${vendor.code} · ${vendor.name}`}
      size="xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!preview || blocked || writable === 0}
            loading={commit.isPending}
            onClick={() => commit.mutate()}
          >
            {t('supplier_catalogs.import_commit', { defaultValue: 'Save {{n}} prices', n: writable })}
          </Button>
        </div>
      }
    >
      <p className="text-xs text-content-secondary mb-3">
        {t('supplier_catalogs.import_steps', {
          defaultValue: '1. Choose the file. 2. Check which column is which. 3. Review the changes. Nothing is saved until you press Save.',
        })}
      </p>
      <WideModalSection columns={3}>
        <WideModalField label={t('supplier_catalogs.import_file', { defaultValue: 'File (Excel or CSV)' })}>
          <input
            type="file"
            accept=".xlsx,.csv,.txt"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPreview(null);
              setMapping({});
            }}
            className="text-sm"
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.import_format', { defaultValue: 'Layout' })}>
          <select value={preset} onChange={(e) => setPreset(e.target.value)} className={inputCls}>
            <option value="">{t('supplier_catalogs.preset_auto', { defaultValue: 'Detect automatically' })}</option>
            <option value="generic">{t('supplier_catalogs.preset_generic', { defaultValue: 'Vendor Excel / CSV' })}</option>
            <option value="sap_condition">
              {t('supplier_catalogs.preset_sap', { defaultValue: 'SAP condition export (MATNR, KBETR, KPEIN)' })}
            </option>
          </select>
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.import_target', { defaultValue: 'Save into' })}>
          <select value={target} onChange={(e) => setTarget(e.target.value)} className={inputCls}>
            <option value="">{t('supplier_catalogs.import_new_list', { defaultValue: 'A new price list' })}</option>
            {priceLists.map((l) => (
              <option key={l.id} value={l.id}>
                {t('supplier_catalogs.import_update_list', { defaultValue: 'Update: {{name}}', name: l.name })}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>
      <div className="mt-3 flex justify-end">
        <Button variant="secondary" disabled={!file} loading={busy} onClick={() => void runPreview()}>
          {preview
            ? t('supplier_catalogs.import_refresh', { defaultValue: 'Refresh preview' })
            : t('supplier_catalogs.import_preview', { defaultValue: 'Show preview' })}
        </Button>
      </div>

      {preview && (
        <div className="mt-4 space-y-4">
          <div>
            <h4 className="text-sm font-semibold mb-2">
              {t('supplier_catalogs.import_columns', { defaultValue: 'Columns in your file' })}
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {MAPPABLE.map((f) => (
                <label key={f} className="flex flex-col gap-1 text-xs text-content-tertiary">
                  {fieldLabel(t, f)}
                  <select
                    value={mapping[f] ?? ''}
                    onChange={(e) => {
                      const next = { ...mapping, [f]: e.target.value || undefined };
                      setMapping(next);
                    }}
                    className={clsx(inputCls, f === 'unit_price' && !mapping[f] && 'border-semantic-error')}
                  >
                    <option value="">—</option>
                    {preview.headers.filter(Boolean).map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('supplier_catalogs.import_match_hint', {
                defaultValue: 'Items are found by vendor SKU first, then MPN, then GTIN, then our SKU. Change a column, then Refresh preview.',
              })}
            </p>
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            {(['create', 'update', 'unchanged', 'unmatched', 'error'] as ImportAction[]).map((a) => (
              <span key={a} className="inline-flex items-center gap-1">
                {actionBadge(t, a)}
                <span className="tabular-nums font-semibold">{preview.counts[a] ?? 0}</span>
              </span>
            ))}
          </div>

          {preview.duplicate_vendor_skus.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-semantic-error/40 bg-semantic-error/10 px-3 py-2 text-xs">
              <AlertOctagon size={14} className="mt-0.5 shrink-0 text-semantic-error" />
              {t('supplier_catalogs.import_dups', {
                defaultValue: 'These vendor SKUs appear more than once: {{skus}}. Fix the file, then preview again.',
                skus: preview.duplicate_vendor_skus.slice(0, 10).join(', '),
              })}
            </div>
          )}

          <WideModalSection columns={3}>
            {!target && (
              <WideModalField label={t('supplier_catalogs.import_name', { defaultValue: 'Price list name' })}>
                <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
              </WideModalField>
            )}
            <WideModalField label={t('supplier_catalogs.f_valid_from', { defaultValue: 'Valid from' })}>
              <input type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} className={inputCls} />
            </WideModalField>
            <WideModalField label={t('supplier_catalogs.f_valid_to', { defaultValue: 'Valid to' })}>
              <input type="date" value={validTo} onChange={(e) => setValidTo(e.target.value)} className={inputCls} />
            </WideModalField>
          </WideModalSection>

          <div className="overflow-x-auto max-h-[360px]">
            <table className="w-full text-xs">
              <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide sticky top-0">
                <tr>
                  <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.row', { defaultValue: 'Row' })}</th>
                  <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.result', { defaultValue: 'Result' })}</th>
                  <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.vendor_sku', { defaultValue: 'Vendor SKU' })}</th>
                  <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.item', { defaultValue: 'Item' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('supplier_catalogs.old_price', { defaultValue: 'Old price' })}</th>
                  <th className="px-2 py-1.5 text-right">{t('supplier_catalogs.new_price', { defaultValue: 'New price' })}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row} className="border-t border-border-light">
                    <td className="px-2 py-1 tabular-nums text-content-tertiary">{r.row}</td>
                    <td className="px-2 py-1">
                      {actionBadge(t, r.action)}
                      {r.errors.length > 0 && (
                        <span className="ml-1 text-semantic-error">{r.errors.map((e) => rowError(t, e)).join(', ')}</span>
                      )}
                    </td>
                    <td className="px-2 py-1 font-mono">{r.vendor_sku || '—'}</td>
                    <td className="px-2 py-1 truncate max-w-[240px]">
                      {r.sku ? `${r.sku} · ${r.item_name ?? ''}` : '—'}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">{r.old_price != null ? String(r.old_price) : '—'}</td>
                    <td className="px-2 py-1 text-right tabular-nums font-semibold">
                      {r.new_price != null ? String(r.new_price) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {preview.rows_truncated && (
              <p className="mt-1 text-xs text-content-tertiary">
                {t('supplier_catalogs.import_first_rows', {
                  defaultValue: 'First {{n}} of {{total}} rows shown; the counts above cover every row.',
                  n: preview.rows.length,
                  total: preview.total_rows,
                })}
              </p>
            )}
          </div>
        </div>
      )}
    </WideModal>
  );
}

/* ── Discount agreements ───────────────────────────────────────────────── */

type Scope = 'overall' | 'category' | 'item';

function DiscountsModal({
  vendor,
  priceLists,
  onClose,
}: {
  vendor: Vendor;
  priceLists: PriceList[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const q = useQuery({ queryKey: ['sc', 'discounts', vendor.id], queryFn: () => listVendorDiscounts(vendor.id) });
  const catsQ = useQuery({
    queryKey: ['sc', 'categories'],
    queryFn: () => apiGet<Array<{ id: string; code: string; name: string }>>('/v1/supplier-catalogs/categories'),
  });
  const [scope, setScope] = useState<Scope>('overall');
  const [basis, setBasis] = useState<'pct' | 'fixed'>('pct');
  const [form, setForm] = useState({ name: '', value: '', category_id: '', price_list_id: '', valid_from: '', valid_to: '' });
  const [itemSearch, setItemSearch] = useState('');
  const [itemId, setItemId] = useState('');
  const itemsQ = useQuery({
    queryKey: ['sc', 'items', 'discount-pick', itemSearch],
    queryFn: () => listCatalogItems({ search: itemSearch, limit: 20 }),
    enabled: scope === 'item' && itemSearch.trim().length > 1,
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['sc', 'discounts', vendor.id] });
    qc.invalidateQueries({ queryKey: ['sc', 'pl-entries'] });
    qc.invalidateQueries({ queryKey: ['sc', 'price-compare'] });
  };
  const valueNum = Number(form.value.replace(',', '.'));
  const pctInvalid = basis === 'pct' && form.value !== '' && (!(valueNum >= 0) || valueNum > 100);
  const create = useMutation({
    mutationFn: () => {
      const payload: CreateDiscountPayload = {
        name: form.name.trim(),
        price_list_id: form.price_list_id || undefined,
        valid_from: form.valid_from || undefined,
        valid_to: form.valid_to || undefined,
      };
      if (scope === 'category') payload.category_id = form.category_id || undefined;
      if (scope === 'item') payload.catalog_item_id = itemId || undefined;
      const value = form.value.replace(',', '.');
      if (basis === 'fixed' && scope === 'item') payload.fixed_net_price = value;
      else payload.discount_pct = value;
      return createVendorDiscount(vendor.id, payload);
    },
    onSuccess: () => {
      setForm({ name: '', value: '', category_id: '', price_list_id: '', valid_from: '', valid_to: '' });
      setItemId('');
      invalidate();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const remove = useMutation({
    mutationFn: (a: DiscountAgreement) => deleteVendorDiscount(a.id),
    onSuccess: invalidate,
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const cats = catsQ.data ?? [];
  const scopeText = (a: DiscountAgreement) => {
    const parts: string[] = [];
    if (a.catalog_item_id) parts.push(t('supplier_catalogs.scope_one_item', { defaultValue: 'One item' }));
    else if (a.category_id)
      parts.push(
        t('supplier_catalogs.scope_category_named', {
          defaultValue: 'Category {{name}}',
          name: cats.find((c) => c.id === a.category_id)?.name ?? '',
        }),
      );
    else parts.push(t('supplier_catalogs.scope_all_items', { defaultValue: 'All items' }));
    if (a.price_list_id)
      parts.push(priceLists.find((l) => l.id === a.price_list_id)?.name ?? t('supplier_catalogs.price_list', { defaultValue: 'Price list' }));
    return parts.join(' · ');
  };
  const canSave =
    form.name.trim() &&
    form.value !== '' &&
    !pctInvalid &&
    (scope !== 'category' || form.category_id) &&
    (scope !== 'item' || itemId);

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('supplier_catalogs.discounts_title', { defaultValue: 'My discounts with this vendor' })}
      subtitle={`${vendor.code} · ${vendor.name}`}
      size="xl"
    >
      <p className="text-xs text-content-secondary mb-3">
        {t('supplier_catalogs.discounts_precedence', {
          defaultValue: 'The most specific discount wins: a fixed net price or discount for one item, then the item category, then the overall discount. Orders keep the price they were placed with.',
        })}
      </p>
      {q.isLoading ? (
        <SkeletonTable rows={3} columns={4} />
      ) : (q.data ?? []).length === 0 ? (
        <p className="text-sm text-content-tertiary py-2">
          {t('supplier_catalogs.no_discounts', { defaultValue: 'No discounts agreed yet: list price = net price.' })}
        </p>
      ) : (
        <table className="w-full text-sm mb-4">
          <thead className="text-content-tertiary text-xs uppercase tracking-wide">
            <tr>
              <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.name', { defaultValue: 'Name' })}</th>
              <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.applies_to', { defaultValue: 'Applies to' })}</th>
              <th className="px-2 py-1.5 text-right">{t('supplier_catalogs.discount', { defaultValue: 'Discount' })}</th>
              <th className="px-2 py-1.5 text-left">{t('supplier_catalogs.valid', { defaultValue: 'Valid' })}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((a) => (
              <tr key={a.id} className="border-t border-border-light">
                <td className="px-2 py-1.5">{a.name}</td>
                <td className="px-2 py-1.5 text-xs text-content-secondary">{scopeText(a)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {a.fixed_net_price != null ? (
                    <span>
                      {t('supplier_catalogs.fixed_net_short', { defaultValue: 'Net' })}{' '}
                      <MoneyDisplay amount={String(a.fixed_net_price)} currency={vendor.currency} />
                    </span>
                  ) : (
                    `-${pct(a.discount_pct)}`
                  )}
                </td>
                <td className="px-2 py-1.5 text-xs text-content-secondary">
                  {a.valid_from || '…'} – {a.valid_to || '…'}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => remove.mutate(a)}>
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4 className="text-sm font-semibold mb-2">{t('supplier_catalogs.add_discount', { defaultValue: 'Add a discount' })}</h4>
      <WideModalSection columns={3}>
        <WideModalField label={t('supplier_catalogs.name', { defaultValue: 'Name' })} required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder={t('supplier_catalogs.discount_name_ph', { defaultValue: 'e.g. Framework agreement 2026' })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.applies_to', { defaultValue: 'Applies to' })}>
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as Scope);
              if (e.target.value !== 'item') setBasis('pct');
            }}
            className={inputCls}
          >
            <option value="overall">{t('supplier_catalogs.scope_all_items', { defaultValue: 'All items' })}</option>
            <option value="category">{t('supplier_catalogs.scope_category', { defaultValue: 'One item category' })}</option>
            <option value="item">{t('supplier_catalogs.scope_one_item', { defaultValue: 'One item' })}</option>
          </select>
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.price_list', { defaultValue: 'Price list' })}>
          <select
            value={form.price_list_id}
            onChange={(e) => setForm({ ...form, price_list_id: e.target.value })}
            className={inputCls}
          >
            <option value="">{t('supplier_catalogs.all_price_lists', { defaultValue: 'All price lists' })}</option>
            {priceLists.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </WideModalField>
        {scope === 'category' && (
          <WideModalField label={t('supplier_catalogs.category', { defaultValue: 'Category' })} required>
            <select
              value={form.category_id}
              onChange={(e) => setForm({ ...form, category_id: e.target.value })}
              className={inputCls}
            >
              <option value="">{t('supplier_catalogs.choose', { defaultValue: 'Choose…' })}</option>
              {cats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
        {scope === 'item' && (
          <WideModalField label={t('supplier_catalogs.item', { defaultValue: 'Item' })} required>
            <input
              value={itemSearch}
              onChange={(e) => setItemSearch(e.target.value)}
              placeholder={t('supplier_catalogs.item_search_ph', { defaultValue: 'Type SKU or name' })}
              className={inputCls}
            />
            <select value={itemId} onChange={(e) => setItemId(e.target.value)} className={clsx(inputCls, 'mt-1')}>
              <option value="">{t('supplier_catalogs.choose', { defaultValue: 'Choose…' })}</option>
              {(itemsQ.data?.items ?? []).map((it) => (
                <option key={it.id} value={it.id}>
                  {it.sku} · {it.name}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
        {scope === 'item' && (
          <WideModalField label={t('supplier_catalogs.discount_basis', { defaultValue: 'Agreed as' })}>
            <select value={basis} onChange={(e) => setBasis(e.target.value as 'pct' | 'fixed')} className={inputCls}>
              <option value="pct">{t('supplier_catalogs.basis_pct', { defaultValue: 'Discount in %' })}</option>
              <option value="fixed">{t('supplier_catalogs.basis_fixed', { defaultValue: 'Fixed net price' })}</option>
            </select>
          </WideModalField>
        )}
        <WideModalField
          label={
            basis === 'fixed'
              ? t('supplier_catalogs.fixed_net_label', { defaultValue: 'Net price per unit ({{cur}})', cur: vendor.currency })
              : t('supplier_catalogs.discount_pct_label', { defaultValue: 'Discount %' })
          }
          required
          hint={pctInvalid ? t('supplier_catalogs.pct_range', { defaultValue: 'Between 0 and 100' }) : undefined}
        >
          <input
            inputMode="decimal"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
            className={clsx(inputCls, pctInvalid && 'border-semantic-error')}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.f_valid_from', { defaultValue: 'Valid from' })}>
          <input
            type="date"
            value={form.valid_from}
            onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('supplier_catalogs.f_valid_to', { defaultValue: 'Valid to' })}>
          <input
            type="date"
            value={form.valid_to}
            onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" disabled={!canSave} loading={create.isPending} onClick={() => create.mutate()}>
          {t('supplier_catalogs.save_discount', { defaultValue: 'Save discount' })}
        </Button>
      </div>
    </WideModal>
  );
}
