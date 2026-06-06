/**
 * Document Templates — Property Development settings page.
 *
 * Renders a 3-column card grid (1 col on mobile) covering:
 *   - the six built-in PDF generators shipped with the platform
 *     (Reservation Receipt, SPA, Payment Receipt, Handover Cert,
 *     Warranty Cert, NOC); each has working "Preview" + "Download
 *     sample" buttons that POST sample-preview and open the resulting
 *     PDF in a new tab via a blob URL.
 *   - tenant-uploaded custom templates (.docx / .html / .pdf / .odt /
 *     .md / .txt up to 10 MB), via the form at the top of the page
 *     (``POST /property-dev/document-templates/upload``). Custom rows
 *     get a "Download" button (streams the original bytes) and a
 *     "Delete" trash icon.
 *
 * Per-development override:
 *   The active development is stored in localStorage under
 *   ``propdev:doc-templates:active-dev``. Each card carries a "Set as
 *   default for current development" toggle that flips a per-doc_type
 *   key in localStorage — this is a client-side preference only (the
 *   real preferred-template-per-development feature ships with the
 *   document-generation events themselves, not the settings page).
 *
 * Variables documentation:
 *   The "{i}" button opens a WideModal listing the variables custom
 *   templates may interpolate (``{buyer.full_name}``, ``{plot.area_m2}``,
 *   …). The list comes from the catalogue endpoint, so the backend
 *   stays source-of-truth.
 *
 * Empty state:
 *   Even though built-in templates always exist, we render an empty
 *   state when the catalogue endpoint returns zero rows (e.g. an
 *   alternate tenant deployment that has disabled the built-ins).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertOctagon,
  Banknote,
  CheckCircle2,
  Code2,
  Download,
  Edit3,
  Eye,
  FilePlus,
  FileSignature,
  FileText,
  Globe2,
  Home,
  Info,
  Key,
  Landmark,
  Loader2,
  RotateCcw,
  ShieldAlert,
  Trash2,
  Upload as UploadIcon,
  Vault,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  EmptyState,
  SkeletonText,
  WideModal,
  WideModalSection,
  ConfirmDialog,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  customDocumentTemplateDownloadUrl,
  deleteCustomDocumentTemplate,
  deleteDocumentTemplateLocaleOverride,
  getCustomDocumentTemplateContent,
  getDocumentTemplateLocale,
  listDevelopments,
  listDocumentTemplates,
  putDocumentTemplateLocale,
  sampleDocumentPreview,
  saveTextCustomDocumentTemplate,
  uploadCustomDocumentTemplate,
  type CustomTemplateTextContentType,
  type Development,
  type DocumentTemplateEntry,
  type DocumentTemplateLocaleStatus,
  type DocumentTemplateVariableGroup,
  type PropDevDocType,
} from './api';

// Static icon map for the known built-in doc_types. Custom or
// jurisdiction-specific doc_types (e.g. ``escritura_publica``,
// ``juyo_jiko_setsumeisho``, ``acta_de_entrega``) fall back to a
// generic FileText so the grid stays visually balanced regardless of
// which country the tenant operates in.
const ICON_FOR_DOC: Record<string, React.ReactNode> = {
  reservation_receipt: <FileText size={16} />,
  sales_contract: <FileSignature size={16} />,
  payment_receipt: <FileText size={16} />,
  handover_certificate: <FileSignature size={16} />,
  warranty_certificate: <ShieldAlert size={16} />,
  noc: <FileSignature size={16} />,
  tenant_lease_agreement: <Home size={16} />,
  move_in_checklist: <Key size={16} />,
  mortgage_clearance_letter: <Banknote size={16} />,
  title_deed_transfer_request: <Landmark size={16} />,
  escrow_release_authorization: <Vault size={16} />,
  refund_authorization: <RotateCcw size={16} />,
};

// Fallback set of doc_types known to have a built-in reportlab renderer.
// Used ONLY when the backend response omits ``has_pdf_renderer`` (older
// API contract). The authoritative source-of-truth is the backend's
// catalogue entry, which already mirrors the renderer registry; this
// list documents the shipping defaults so a brand-new client paired
// with an older server still gates Preview / Download-sample correctly.
const RENDERABLE_BUILTIN_DOC_TYPES_FALLBACK = new Set<string>([
  'reservation_receipt',
  'sales_contract',
  'payment_receipt',
  'handover_certificate',
  'warranty_certificate',
  'noc',
  'tenant_lease_agreement',
  'move_in_checklist',
  'mortgage_clearance_letter',
  'title_deed_transfer_request',
  'escrow_release_authorization',
  'refund_authorization',
]);

/**
 * Decide whether a catalogue entry should expose the Preview /
 * Download-sample buttons. Prefers the server-supplied
 * ``has_pdf_renderer`` flag (worldwide-parameterized as of v4.7); falls
 * back to the legacy built-in slug list when the field is absent.
 */
function templateHasPdfRenderer(tpl: DocumentTemplateEntry): boolean {
  if (typeof tpl.has_pdf_renderer === 'boolean') return tpl.has_pdf_renderer;
  if (tpl.is_custom) return false;
  return RENDERABLE_BUILTIN_DOC_TYPES_FALLBACK.has(String(tpl.doc_type));
}

const ACTIVE_DEV_LS_KEY = 'propdev:doc-templates:active-dev';
const DEFAULT_TPL_LS_PREFIX = 'propdev:doc-templates:default-for-dev:';

function readActiveDevelopmentId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_DEV_LS_KEY);
  } catch {
    return null;
  }
}

function writeActiveDevelopmentId(value: string | null): void {
  try {
    if (value) localStorage.setItem(ACTIVE_DEV_LS_KEY, value);
    else localStorage.removeItem(ACTIVE_DEV_LS_KEY);
  } catch {
    /* localStorage may be unavailable (private mode, embedded iframe). */
  }
}

function getDefaultTemplateForDev(
  devId: string | null,
  docType: string,
): string | null {
  if (!devId) return null;
  try {
    return localStorage.getItem(`${DEFAULT_TPL_LS_PREFIX}${devId}:${docType}`);
  } catch {
    return null;
  }
}

function setDefaultTemplateForDev(
  devId: string | null,
  docType: string,
  templateId: string | null,
): void {
  if (!devId) return;
  try {
    const key = `${DEFAULT_TPL_LS_PREFIX}${devId}:${docType}`;
    if (templateId) localStorage.setItem(key, templateId);
    else localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/**
 * Editor session state. `editingTemplateId === null` means a brand-new
 * template (save creates a row). Otherwise the editor pre-loads the
 * existing content via the GET-content endpoint and a save PATCHes the
 * row in-place.
 */
interface EditorSession {
  editingTemplateId: string | null;
  initialName?: string;
  initialDocType?: string;
  initialEntity?: string;
  initialContentType?: CustomTemplateTextContentType;
}

export function DocumentTemplatesSettingsPage() {
  const { t } = useTranslation();
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [editorSession, setEditorSession] = useState<EditorSession | null>(null);
  const [localeEditor, setLocaleEditor] = useState<string | null>(null);
  const [activeDevId, setActiveDevId] = useState<string | null>(
    () => readActiveDevelopmentId(),
  );

  const dataQ = useQuery({
    queryKey: ['propdev', 'document-templates', activeDevId ?? ''],
    queryFn: () => listDocumentTemplates(activeDevId ?? undefined),
    staleTime: 5 * 60_000,
  });

  // Developments feed the active-development picker (CONN-25): operators
  // pick a development by name instead of pasting a raw UUID, so the
  // per-development default-template toggles are reachable in two clicks.
  const developmentsQ = useQuery({
    queryKey: ['propdev-developments'],
    queryFn: () => listDevelopments({ limit: 100 }),
    staleTime: 5 * 60_000,
  });
  const developments = developmentsQ.data ?? [];

  // Persist the active-dev pick on change.
  useEffect(() => {
    writeActiveDevelopmentId(activeDevId);
  }, [activeDevId]);

  const templates = dataQ.data?.templates ?? [];
  const builtins = templates.filter((t) => !t.is_custom);
  const customs = templates.filter((t) => t.is_custom);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.settings', { defaultValue: 'Settings' }) },
          {
            label: t('nav.property_dev', { defaultValue: 'Property Development' }),
            to: '/property-dev',
          },
          {
            label: t('property_dev.doc_templates.title', {
              defaultValue: 'Document templates',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('property_dev.doc_templates.title', {
          defaultValue: 'Document templates',
        })}
        subtitle={t('property_dev.doc_templates.intro', {
          defaultValue:
            'Document templates power the PDF documents OpenConstructionERP generates for buyer journeys, reservation receipts, SPA contracts, handover protocols, warranty certificates. Pick a built-in template, preview it for your country or regulator, or upload your own .docx / .html / .pdf template.',
        })}
        actions={
          <Button
            variant="ghost"
            icon={<Info size={14} />}
            onClick={() => setVariablesOpen(true)}
            data-testid="open-variables-doc"
          >
            {t('property_dev.doc_templates.variables_btn', {
              defaultValue: 'Template variables',
            })}
          </Button>
        }
      />

      {/* Locales / regulators meta + active-development context */}
      <Card className="p-4">
        {dataQ.data && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-xs text-content-tertiary">
                {t('property_dev.doc_templates.locales_supported', {
                  defaultValue: 'Locales:',
                })}
              </div>
              <LocaleStatusList
                statuses={dataQ.data.locale_status}
                fallback={dataQ.data.locales}
                onEdit={(code) => setLocaleEditor(code)}
              />
              <button
                type="button"
                onClick={() => setLocaleEditor('__new__')}
                className="ml-1 rounded-full border border-dashed border-oe-blue/40 px-2 py-0.5 text-[11px] font-medium text-oe-blue hover:bg-oe-blue/5"
                data-testid="open-locale-editor-new"
                title={t('property_dev.doc_templates.add_locale_hint', {
                  defaultValue:
                    'Upload a tenant-owned JSON to override or add a new translation.',
                })}
              >
                {t('property_dev.doc_templates.add_locale', {
                  defaultValue: '+ Add / edit translation',
                })}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-xs text-content-tertiary">
                {t('property_dev.doc_templates.regulators_supported', {
                  defaultValue: 'Regulators:',
                })}
              </div>
              {dataQ.data.regulators.map((r) => (
                <Badge key={r} variant="neutral">
                  {r}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {/* Active development context — used by the per-dev "set as default"
            toggles. A select populated from listDevelopments (CONN-25)
            replaces the old free-text UUID input so the per-development
            defaults are reachable without pasting an id. The chosen id is
            stored under the same localStorage key. */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
          <label htmlFor="propdev-active-dev" className="font-medium">
            {t('property_dev.doc_templates.active_dev_label', {
              defaultValue: 'Active development (for "set as default" toggles):',
            })}
          </label>
          <select
            id="propdev-active-dev"
            value={activeDevId ?? ''}
            onChange={(e) => setActiveDevId(e.target.value || null)}
            disabled={developmentsQ.isLoading}
            className="h-7 w-72 max-w-full rounded border border-border bg-surface-primary px-2 text-xs disabled:opacity-60"
            data-testid="active-dev-input"
          >
            <option value="">
              {developmentsQ.isLoading
                ? t('common.loading', { defaultValue: 'Loading…' })
                : t('property_dev.doc_templates.active_dev_none', {
                    defaultValue: 'No development (built-in defaults)',
                  })}
            </option>
            {developments.map((d: Development) => (
              <option key={d.id} value={d.id}>
                {d.code ? `${d.code} - ${d.name}` : d.name}
              </option>
            ))}
            {/* Keep a stored id selectable even when it is not in the
                loaded list (different project scope / stale localStorage). */}
            {activeDevId &&
              !developments.some((d: Development) => d.id === activeDevId) && (
                <option value={activeDevId}>
                  {t('property_dev.doc_templates.active_dev_unknown', {
                    defaultValue: 'Saved development ({{id}})',
                    id: activeDevId.slice(0, 8),
                  })}
                </option>
              )}
          </select>
          {developmentsQ.isError && (
            <button
              type="button"
              className="text-xs text-oe-blue underline"
              onClick={() => developmentsQ.refetch()}
            >
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          )}
          {activeDevId && (
            <button
              type="button"
              className="text-xs text-content-tertiary underline"
              onClick={() => setActiveDevId(null)}
            >
              {t('common.clear', { defaultValue: 'Clear' })}
            </button>
          )}
        </div>
      </Card>

      {/* Create-in-browser CTA */}
      <Card className="p-4 flex flex-wrap items-center justify-between gap-3 bg-oe-blue/5 border-oe-blue/20">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
            <Edit3 size={16} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-content-primary">
              {t('property_dev.doc_templates.editor_cta_title', {
                defaultValue: 'Create or edit templates in your browser',
              })}
            </h2>
            <p className="mt-0.5 text-xs text-content-secondary max-w-2xl">
              {t('property_dev.doc_templates.editor_cta_subtitle', {
                defaultValue:
                  "Write HTML or Markdown directly here - no upload required. Click variable chips to insert {placeholders}, and see a live preview alongside the source.",
              })}
            </p>
          </div>
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={<FilePlus size={14} />}
          onClick={() => setEditorSession({ editingTemplateId: null })}
          data-testid="open-editor-new"
        >
          {t('property_dev.doc_templates.editor_cta_btn', {
            defaultValue: 'Create new template',
          })}
        </Button>
      </Card>

      {/* Upload custom template */}
      <UploadCustomTemplateForm
        onUploaded={() => dataQ.refetch()}
        allowedExtensions={
          dataQ.data?.upload?.allowed_extensions ?? [
            '.docx', '.html', '.htm', '.pdf', '.odt', '.md', '.txt', '.xlsx',
          ]
        }
        maxSizeMb={dataQ.data?.upload?.max_size_mb ?? 10}
        activeDevId={activeDevId}
        docTypePresets={
          dataQ.data?.doc_type_presets ?? DOC_TYPE_PRESETS_FALLBACK
        }
        entityPresets={
          dataQ.data?.entity_presets ?? ENTITY_PRESETS_FALLBACK
        }
      />

      {/* Catalogue grid */}
      {dataQ.isLoading ? (
        <Card padding="md">
          <SkeletonText lines={6} />
        </Card>
      ) : dataQ.isError ? (
        <Card padding="md">
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('property_dev.doc_templates.load_error', {
              defaultValue: 'Could not load templates',
            })}
            description={getErrorMessage(dataQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => dataQ.refetch(),
            }}
          />
        </Card>
      ) : templates.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<FileSignature size={22} />}
            title={t('property_dev.doc_templates.empty', {
              defaultValue: 'No templates yet',
            })}
            description={t('property_dev.doc_templates.empty_desc', {
              defaultValue:
                'Built-in templates ship with the platform; upload your first custom template using the form above.',
            })}
          />
        </Card>
      ) : (
        <>
          <SectionHeader
            label={t('property_dev.doc_templates.builtins_header', {
              defaultValue: 'Built-in templates',
            })}
            count={builtins.length}
          />
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {builtins.map((tpl) => (
              <TemplateCard
                key={tpl.doc_type}
                template={tpl}
                locales={dataQ.data!.locales}
                regulators={dataQ.data!.regulators}
                activeDevId={activeDevId}
                onAfterDelete={() => dataQ.refetch()}
                onOpenEditor={(session) => setEditorSession(session)}
              />
            ))}
          </div>
          {customs.length > 0 && (
            <>
              <SectionHeader
                label={t('property_dev.doc_templates.customs_header', {
                  defaultValue: 'Your uploaded templates',
                })}
                count={customs.length}
              />
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {customs.map((tpl) => (
                  <TemplateCard
                    key={tpl.id ?? tpl.doc_type}
                    template={tpl}
                    locales={dataQ.data!.locales}
                    regulators={dataQ.data!.regulators}
                    activeDevId={activeDevId}
                    onAfterDelete={() => dataQ.refetch()}
                    onOpenEditor={(session) => setEditorSession(session)}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      <VariablesModal
        open={variablesOpen}
        onClose={() => setVariablesOpen(false)}
        groups={dataQ.data?.variables ?? []}
      />

      {editorSession && (
        <TemplateEditorModal
          session={editorSession}
          variableGroups={dataQ.data?.variables ?? []}
          activeDevId={activeDevId}
          docTypePresets={
            dataQ.data?.doc_type_presets ?? DOC_TYPE_PRESETS_FALLBACK
          }
          entityPresets={
            dataQ.data?.entity_presets ?? ENTITY_PRESETS_FALLBACK
          }
          onClose={() => setEditorSession(null)}
          onSaved={() => {
            setEditorSession(null);
            dataQ.refetch();
          }}
        />
      )}

      {localeEditor && (
        <LocaleEditorModal
          initialCode={localeEditor === '__new__' ? null : localeEditor}
          statuses={dataQ.data?.locale_status ?? []}
          onClose={() => setLocaleEditor(null)}
          onSaved={() => {
            setLocaleEditor(null);
            dataQ.refetch();
          }}
        />
      )}
    </div>
  );
}

/**
 * Datalist-backed free-text combobox used for ``doc_type`` / ``entity``
 * / regulator slugs.
 *
 * Why a native ``<input list>`` instead of a custom dropdown:
 *
 *   - **Zero dependencies** — fits the LIGHTWEIGHT principle. Existing
 *     dropdowns on this page use plain native ``<select>``; adopting a
 *     headless-UI combobox just for this would balloon the bundle.
 *   - **Accept any string** — the user can pick a preset OR type their
 *     own jurisdiction-specific slug (``escritura_publica``,
 *     ``juyo_jiko_setsumeisho``, ``acta_de_entrega``, …). The backend
 *     validates shape, not membership, so the UI must mirror that.
 *   - **Native a11y + IME support** — datalist gets keyboard focus
 *     ring, screen-reader announcement and Asian-IME composition for
 *     free; rolling our own would re-invent all three.
 *
 * The datalist id is namespaced with a hash of the presets so two
 * comboboxes on the same page (doc_type + entity) don't share a list.
 */
function SlugCombobox(props: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  presets: ReadonlyArray<string>;
  placeholder?: string;
  className?: string;
  'data-testid'?: string;
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
}) {
  const {
    id,
    value,
    onChange,
    presets,
    placeholder,
    className,
    disabled,
    title,
    ariaLabel,
  } = props;
  const listId = `${id}-presets`;
  // Dedup presets (regulator list may contain "NONE" twice when filtered).
  const uniquePresets = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const p of presets) {
      if (!seen.has(p)) {
        seen.add(p);
        out.push(p);
      }
    }
    return out;
  }, [presets]);
  return (
    <>
      <input
        id={id}
        type="text"
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={
          className ??
          'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue disabled:opacity-50'
        }
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        title={title}
        aria-label={ariaLabel}
        data-testid={props['data-testid']}
      />
      <datalist id={listId}>
        {uniquePresets.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="mt-2 flex items-center gap-2 px-1 text-xs font-medium uppercase tracking-wide text-content-tertiary">
      <span>{label}</span>
      <Badge variant="neutral">{count}</Badge>
    </div>
  );
}

function UploadCustomTemplateForm({
  onUploaded,
  allowedExtensions,
  maxSizeMb,
  activeDevId,
  docTypePresets,
  entityPresets,
}: {
  onUploaded: () => void;
  allowedExtensions: string[];
  maxSizeMb: number;
  activeDevId: string | null;
  docTypePresets: ReadonlyArray<string>;
  entityPresets: ReadonlyArray<string>;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [docType, setDocType] = useState('custom');
  const [entity, setEntity] = useState('custom');
  const [trigger, setTrigger] = useState('manual');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);

  const accept = useMemo(() => allowedExtensions.join(','), [allowedExtensions]);

  const allowedExtSet = useMemo(
    () => new Set(allowedExtensions.map((e) => e.toLowerCase())),
    [allowedExtensions],
  );

  const pickFile = (next: File | null) => {
    if (next) {
      const dot = next.name.lastIndexOf('.');
      const ext = dot >= 0 ? next.name.slice(dot).toLowerCase() : '';
      if (!allowedExtSet.has(ext)) {
        addToast({
          type: 'error',
          title: t('property_dev.doc_templates.upload_bad_ext', {
            defaultValue: 'Unsupported file type. Allowed: {{exts}}',
            exts: allowedExtensions.join(', '),
          }),
        });
        setFile(null);
        return;
      }
    }
    setFile(next);
  };

  const reset = () => {
    setFile(null);
    setName('');
    setDocType('custom');
    setEntity('custom');
    setTrigger('manual');
    setDescription('');
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      addToast({
        type: 'warning',
        title: t('property_dev.doc_templates.upload_no_file', {
          defaultValue: 'Pick a file before uploading',
        }),
      });
      return;
    }
    if (!name.trim()) {
      addToast({
        type: 'warning',
        title: t('property_dev.doc_templates.upload_no_name', {
          defaultValue: 'Give the template a name',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await uploadCustomDocumentTemplate({
        file,
        name: name.trim(),
        doc_type: docType,
        entity,
        trigger,
        description,
        development_id: activeDevId ?? undefined,
      });
      addToast({
        type: 'success',
        title: t('property_dev.doc_templates.upload_ok', {
          defaultValue: 'Template uploaded',
        }),
      });
      reset();
      onUploaded();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <UploadIcon size={14} className="text-oe-blue" />
        {t('property_dev.doc_templates.upload_title', {
          defaultValue: 'Upload custom template',
        })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('property_dev.doc_templates.upload_subtitle', {
          defaultValue:
            'Accepts .docx, .html, .pdf, .odt, .md or .txt up to {{max}} MB. The file is stored against your project; rendering is done by the document-generation events.',
          max: maxSizeMb,
        })}
      </p>
      <form className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-12" onSubmit={submit}>
        <div className="md:col-span-4">
          <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
            {t('property_dev.doc_templates.upload_field_file', {
              defaultValue: 'File',
            })}
          </label>
          <input
            type="file"
            accept={accept}
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs file:mr-2 file:rounded-md file:border-0 file:bg-oe-blue/10 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-oe-blue hover:file:bg-oe-blue/20"
            data-testid="custom-upload-file"
          />
        </div>
        <div className="md:col-span-4">
          <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
            {t('property_dev.doc_templates.upload_field_name', {
              defaultValue: 'Display name',
            })}
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('property_dev.doc_templates.upload_field_name_ph', {
              defaultValue: 'e.g. KYC checklist (UAE 2026)',
            })}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            data-testid="custom-upload-name"
          />
        </div>
        <div className="md:col-span-2">
          <label
            htmlFor="custom-upload-doctype"
            className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
          >
            {t('property_dev.doc_templates.upload_field_doctype', {
              defaultValue: 'Doc type',
            })}
          </label>
          <SlugCombobox
            id="custom-upload-doctype"
            value={docType}
            onChange={setDocType}
            presets={docTypePresets}
            placeholder={t('property_dev.doc_templates.doctype_placeholder', {
              defaultValue: 'pick or type any slug',
            })}
            data-testid="custom-upload-doctype"
            ariaLabel={t('property_dev.doc_templates.upload_field_doctype', {
              defaultValue: 'Doc type',
            })}
          />
        </div>
        <div className="md:col-span-2">
          <label
            htmlFor="custom-upload-entity"
            className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
          >
            {t('property_dev.doc_templates.upload_field_entity', {
              defaultValue: 'Entity',
            })}
          </label>
          <SlugCombobox
            id="custom-upload-entity"
            value={entity}
            onChange={setEntity}
            presets={entityPresets}
            placeholder={t('property_dev.doc_templates.entity_placeholder', {
              defaultValue: 'pick or type any slug',
            })}
            data-testid="custom-upload-entity"
            ariaLabel={t('property_dev.doc_templates.upload_field_entity', {
              defaultValue: 'Entity',
            })}
          />
        </div>
        <div className="md:col-span-8">
          <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
            {t('property_dev.doc_templates.upload_field_desc', {
              defaultValue: 'Description (optional)',
            })}
          </label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('property_dev.doc_templates.upload_field_desc_ph', {
              defaultValue: 'Short note for your team',
            })}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            data-testid="custom-upload-desc"
          />
        </div>
        <div className="md:col-span-2">
          <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
            {t('property_dev.doc_templates.upload_field_trigger', {
              defaultValue: 'Trigger',
            })}
          </label>
          <input
            type="text"
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
            placeholder="manual"
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            data-testid="custom-upload-trigger"
          />
        </div>
        <div className="md:col-span-2 flex items-end">
          <Button
            type="submit"
            variant="primary"
            size="md"
            disabled={busy}
            loading={busy}
            icon={<UploadIcon size={14} />}
            className="w-full"
            data-testid="custom-upload-submit"
          >
            {t('property_dev.doc_templates.upload_submit', {
              defaultValue: 'Upload',
            })}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function TemplateCard({
  template,
  locales,
  regulators,
  activeDevId,
  onAfterDelete,
  onOpenEditor,
}: {
  template: DocumentTemplateEntry;
  locales: string[];
  regulators: string[];
  activeDevId: string | null;
  onAfterDelete: () => void;
  onOpenEditor: (session: EditorSession) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const [locale, setLocale] = useState(locales[0] ?? 'en');
  const [regulator, setRegulator] = useState(
    regulators.includes('NONE') ? 'NONE' : (regulators[0] ?? 'NONE'),
  );
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const isCustom = !!template.is_custom;
  // ``canPreview`` is driven by the backend's ``has_pdf_renderer`` flag
  // (worldwide-parameterized) so jurisdictions outside the original 7
  // built-ins (UAE / RU / DE / IN / etc.) inherit the same gating
  // without any frontend changes. Falls back to the legacy slug list
  // when the server omits the flag (older API contract).
  const canPreview = !isCustom && templateHasPdfRenderer(template);
  const docTypeKey = String(template.doc_type);

  // SPA is the only template that injects jurisdiction clauses, so the
  // regulator dropdown only meaningfully affects sales_contract.
  const regulatorMatters = template.doc_type === 'sales_contract';

  const [isDefault, setIsDefault] = useState<boolean>(() => {
    if (!isCustom || !template.id || !activeDevId) return false;
    return getDefaultTemplateForDev(activeDevId, docTypeKey) === template.id;
  });
  useEffect(() => {
    if (!isCustom || !template.id || !activeDevId) {
      setIsDefault(false);
      return;
    }
    setIsDefault(
      getDefaultTemplateForDev(activeDevId, docTypeKey) === template.id,
    );
  }, [isCustom, template.id, docTypeKey, activeDevId]);

  const openSamplePreview = async () => {
    if (!canPreview) return;
    setBusy(true);
    try {
      const res = await sampleDocumentPreview(
        template.doc_type as PropDevDocType,
        locale,
        regulator,
      );
      const bin = atob(res.base64);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      const blob = new Blob([arr], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const win = window.open(url, '_blank', 'noopener,noreferrer');
      if (!win) {
        addToast({
          type: 'warning',
          title: t('property_dev.doc_templates.popup_blocked', {
            defaultValue:
              'Browser blocked the preview window. Allow pop-ups for this site and retry.',
          }),
        });
        const a = document.createElement('a');
        a.href = url;
        a.download = res.filename;
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const downloadSample = async () => {
    if (!canPreview) return;
    setBusy(true);
    try {
      const res = await sampleDocumentPreview(
        template.doc_type as PropDevDocType,
        locale,
        regulator,
      );
      const bin = atob(res.base64);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      const blob = new Blob([arr], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const downloadCustom = () => {
    if (!template.id) return;
    window.open(customDocumentTemplateDownloadUrl(template.id), '_blank');
  };

  const doDelete = async () => {
    if (!template.id) return;
    setBusy(true);
    try {
      await deleteCustomDocumentTemplate(template.id);
      addToast({
        type: 'success',
        title: t('property_dev.doc_templates.delete_ok', {
          defaultValue: 'Template deleted',
        }),
      });
      setConfirmDelete(false);
      onAfterDelete();
      qc.invalidateQueries({ queryKey: ['propdev', 'document-templates'] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const toggleDefault = () => {
    if (!isCustom || !template.id || !activeDevId) return;
    const next = !isDefault;
    setDefaultTemplateForDev(
      activeDevId,
      docTypeKey,
      next ? template.id : null,
    );
    setIsDefault(next);
    addToast({
      type: 'info',
      title: next
        ? t('property_dev.doc_templates.default_set', {
            defaultValue: 'Set as default for this development',
          })
        : t('property_dev.doc_templates.default_cleared', {
            defaultValue: 'Default cleared',
          }),
    });
  };

  const filteredRegulators = useMemo(
    () => (regulatorMatters ? regulators : ['NONE']),
    [regulatorMatters, regulators],
  );

  return (
    <Card className="overflow-hidden">
      <header className="flex items-start gap-3 border-b border-border-light px-4 py-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          {ICON_FOR_DOC[docTypeKey] ?? <FileText size={16} />}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold text-content-primary truncate">
            {isCustom
              ? template.title
              : t(`property_dev.doc_templates.types.${docTypeKey}.title`, {
                  defaultValue: template.title,
                })}
          </h2>
          <p className="mt-0.5 text-xs text-content-tertiary line-clamp-3">
            {template.description ||
              t('property_dev.doc_templates.no_description', {
                defaultValue: 'No description.',
              })}
          </p>
        </div>
        {isCustom ? (
          <Badge variant="success">
            {t('property_dev.doc_templates.badge_custom', {
              defaultValue: 'Custom',
            })}
          </Badge>
        ) : (
          <Badge variant="blue">
            {t('property_dev.doc_templates.badge_builtin', {
              defaultValue: 'Built-in',
            })}
          </Badge>
        )}
      </header>
      <div className="px-4 py-3 space-y-3 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="uppercase tracking-wide text-content-tertiary">
              {t('property_dev.doc_templates.triggered_by', {
                defaultValue: 'Triggered by',
              })}
            </p>
            <p className="mt-0.5 font-mono text-content-secondary break-all">
              {template.trigger}
            </p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-content-tertiary">
              {t('property_dev.doc_templates.pages', { defaultValue: 'Pages' })}
            </p>
            <p className="mt-0.5 text-content-primary">{template.pages}</p>
          </div>
        </div>

        {canPreview && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
            <div>
              <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                <Globe2 size={10} className="mr-1 inline" />
                {t('property_dev.doc_templates.locale', {
                  defaultValue: 'Locale',
                })}
              </label>
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              >
                {locales.map((l) => (
                  <option key={l} value={l}>
                    {l.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor={`tpl-regulator-${docTypeKey}`}
                className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
              >
                <ShieldAlert size={10} className="mr-1 inline" />
                {t('property_dev.doc_templates.regulator', {
                  defaultValue: 'Regulator',
                })}
              </label>
              {/* Combobox — backend supplies the known list (RERA /
                  MAHARERA / 214_FZ / CMA / …) but jurisdictions without
                  a RERA-equivalent (most of the world) can type their
                  own authority code or just "NONE". */}
              <SlugCombobox
                id={`tpl-regulator-${docTypeKey}`}
                value={regulator}
                onChange={setRegulator}
                presets={filteredRegulators}
                disabled={!regulatorMatters}
                title={
                  regulatorMatters
                    ? t('property_dev.doc_templates.regulator_hint', {
                        defaultValue:
                          'Pick a preset or type any compliance authority code.',
                      })
                    : t('property_dev.doc_templates.regulator_na', {
                        defaultValue:
                          'Regulator clauses only affect the Sale-Purchase Agreement.',
                      })
                }
                ariaLabel={t('property_dev.doc_templates.regulator', {
                  defaultValue: 'Regulator',
                })}
              />
            </div>
          </div>
        )}

        {/* Per-development override for custom templates */}
        {isCustom && template.id && activeDevId && (
          <div className="flex items-center justify-between rounded-md bg-surface-secondary px-2 py-1.5">
            <span className="text-[11px] text-content-secondary">
              {t('property_dev.doc_templates.default_for_dev', {
                defaultValue:
                  'Set as default for current development ({{dev}})',
                dev: activeDevId.slice(0, 8) + '…',
              })}
            </span>
            <button
              type="button"
              onClick={toggleDefault}
              className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                isDefault
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                  : 'bg-surface-tertiary text-content-tertiary hover:bg-surface-tertiary/80'
              }`}
              data-testid={`toggle-default-${template.id}`}
            >
              {isDefault ? <CheckCircle2 size={11} /> : null}
              {isDefault
                ? t('common.yes', { defaultValue: 'Default' })
                : t('property_dev.doc_templates.set_default', {
                    defaultValue: 'Set default',
                  })}
            </button>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge variant="neutral">
            {t('property_dev.doc_templates.entity', { defaultValue: 'Entity' })}:{' '}
            {template.entity}
          </Badge>
          <div className="flex items-center gap-2">
            {canPreview && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={12} />}
                  onClick={downloadSample}
                  disabled={busy}
                  data-testid={`download-sample-${docTypeKey}`}
                >
                  {t('property_dev.doc_templates.download_sample', {
                    defaultValue: 'Download sample',
                  })}
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  icon={
                    busy ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Eye size={12} />
                    )
                  }
                  onClick={openSamplePreview}
                  loading={busy}
                  data-testid={`preview-sample-${docTypeKey}`}
                >
                  {t('property_dev.doc_templates.preview_sample', {
                    defaultValue: 'Preview',
                  })}
                </Button>
              </>
            )}
            {isCustom && template.id && (
              <>
                {/* Edit button — only for rows whose content_type is
                    HTML / Markdown / plain text. Binary uploads (.docx,
                    .pdf, .odt) get 415 from the GET-content endpoint so
                    we don't even surface the button. */}
                {(template.content_type === 'text/html' ||
                  template.content_type === 'text/markdown' ||
                  template.content_type === 'text/plain') && (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Edit3 size={12} />}
                    onClick={() => onOpenEditor({
                      editingTemplateId: template.id!,
                      initialName: template.title,
                      initialDocType: String(template.doc_type),
                      initialEntity: template.entity,
                      initialContentType:
                        (template.content_type as CustomTemplateTextContentType) ||
                        'text/html',
                    })}
                    disabled={busy}
                    data-testid={`edit-custom-${template.id}`}
                  >
                    {t('common.edit', { defaultValue: 'Edit' })}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={12} />}
                  onClick={downloadCustom}
                  disabled={busy}
                  data-testid={`download-custom-${template.id}`}
                >
                  {t('property_dev.doc_templates.download_custom', {
                    defaultValue: 'Download',
                  })}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={12} />}
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy}
                  data-testid={`delete-custom-${template.id}`}
                >
                  {t('common.delete', { defaultValue: 'Delete' })}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          open={confirmDelete}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={doDelete}
          title={t('property_dev.doc_templates.delete_title', {
            defaultValue: 'Delete this template?',
          })}
          message={t('property_dev.doc_templates.delete_message', {
            defaultValue:
              'The file will be removed from storage and any per-development defaults pointing at it will fall back to the built-in template.',
          })}
          confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
          variant="danger"
          loading={busy}
        />
      )}
    </Card>
  );
}

/* ── In-browser template editor ────────────────────────────────────── */

/**
 * Tiny syntax-highlighted preview of an HTML/MD source string.
 *
 * Avoids any heavy editor framework — `<textarea>` for the source
 * (preserves selection / clipboard / native a11y), a sibling
 * <div className="prose"> for the live preview (HTML rendered raw via
 * dangerouslySetInnerHTML, or markdown turned into <pre> for safety).
 *
 * The preview pane is deliberately not a full sandbox iframe — the
 * template will be re-rendered server-side at document-generation time
 * (with proper variable interpolation + reportlab), so this preview is
 * advisory only. Users authoring HTML get a friendly visual hint, but
 * the final document is server-controlled.
 */
const ALLOWED_CONTENT_TYPES: { value: CustomTemplateTextContentType; label: string }[] = [
  { value: 'text/html', label: 'HTML' },
  { value: 'text/markdown', label: 'Markdown' },
  { value: 'text/plain', label: 'Plain text' },
];

/**
 * Fallback preset lists used when the backend response doesn't yet
 * include ``doc_type_presets`` / ``entity_presets`` (older API
 * contract). These match the shipping defaults; the source-of-truth
 * lives in ``backend/.../property_dev/router.py``.
 *
 * IMPORTANT: these are SUGGESTIONS only. The combobox accepts any
 * tenant-supplied slug — Brazilian ``escritura_publica``, Japanese
 * ``juyo_jiko_setsumeisho``, Mexican ``acta_de_entrega``, etc. — so
 * the platform isn't locked to the original 7-country list.
 */
const DOC_TYPE_PRESETS_FALLBACK: ReadonlyArray<string> = [
  'custom',
  'reservation_receipt',
  'sales_contract',
  'payment_receipt',
  'handover_certificate',
  'warranty_certificate',
  'noc',
  'snag_report',
  'invoice',
  'payment_reminder',
  'kyc_checklist',
  'brokerage_commission',
  'tenant_lease_agreement',
  'move_in_checklist',
  'mortgage_clearance_letter',
  'title_deed_transfer_request',
  'escrow_release_authorization',
  'refund_authorization',
];

const ENTITY_PRESETS_FALLBACK: ReadonlyArray<string> = [
  'custom', 'reservation', 'sales_contract', 'instalment', 'handover',
  'snag', 'broker', 'buyer', 'plot', 'development', 'tenant',
];

function TemplateEditorModal({
  session,
  variableGroups,
  activeDevId,
  docTypePresets,
  entityPresets,
  onClose,
  onSaved,
}: {
  session: EditorSession;
  variableGroups: DocumentTemplateVariableGroup[];
  activeDevId: string | null;
  docTypePresets: ReadonlyArray<string>;
  entityPresets: ReadonlyArray<string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEditing = !!session.editingTemplateId;

  const [name, setName] = useState(session.initialName ?? '');
  const [docType, setDocType] = useState<string>(
    session.initialDocType ?? 'custom',
  );
  const [entity, setEntity] = useState<string>(session.initialEntity ?? 'custom');
  const [contentType, setContentType] = useState<CustomTemplateTextContentType>(
    session.initialContentType ?? 'text/html',
  );
  const [contentText, setContentText] = useState<string>('');
  const [description, setDescription] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(isEditing);
  const [debouncedContent, setDebouncedContent] = useState<string>('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Load existing content when editing.
  useEffect(() => {
    let cancelled = false;
    if (!isEditing || !session.editingTemplateId) {
      setLoading(false);
      // Seed with a friendly HTML starter when creating new.
      setContentText((prev) =>
        prev ||
        '<!-- Property-Development custom template -->\n' +
          '<html>\n' +
          '  <body style="font-family: Helvetica, Arial, sans-serif; padding: 24px;">\n' +
          '    <h1>{development.name}</h1>\n' +
          '    <p>Buyer: {buyer.full_name}</p>\n' +
          '    <p>Unit: {plot.plot_number} ({plot.area_m2} m²)</p>\n' +
          '    <p>Contract: {contract.contract_number} - {contract.total_value} {contract.currency}</p>\n' +
          '  </body>\n' +
          '</html>',
      );
      return;
    }
    setLoading(true);
    getCustomDocumentTemplateContent(session.editingTemplateId)
      .then((res) => {
        if (cancelled) return;
        setName(res.title);
        setDocType(res.doc_type);
        setEntity(res.entity);
        setDescription(res.description);
        const ct = (res.content_type as CustomTemplateTextContentType) || 'text/html';
        setContentType(ct);
        setContentText(res.content_text);
      })
      .catch((err) => {
        if (cancelled) return;
        addToast({ type: 'error', title: getErrorMessage(err) });
        onClose();
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isEditing, session.editingTemplateId, addToast, onClose]);

  // Debounce the preview pane re-render to keep typing snappy.
  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedContent(contentText), 250);
    return () => window.clearTimeout(handle);
  }, [contentText]);

  const insertAtCursor = useCallback((snippet: string) => {
    const ta = textareaRef.current;
    if (!ta) {
      setContentText((prev) => prev + snippet);
      return;
    }
    const start = ta.selectionStart ?? ta.value.length;
    const end = ta.selectionEnd ?? ta.value.length;
    const before = ta.value.slice(0, start);
    const after = ta.value.slice(end);
    const next = before + snippet + after;
    setContentText(next);
    // Move cursor to AFTER the inserted snippet on next tick.
    queueMicrotask(() => {
      if (!textareaRef.current) return;
      textareaRef.current.focus();
      const caret = start + snippet.length;
      textareaRef.current.setSelectionRange(caret, caret);
    });
  }, []);

  const submit = async () => {
    if (!name.trim()) {
      addToast({
        type: 'warning',
        title: t('property_dev.doc_templates.editor_no_name', {
          defaultValue: 'Give the template a name',
        }),
      });
      return;
    }
    if (!contentText.trim()) {
      addToast({
        type: 'warning',
        title: t('property_dev.doc_templates.editor_no_body', {
          defaultValue: 'Template body is empty',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await saveTextCustomDocumentTemplate({
        template_id: session.editingTemplateId ?? undefined,
        name: name.trim(),
        doc_type: docType,
        entity,
        description,
        content_type: contentType,
        content_text: contentText,
        development_id: activeDevId ?? undefined,
      });
      addToast({
        type: 'success',
        title: isEditing
          ? t('property_dev.doc_templates.editor_updated', {
              defaultValue: 'Template updated',
            })
          : t('property_dev.doc_templates.editor_created', {
              defaultValue: 'Template created',
            }),
      });
      onSaved();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  // Render the preview pane. For HTML we honour user markup verbatim
  // (the preview is sandboxed inside the modal body — no script tags are
  // executed against the host because dangerouslySetInnerHTML in React
  // strips <script> at hydration on most modern browsers, and our
  // backend re-renders the template in a non-JS reportlab pipeline at
  // document-generation time anyway).
  const previewHtml = useMemo(() => {
    if (contentType === 'text/html') return debouncedContent;
    if (contentType === 'text/markdown') {
      // Tiny markdown renderer covering the 95% case (headings, bold,
      // italic, code, paragraphs). Heavy markdown engines would balloon
      // the bundle for what is fundamentally a preview pane.
      let html = debouncedContent
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      html = html.replace(/^###### (.*)$/gm, '<h6>$1</h6>');
      html = html.replace(/^##### (.*)$/gm, '<h5>$1</h5>');
      html = html.replace(/^#### (.*)$/gm, '<h4>$1</h4>');
      html = html.replace(/^### (.*)$/gm, '<h3>$1</h3>');
      html = html.replace(/^## (.*)$/gm, '<h2>$1</h2>');
      html = html.replace(/^# (.*)$/gm, '<h1>$1</h1>');
      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
      html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
      html = html.split(/\n{2,}/).map((p) =>
        p.startsWith('<h') ? p : `<p>${p.replace(/\n/g, '<br/>')}</p>`,
      ).join('\n');
      return html;
    }
    // plain text — escape and wrap in <pre>.
    return `<pre style="white-space: pre-wrap; font-family: monospace;">${
      debouncedContent
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
    }</pre>`;
  }, [contentType, debouncedContent]);

  return (
    <WideModal
      open={true}
      onClose={onClose}
      title={
        isEditing
          ? t('property_dev.doc_templates.editor_title_edit', {
              defaultValue: 'Edit custom template',
            })
          : t('property_dev.doc_templates.editor_title_new', {
              defaultValue: 'New custom template',
            })
      }
      size="full"
      busy={busy}
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-xs text-content-tertiary">
            {t('property_dev.doc_templates.editor_footer_hint', {
              defaultValue:
                'Tip: click a variable chip to insert it at the cursor. The preview re-renders 250 ms after typing stops.',
            })}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              loading={busy}
              disabled={busy || loading}
              data-testid="editor-save"
            >
              {isEditing
                ? t('common.save', { defaultValue: 'Save' })
                : t('property_dev.doc_templates.editor_create_btn', {
                    defaultValue: 'Create template',
                  })}
            </Button>
          </div>
        </div>
      }
    >
      {loading ? (
        <SkeletonText lines={10} />
      ) : (
        <div className="space-y-3">
          {/* Metadata row */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-3">
            <div className="md:col-span-4">
              <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                {t('property_dev.doc_templates.upload_field_name', {
                  defaultValue: 'Display name',
                })}
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                data-testid="editor-name"
              />
            </div>
            <div className="md:col-span-3">
              <label
                htmlFor="editor-doctype"
                className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
              >
                {t('property_dev.doc_templates.upload_field_doctype', {
                  defaultValue: 'Doc type',
                })}
              </label>
              <SlugCombobox
                id="editor-doctype"
                value={docType}
                onChange={setDocType}
                presets={docTypePresets}
                placeholder={t('property_dev.doc_templates.doctype_placeholder', {
                  defaultValue: 'pick or type any slug',
                })}
                data-testid="editor-doctype"
                ariaLabel={t('property_dev.doc_templates.upload_field_doctype', {
                  defaultValue: 'Doc type',
                })}
              />
            </div>
            <div className="md:col-span-2">
              <label
                htmlFor="editor-entity"
                className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
              >
                {t('property_dev.doc_templates.upload_field_entity', {
                  defaultValue: 'Entity',
                })}
              </label>
              <SlugCombobox
                id="editor-entity"
                value={entity}
                onChange={setEntity}
                presets={entityPresets}
                placeholder={t('property_dev.doc_templates.entity_placeholder', {
                  defaultValue: 'pick or type any slug',
                })}
                data-testid="editor-entity"
                ariaLabel={t('property_dev.doc_templates.upload_field_entity', {
                  defaultValue: 'Entity',
                })}
              />
            </div>
            <div className="md:col-span-3">
              <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                {t('property_dev.doc_templates.editor_content_type', {
                  defaultValue: 'Source format',
                })}
              </label>
              <select
                value={contentType}
                onChange={(e) =>
                  setContentType(e.target.value as CustomTemplateTextContentType)
                }
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                data-testid="editor-content-type"
              >
                {ALLOWED_CONTENT_TYPES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="md:col-span-12">
              <label className="block text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                {t('property_dev.doc_templates.upload_field_desc', {
                  defaultValue: 'Description (optional)',
                })}
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                data-testid="editor-description"
              />
            </div>
          </div>

          {/* Variable picker chips */}
          <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
            <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-content-tertiary">
              <Code2 size={12} />
              {t('property_dev.doc_templates.editor_variables_picker', {
                defaultValue: 'Insert a variable',
              })}
            </div>
            <div className="mt-2 max-h-40 overflow-auto space-y-2">
              {variableGroups.length === 0 ? (
                <p className="text-[11px] text-content-tertiary">
                  {t('property_dev.doc_templates.variables_empty', {
                    defaultValue:
                      'No variable documentation is available - load this page from a tenant with property-dev enabled.',
                  })}
                </p>
              ) : (
                variableGroups.map((g) => (
                  <div key={g.group}>
                    <p className="text-[11px] font-semibold text-content-secondary mb-1">
                      {g.label}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {g.vars.map((v) => (
                        <button
                          key={v.key}
                          type="button"
                          title={v.desc}
                          onClick={() => insertAtCursor(v.key)}
                          className="inline-flex items-center rounded-full border border-oe-blue/30 bg-oe-blue/5 px-2 py-0.5 text-[11px] text-oe-blue hover:bg-oe-blue/15 hover:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                          data-testid={`var-chip-${v.key}`}
                        >
                          <code>{v.key}</code>
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Split editor — source on the left, preview on the right.
              Both panes share the same fixed height so the modal stays
              scroll-anchored at the metadata row. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 h-[55vh] min-h-[360px]">
            <div className="flex flex-col">
              <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                <span>
                  {t('property_dev.doc_templates.editor_source_pane', {
                    defaultValue: 'Source',
                  })}
                </span>
                <span className="font-mono">{contentType}</span>
              </div>
              <textarea
                ref={textareaRef}
                value={contentText}
                onChange={(e) => setContentText(e.target.value)}
                spellCheck={false}
                className="flex-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2 font-mono text-[12px] leading-5 text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
                data-testid="editor-source"
              />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wide text-content-tertiary mb-1">
                <span>
                  {t('property_dev.doc_templates.editor_preview_pane', {
                    defaultValue: 'Live preview (advisory - final render is server-side)',
                  })}
                </span>
              </div>
              <div
                className="flex-1 w-full overflow-auto rounded-lg border border-border bg-white text-black px-4 py-3 text-sm"
                data-testid="editor-preview"
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{ __html: previewHtml }}
              />
            </div>
          </div>
        </div>
      )}
    </WideModal>
  );
}

function VariablesModal({
  open,
  onClose,
  groups,
}: {
  open: boolean;
  onClose: () => void;
  groups: DocumentTemplateVariableGroup[];
}) {
  const { t } = useTranslation();
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('property_dev.doc_templates.variables_title', {
        defaultValue: 'Template variables',
      })}
      size="lg"
    >
      <p className="px-1 text-sm text-content-secondary">
        {t('property_dev.doc_templates.variables_intro', {
          defaultValue:
            'Use these placeholders inside your .docx / .html templates. The document-generation events interpolate them at render time from the active development, plot, buyer, contract, reservation, instalment and handover.',
        })}
      </p>
      <div className="mt-3 space-y-3">
        {groups.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('property_dev.doc_templates.variables_empty', {
              defaultValue:
                'No variable documentation is available - load this page from a tenant with property-dev enabled.',
            })}
          </p>
        ) : (
          groups.map((g) => (
            <WideModalSection key={g.group} title={g.label} columns={2}>
              {g.vars.map((v) => (
                <div
                  key={v.key}
                  className="flex flex-col rounded-md border border-border-light bg-surface-secondary px-2 py-1.5"
                >
                  <code className="text-xs text-oe-blue">{v.key}</code>
                  <span className="text-[11px] text-content-tertiary">
                    {v.desc}
                  </span>
                </div>
              ))}
            </WideModalSection>
          ))
        )}
      </div>
    </WideModal>
  );
}

/**
 * Renders one chip per supported locale with native+English names and a
 * translation-source badge. Each chip is clickable — opens the locale
 * editor so the user can read/upload/delete the tenant override.
 */
function LocaleStatusList({
  statuses,
  fallback,
  onEdit,
}: {
  statuses?: DocumentTemplateLocaleStatus[];
  fallback: string[];
  onEdit: (code: string) => void;
}) {
  const { t } = useTranslation();
  if (statuses && statuses.length > 0) {
    return (
      <>
        {statuses.map((s) => {
          const variant: 'success' | 'blue' | 'warning' =
            s.source === 'override'
              ? 'success'
              : s.source === 'bundled' && s.is_translated
                ? 'blue'
                : 'warning';
          const title =
            s.source === 'override'
              ? t('property_dev.doc_templates.locale_source_override', {
                  defaultValue:
                    'Tenant override active ({{n}} keys). Click to edit or revert.',
                  n: s.key_count,
                })
              : s.source === 'bundled' && s.is_translated
                ? t('property_dev.doc_templates.locale_source_bundled', {
                    defaultValue:
                      'Built-in translation ({{n}} keys). Click to override.',
                    n: s.key_count,
                  })
                : t('property_dev.doc_templates.locale_source_fallback', {
                    defaultValue:
                      'No translation found - PDF falls back to English. Click to add.',
                  });
          const label = `${s.native_name} (${s.english_name})`;
          return (
            <button
              key={s.code}
              type="button"
              onClick={() => onEdit(s.code)}
              title={title}
              className="group inline-flex items-center gap-1"
              data-testid={`locale-chip-${s.code}`}
            >
              <Badge variant={variant}>
                <span className="font-semibold">{s.code.toUpperCase()}</span>
                <span className="ml-1 text-[10px] font-normal opacity-80">
                  {label}
                </span>
              </Badge>
            </button>
          );
        })}
      </>
    );
  }
  // Legacy fallback when older API doesn't return locale_status.
  return (
    <>
      {fallback.map((l) => (
        <button key={l} type="button" onClick={() => onEdit(l)}>
          <Badge variant="blue">{l.toUpperCase()}</Badge>
        </button>
      ))}
    </>
  );
}

/**
 * Modal to inspect / upload / delete tenant locale-override JSON. PUT
 * stores the JSON under ``uploads/property_dev/document_locales/<code>.json``
 * and the next PDF render picks it up automatically.
 */
function LocaleEditorModal({
  initialCode,
  statuses,
  onClose,
  onSaved,
}: {
  initialCode: string | null;
  statuses: DocumentTemplateLocaleStatus[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [code, setCode] = useState<string>(initialCode ?? '');
  const [jsonText, setJsonText] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeStatus, setActiveStatus] = useState<
    DocumentTemplateLocaleStatus | null
  >(null);

  // Load the current merged JSON whenever the picked code changes.
  useEffect(() => {
    const trimmed = code.trim().toLowerCase();
    if (!trimmed) {
      setJsonText('');
      setActiveStatus(null);
      return;
    }
    setLoading(true);
    getDocumentTemplateLocale(trimmed)
      .then((payload) => {
        setJsonText(JSON.stringify(payload.data, null, 2));
        const match = statuses.find((s) => s.code === trimmed);
        setActiveStatus(match ?? null);
      })
      .catch((err) => {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: getErrorMessage(err),
        });
        setJsonText('');
      })
      .finally(() => setLoading(false));
  }, [code, statuses, addToast, t]);

  const save = async () => {
    const trimmed = code.trim().toLowerCase();
    if (!trimmed) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      addToast({
        type: 'error',
        title: t('property_dev.doc_templates.locale_invalid_json_title', {
          defaultValue: 'Invalid JSON',
        }),
        message: t('property_dev.doc_templates.locale_invalid_json_msg', {
          defaultValue: 'Fix the JSON syntax before saving.',
        }),
      });
      return;
    }
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('property_dev.doc_templates.locale_invalid_shape', {
          defaultValue: 'Locale JSON must be an object at the top level.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await putDocumentTemplateLocale(trimmed, parsed);
      addToast({
        type: 'success',
        title: t('common.saved', { defaultValue: 'Saved' }),
        message: t('property_dev.doc_templates.locale_saved_msg', {
          defaultValue: 'Tenant override stored - PDFs will use it on next render.',
        }),
      });
      onSaved();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    } finally {
      setBusy(false);
    }
  };

  const revert = async () => {
    const trimmed = code.trim().toLowerCase();
    if (!trimmed) return;
    setBusy(true);
    try {
      await deleteDocumentTemplateLocaleOverride(trimmed);
      addToast({
        type: 'success',
        title: t('property_dev.doc_templates.locale_reverted', {
          defaultValue: 'Override removed',
        }),
        message: t('property_dev.doc_templates.locale_reverted_msg', {
          defaultValue: 'Back to the bundled translation (or English fallback).',
        }),
      });
      onSaved();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    } finally {
      setBusy(false);
    }
  };

  const downloadStarter = async () => {
    setBusy(true);
    try {
      const en = await getDocumentTemplateLocale('en');
      setJsonText(JSON.stringify(en.data, null, 2));
      addToast({
        type: 'info',
        title: t('property_dev.doc_templates.locale_starter_loaded', {
          defaultValue: 'Loaded English as starter',
        }),
        message: t('property_dev.doc_templates.locale_starter_loaded_msg', {
          defaultValue: 'Translate the values, keep the keys.',
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('property_dev.doc_templates.locale_editor_title', {
        defaultValue: 'Document-template translations',
      })}
      size="xl"
    >
      <div className="space-y-3 p-4 text-sm">
        <p className="text-content-secondary">
          {t('property_dev.doc_templates.locale_editor_intro', {
            defaultValue:
              'Built-in JSON ships with the platform; uploading an override here stores a tenant-owned copy that wins at PDF render time. Delete the override to revert.',
          })}
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <label
              htmlFor="locale-editor-code"
              className="block text-[11px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
            >
              {t('property_dev.doc_templates.locale_code_label', {
                defaultValue: 'Locale code (e.g. de, ja, pt-BR)',
              })}
            </label>
            <input
              id="locale-editor-code"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="de"
              autoFocus={!initialCode}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={downloadStarter}
            disabled={busy}
            icon={<Download size={14} />}
          >
            {t('property_dev.doc_templates.locale_load_en', {
              defaultValue: 'Load English as starter',
            })}
          </Button>
        </div>
        {activeStatus && (
          <div className="rounded-md bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
            <div className="font-medium text-content-primary">
              {activeStatus.native_name}{' '}
              <span className="text-content-tertiary">
                ({activeStatus.english_name})
              </span>
            </div>
            <div className="mt-1">
              {t('property_dev.doc_templates.locale_source', {
                defaultValue: 'Source',
              })}
              :{' '}
              <strong>
                {activeStatus.source === 'override'
                  ? t('property_dev.doc_templates.locale_source_override_short', {
                      defaultValue: 'tenant override',
                    })
                  : activeStatus.source === 'bundled'
                    ? t('property_dev.doc_templates.locale_source_bundled_short', {
                        defaultValue: 'bundled (built-in)',
                      })
                    : t(
                        'property_dev.doc_templates.locale_source_fallback_short',
                        { defaultValue: 'falls back to English' },
                      )}
              </strong>{' '}
              · {activeStatus.key_count} / {activeStatus.en_key_count}{' '}
              {t('property_dev.doc_templates.locale_keys', {
                defaultValue: 'keys',
              })}
              {activeStatus.rtl && (
                <>
                  {' '}
                  · <Badge variant="neutral">RTL</Badge>
                </>
              )}
            </div>
          </div>
        )}
        <div>
          <label
            htmlFor="locale-editor-json"
            className="block text-[11px] font-medium uppercase tracking-wide text-content-tertiary mb-1"
          >
            {t('property_dev.doc_templates.locale_json_label', {
              defaultValue: 'Translation JSON',
            })}
          </label>
          <textarea
            id="locale-editor-json"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            disabled={loading || busy}
            rows={20}
            spellCheck={false}
            className="w-full rounded-lg border border-border bg-surface-primary p-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            placeholder={
              loading
                ? t('common.loading', { defaultValue: 'Loading…' })
                : '{\n  "labels": {\n    "buyer": "Käufer"\n  }\n}'
            }
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] text-content-tertiary max-w-md">
            {t('property_dev.doc_templates.locale_hint', {
              defaultValue:
                'Tip: load English as a starter, translate the leaf values, keep the keys, then save. Empty keys silently fall back to English at render time.',
            })}
          </p>
          <div className="flex items-center gap-2">
            {activeStatus?.source === 'override' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={revert}
                disabled={busy}
                icon={<Trash2 size={14} />}
              >
                {t('property_dev.doc_templates.locale_revert', {
                  defaultValue: 'Remove override',
                })}
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={save}
              disabled={busy || !code.trim() || !jsonText.trim()}
              loading={busy}
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </div>
      </div>
    </WideModal>
  );
}
