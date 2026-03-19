import { useState, useCallback, useRef, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  ArrowRight,
  Download,
  RotateCcw,
  Save,
  AlertCircle,
  Zap,
  Pencil,
  Camera,
  FileText,
  FileSpreadsheet,
  HardHat,
  ClipboardPaste,
  Upload,
  X,
  Image as ImageIcon,
  FileArchive,
  Info,
} from 'lucide-react';
import { Card, CardContent, Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { aiApi, type QuickEstimateRequest, type EstimateJobResponse, type EstimateItem } from './api';
import { apiGet } from '@/shared/lib/api';

// ── Tab types ────────────────────────────────────────────────────────────────

type InputTab = 'text' | 'photo' | 'pdf' | 'excel' | 'cad' | 'paste';

interface TabDef {
  id: InputTab;
  label: string;
  labelKey: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  { id: 'text', label: 'Text', labelKey: 'ai.tab_text', icon: <Pencil size={16} /> },
  { id: 'photo', label: 'Photo', labelKey: 'ai.tab_photo', icon: <Camera size={16} /> },
  { id: 'pdf', label: 'PDF', labelKey: 'ai.tab_pdf', icon: <FileText size={16} /> },
  { id: 'excel', label: 'Excel', labelKey: 'ai.tab_excel', icon: <FileSpreadsheet size={16} /> },
  { id: 'cad', label: 'CAD', labelKey: 'ai.tab_cad', icon: <HardHat size={16} /> },
  { id: 'paste', label: 'Paste', labelKey: 'ai.tab_paste', icon: <ClipboardPaste size={16} /> },
];

// ── Option data ──────────────────────────────────────────────────────────────

const BUILDING_TYPES = [
  { value: '', label: 'Any type' },
  { value: 'residential', label: 'Residential' },
  { value: 'commercial_office', label: 'Commercial / Office' },
  { value: 'industrial', label: 'Industrial' },
  { value: 'retail', label: 'Retail' },
  { value: 'healthcare', label: 'Healthcare' },
  { value: 'education', label: 'Education' },
  { value: 'hospitality', label: 'Hospitality' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'mixed_use', label: 'Mixed Use' },
];

const STANDARDS = [
  { value: '', label: 'Auto-detect' },
  { value: 'din276', label: 'DIN 276' },
  { value: 'nrm', label: 'NRM 1/2' },
  { value: 'masterformat', label: 'MasterFormat' },
  { value: 'uniformat', label: 'UniFormat' },
];

const CURRENCIES = [
  { value: '', label: 'Auto' },
  { value: 'EUR', label: 'EUR' },
  { value: 'USD', label: 'USD' },
  { value: 'GBP', label: 'GBP' },
  { value: 'CHF', label: 'CHF' },
  { value: 'CAD', label: 'CAD' },
  { value: 'AUD', label: 'AUD' },
  { value: 'JPY', label: 'JPY' },
  { value: 'CNY', label: 'CNY' },
  { value: 'INR', label: 'INR' },
  { value: 'AED', label: 'AED' },
];

// ── File accept maps ─────────────────────────────────────────────────────────

type FileTab = 'photo' | 'pdf' | 'excel' | 'cad';

const ACCEPT_MAP: { [K in FileTab]: string } = {
  photo: '.jpg,.jpeg,.png,.tiff,.webp',
  pdf: '.pdf',
  excel: '.xlsx,.xls,.csv',
  cad: '.rvt,.ifc,.dwg,.dgn',
};

const FORMAT_LABELS: { [K in FileTab]: string } = {
  photo: 'JPG, PNG, TIFF, WebP',
  pdf: 'PDF',
  excel: 'Excel (.xlsx), CSV (.csv)',
  cad: 'Revit (.rvt), IFC (.ifc), DWG (.dwg), DGN (.dgn)',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatNumber(n: number, currency?: string): string {
  try {
    return new Intl.NumberFormat('en-US', {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toLocaleString();
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

// ── Shimmer loading rows ─────────────────────────────────────────────────────

function ShimmerRow() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-3">
        <div className="h-4 w-12 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-48 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-8 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-14 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-16 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-20 rounded bg-surface-tertiary" />
      </td>
    </tr>
  );
}

function LoadingState() {
  return (
    <div className="animate-card-in" style={{ animationDelay: '100ms' }}>
      <Card>
        <div className="px-6 pt-6 pb-2">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle">
              <Sparkles size={16} className="text-oe-blue animate-pulse" />
            </div>
            <div>
              <p className="text-sm font-semibold text-content-primary">
                AI is analyzing your input...
              </p>
              <p className="text-xs text-content-tertiary">
                Generating cost breakdown and quantities
              </p>
            </div>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div className="h-full w-1/3 animate-shimmer rounded-full bg-oe-blue opacity-60 bg-[length:200%_100%]" />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-left">
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  Pos
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  Description
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  Unit
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  Qty
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  Rate
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 8 }).map((_, i) => (
                <ShimmerRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── Save to BOQ dialog ───────────────────────────────────────────────────────

interface SaveDialogProps {
  open: boolean;
  onClose: () => void;
  onSave: (projectId: string, boqName: string) => void;
  saving: boolean;
}

interface ProjectSummary {
  id: string;
  name: string;
}

function SaveToBOQDialog({ open, onClose, onSave, saving }: SaveDialogProps) {
  const { t } = useTranslation();
  const [selectedProject, setSelectedProject] = useState('');
  const [boqName, setBOQName] = useState('AI Quick Estimate');

  const { data: projects } = useQuery({
    queryKey: ['projects-list-simple'],
    queryFn: () => apiGet<{ items: ProjectSummary[] }>('/v1/projects/?page_size=100'),
    enabled: open,
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md animate-card-in rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-content-primary mb-4">
          {t('ai.save_to_boq', { defaultValue: 'Save as BOQ' })}
        </h3>

        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('ai.select_project', { defaultValue: 'Select Project' })}
            </label>
            <select
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none"
            >
              <option value="" disabled>
                {t('ai.choose_project', { defaultValue: '-- Choose a project --' })}
              </option>
              {projects?.items?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('ai.boq_name', { defaultValue: 'BOQ Name' })}
            </label>
            <input
              type="text"
              value={boqName}
              onChange={(e) => setBOQName(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary"
              placeholder={t('ai.boq_name_placeholder', { defaultValue: 'Name for this BOQ...' })}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => onSave(selectedProject, boqName)}
            disabled={!selectedProject || !boqName.trim() || saving}
            loading={saving}
            icon={<Save size={15} />}
          >
            {t('ai.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Results table ────────────────────────────────────────────────────────────

function ResultsTable({ result }: { result: EstimateJobResponse }) {
  const { t } = useTranslation();
  const currency = result.currency || 'EUR';

  let currentCategory = '';

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left">
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide w-20">
              {t('ai.col_pos', { defaultValue: 'Pos' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
              {t('ai.col_description', { defaultValue: 'Description' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide w-16">
              {t('ai.col_unit', { defaultValue: 'Unit' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-24">
              {t('ai.col_qty', { defaultValue: 'Qty' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-28">
              {t('ai.col_rate', { defaultValue: 'Unit Rate' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-32">
              {t('ai.col_total', { defaultValue: 'Total' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {result.items.map((item: EstimateItem, idx: number) => {
            const showCategory = item.category && item.category !== currentCategory;
            if (item.category) currentCategory = item.category;

            return (
              <>
                {showCategory && (
                  <tr key={`cat-${idx}`} className="bg-surface-secondary/50">
                    <td
                      colSpan={6}
                      className="px-4 py-2 text-xs font-semibold text-content-secondary uppercase tracking-wider"
                    >
                      {item.category}
                    </td>
                  </tr>
                )}
                <tr
                  key={item.ordinal}
                  className="border-b border-border-light/50 transition-colors duration-fast hover:bg-surface-secondary/30"
                  style={{ animationDelay: `${idx * 30}ms` }}
                >
                  <td className="px-4 py-3 font-mono text-xs text-content-tertiary">
                    {item.ordinal}
                  </td>
                  <td className="px-4 py-3 text-content-primary">
                    {item.description}
                    {Object.keys(item.classification).length > 0 && (
                      <div className="mt-0.5 flex gap-1">
                        {Object.entries(item.classification).map(([std, code]) => (
                          <Badge key={std} variant="neutral" size="sm">
                            {std}: {code}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-content-secondary">{item.unit}</td>
                  <td className="px-4 py-3 text-right font-mono text-content-primary">
                    {formatNumber(item.quantity)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-content-secondary">
                    {formatNumber(item.unit_rate)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-medium text-content-primary">
                    {formatNumber(item.total)}
                  </td>
                </tr>
              </>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border">
            <td
              colSpan={5}
              className="px-4 py-4 text-right text-base font-semibold text-content-primary"
            >
              {t('ai.grand_total', { defaultValue: 'Grand Total' })}
            </td>
            <td className="px-4 py-4 text-right font-mono text-lg font-bold text-oe-blue">
              {formatNumber(result.total_cost, currency)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ── Drop Zone (reusable file upload area) ────────────────────────────────────

function FileDropZone({
  accept,
  formatLabel,
  onFileSelect,
  disabled,
  hint,
}: {
  accept: string;
  formatLabel: string;
  onFileSelect: (file: File) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect, disabled],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFileSelect(file);
      e.target.value = '';
    },
    [onFileSelect],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`
        flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed
        px-6 py-8 text-center cursor-pointer transition-all duration-200
        ${dragOver ? 'border-oe-blue bg-oe-blue-subtle/30 scale-[1.01]' : 'border-border-light hover:border-content-tertiary hover:bg-surface-secondary/50'}
        ${disabled ? 'opacity-50 pointer-events-none' : ''}
      `}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
        <Upload size={22} className="text-content-tertiary" strokeWidth={1.5} />
      </div>
      <div>
        <p className="text-sm font-medium text-content-primary">
          {t('ai.drop_file', { defaultValue: 'Drop your file here, or click to browse' })}
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          {t('ai.supported_formats', { defaultValue: 'Supports: {{formats}}', formats: formatLabel })}
        </p>
        {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={handleChange}
        disabled={disabled}
      />
    </div>
  );
}

// ── File preview (shows selected file with remove option) ────────────────────

function FilePreview({
  file,
  imagePreviewUrl,
  onRemove,
  disabled,
}: {
  file: File;
  imagePreviewUrl: string | null;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const ext = getFileExtension(file.name);
  const isImage = ['jpg', 'jpeg', 'png', 'tiff', 'webp', 'gif'].includes(ext);

  const iconForExt = () => {
    if (isImage) return <ImageIcon size={20} className="text-oe-blue" />;
    if (ext === 'pdf') return <FileText size={20} className="text-red-500" />;
    if (['xlsx', 'xls', 'csv'].includes(ext))
      return <FileSpreadsheet size={20} className="text-green-600" />;
    if (['rvt', 'ifc', 'dwg', 'dgn'].includes(ext))
      return <FileArchive size={20} className="text-amber-600" />;
    return <FileText size={20} className="text-content-tertiary" />;
  };

  return (
    <div className="mt-4 flex items-center gap-3 rounded-xl bg-surface-secondary px-4 py-3">
      {imagePreviewUrl ? (
        <img
          src={imagePreviewUrl}
          alt={file.name}
          className="h-14 w-14 shrink-0 rounded-lg object-cover border border-border-light"
        />
      ) : (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-primary border border-border-light">
          {iconForExt()}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-content-primary truncate">{file.name}</p>
        <p className="text-xs text-content-tertiary">
          {formatFileSize(file.size)}
          {ext && (
            <>
              {' '}
              <Badge variant="neutral" size="sm" className="ml-1">
                .{ext}
              </Badge>
            </>
          )}
        </p>
      </div>
      {!disabled && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary transition-colors"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}

// ── Selector row (location + currency, compact) ──────────────────────────────

function CompactOptions({
  location,
  setLocation,
  currency,
  setCurrency,
  standard,
  setStandard,
  disabled,
}: {
  location: string;
  setLocation: (v: string) => void;
  currency: string;
  setCurrency: (v: string) => void;
  standard: string;
  setStandard: (v: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const selectClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none';
  const inputClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary';

  return (
    <div className="mt-4 grid grid-cols-3 gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.location', { defaultValue: 'Location' })}
        </label>
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
          className={inputClass}
          disabled={disabled}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.currency_label', { defaultValue: 'Currency' })}
        </label>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className={selectClass}
          disabled={disabled}
        >
          {CURRENCIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.standard_label', { defaultValue: 'Standard' })}
        </label>
        <select
          value={standard}
          onChange={(e) => setStandard(e.target.value)}
          className={selectClass}
          disabled={disabled}
        >
          {STANDARDS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export function QuickEstimatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // Active tab
  const [activeTab, setActiveTab] = useState<InputTab>('text');

  // Text form state
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [currency, setCurrency] = useState('');
  const [standard, setStandard] = useState('');
  const [buildingType, setBuildingType] = useState('');
  const [areaM2, setAreaM2] = useState('');

  // Paste form state
  const [pasteText, setPasteText] = useState('');

  // File state (shared across file tabs)
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  // Result state
  const [result, setResult] = useState<EstimateJobResponse | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  // Check if AI is configured
  const { data: aiSettings } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    retry: false,
  });

  const isConfigured = aiSettings?.status === 'connected';

  // ── File selection handler ────────────────────────────────────────────

  const handleFileSelect = useCallback(
    (file: File) => {
      setSelectedFile(file);
      // Generate image preview for photo tab
      const ext = getFileExtension(file.name);
      if (['jpg', 'jpeg', 'png', 'webp', 'gif', 'tiff'].includes(ext)) {
        const url = URL.createObjectURL(file);
        setImagePreviewUrl(url);
      } else {
        setImagePreviewUrl(null);
      }
    },
    [],
  );

  const handleRemoveFile = useCallback(() => {
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
    }
    setSelectedFile(null);
    setImagePreviewUrl(null);
  }, [imagePreviewUrl]);

  // ── Tab switching (clears file but keeps text/options) ────────────────

  const handleTabChange = useCallback(
    (tab: InputTab) => {
      setActiveTab(tab);
      // Clear file when switching tabs since accept types differ
      if (selectedFile) {
        handleRemoveFile();
      }
    },
    [selectedFile, handleRemoveFile],
  );

  // ── Text estimate mutation ────────────────────────────────────────────

  const textEstimateMutation = useMutation({
    mutationFn: aiApi.quickEstimate,
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('ai.estimate_complete', { defaultValue: 'Estimate generated' }),
        message: t('ai.estimate_complete_msg', {
          defaultValue: `${data.items.length} items in ${(data.duration_ms / 1000).toFixed(1)}s`,
          count: data.items.length,
          duration: (data.duration_ms / 1000).toFixed(1),
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  // ── Photo estimate mutation ───────────────────────────────────────────

  const photoEstimateMutation = useMutation({
    mutationFn: aiApi.photoEstimate,
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('ai.estimate_complete', { defaultValue: 'Estimate generated' }),
        message: t('ai.estimate_complete_msg', {
          defaultValue: `${data.items.length} items in ${(data.duration_ms / 1000).toFixed(1)}s`,
          count: data.items.length,
          duration: (data.duration_ms / 1000).toFixed(1),
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  // ── Save as BOQ mutation ──────────────────────────────────────────────

  const saveMutation = useMutation({
    mutationFn: ({ projectId, boqName }: { projectId: string; boqName: string }) => {
      if (!result) throw new Error('No estimate to save');
      return aiApi.createBOQFromEstimate(result.id, {
        project_id: projectId,
        boq_name: boqName,
      });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      setSaveDialogOpen(false);
      addToast({
        type: 'success',
        title: t('ai.boq_saved', { defaultValue: 'BOQ saved successfully' }),
      });
      navigate(`/boq/${data.boq_id}`);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.save_failed', { defaultValue: 'Failed to save BOQ' }),
        message: err.message,
      });
    },
  });

  // ── Determine if any mutation is pending ──────────────────────────────

  const isPending = textEstimateMutation.isPending || photoEstimateMutation.isPending;
  const isError =
    (textEstimateMutation.isError && !textEstimateMutation.isPending) ||
    (photoEstimateMutation.isError && !photoEstimateMutation.isPending);
  const mutationError =
    (textEstimateMutation.error as Error | null) || (photoEstimateMutation.error as Error | null);

  // ── Submit handlers per tab ───────────────────────────────────────────

  const handleTextSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!description.trim()) return;

      const request: QuickEstimateRequest = {
        description: description.trim(),
      };
      if (location.trim()) request.location = location.trim();
      if (currency) request.currency = currency;
      if (standard) request.classification_standard = standard;
      if (buildingType) request.building_type = buildingType;
      if (areaM2 && Number(areaM2) > 0) request.area_m2 = Number(areaM2);

      setResult(null);
      textEstimateMutation.mutate(request);
    },
    [description, location, currency, standard, buildingType, areaM2, textEstimateMutation],
  );

  const handlePhotoSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    photoEstimateMutation.mutate({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, photoEstimateMutation]);

  const handleFileSubmit = useCallback(() => {
    if (!selectedFile) return;
    // For PDF, Excel, CAD: use photo-estimate endpoint which accepts any file
    // The backend smart-import requires a BOQ ID, so for a standalone estimate
    // we send files through the photo-estimate endpoint which handles various formats.
    setResult(null);
    photoEstimateMutation.mutate({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, photoEstimateMutation]);

  const handlePasteSubmit = useCallback(() => {
    if (!pasteText.trim()) return;

    const request: QuickEstimateRequest = {
      description: `Parse the following BOQ/cost data and generate a structured estimate:\n\n${pasteText.trim()}`,
    };
    if (location.trim()) request.location = location.trim();
    if (currency) request.currency = currency;
    if (standard) request.classification_standard = standard;

    setResult(null);
    textEstimateMutation.mutate(request);
  }, [pasteText, location, currency, standard, textEstimateMutation]);

  // ── Unified submit ────────────────────────────────────────────────────

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      if (e) e.preventDefault();
      switch (activeTab) {
        case 'text':
          if (e) handleTextSubmit(e);
          break;
        case 'photo':
          handlePhotoSubmit();
          break;
        case 'pdf':
        case 'excel':
        case 'cad':
          handleFileSubmit();
          break;
        case 'paste':
          handlePasteSubmit();
          break;
      }
    },
    [activeTab, handleTextSubmit, handlePhotoSubmit, handleFileSubmit, handlePasteSubmit],
  );

  // ── Can submit check ──────────────────────────────────────────────────

  const canSubmit = (() => {
    if (isPending) return false;
    switch (activeTab) {
      case 'text':
        return !!description.trim();
      case 'photo':
      case 'pdf':
      case 'excel':
      case 'cad':
        return !!selectedFile;
      case 'paste':
        return !!pasteText.trim();
      default:
        return false;
    }
  })();

  // ── Submit button label ───────────────────────────────────────────────

  const submitLabel = (() => {
    if (isPending) return t('ai.generating', { defaultValue: 'Generating...' });
    switch (activeTab) {
      case 'text':
        return t('ai.generate', { defaultValue: 'Generate Estimate' });
      case 'photo':
        return t('ai.analyze_photo', { defaultValue: 'Analyze Photo' });
      case 'pdf':
        return t('ai.extract_estimate', { defaultValue: 'Extract & Estimate' });
      case 'excel':
        return t('ai.import_parse', { defaultValue: 'Import & Parse' });
      case 'cad':
        return t('ai.convert_estimate', { defaultValue: 'Convert & Estimate' });
      case 'paste':
        return t('ai.parse_import', { defaultValue: 'Parse & Import' });
      default:
        return t('ai.generate', { defaultValue: 'Generate Estimate' });
    }
  })();

  // ── Reset ─────────────────────────────────────────────────────────────

  const handleReset = useCallback(() => {
    setResult(null);
    setDescription('');
    setLocation('');
    setCurrency('');
    setStandard('');
    setBuildingType('');
    setAreaM2('');
    setPasteText('');
    handleRemoveFile();
    textEstimateMutation.reset();
    photoEstimateMutation.reset();
  }, [handleRemoveFile, textEstimateMutation, photoEstimateMutation]);

  const resetMutationErrors = useCallback(() => {
    textEstimateMutation.reset();
    photoEstimateMutation.reset();
  }, [textEstimateMutation, photoEstimateMutation]);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="animate-card-in" style={{ animationDelay: '0ms' }}>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-oe-blue to-[#7c3aed] shadow-lg shadow-oe-blue/20">
            <Sparkles size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {t('ai.estimate_title', { defaultValue: 'AI Estimate' })}
            </h1>
            <p className="text-sm text-content-secondary">
              {t('ai.estimate_subtitle', {
                defaultValue: 'Create an estimate from any source',
              })}
            </p>
          </div>
        </div>
      </div>

      {/* Not configured warning */}
      {aiSettings && !isConfigured && (
        <div
          className="animate-card-in flex items-center gap-3 rounded-xl border border-semantic-warning/30 bg-semantic-warning-bg px-4 py-3"
          style={{ animationDelay: '50ms' }}
        >
          <AlertCircle size={18} className="shrink-0 text-[#b45309]" />
          <div className="flex-1">
            <p className="text-sm font-medium text-[#b45309]">
              {t('ai.not_configured_title', { defaultValue: 'AI provider not configured' })}
            </p>
            <p className="text-xs text-[#b45309]/80">
              {t('ai.not_configured_msg', {
                defaultValue: 'Set up your API key in Settings to use AI features.',
              })}
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate('/settings')}
            icon={<ArrowRight size={14} />}
            iconPosition="right"
          >
            {t('ai.go_to_settings', { defaultValue: 'Settings' })}
          </Button>
        </div>
      )}

      {/* Input card with tabs */}
      <Card className="animate-card-in" style={{ animationDelay: '100ms' }} padding="none">
        {/* Tab bar */}
        <div className="px-6 pt-5 pb-0">
          <div className="flex flex-wrap gap-1.5 rounded-xl bg-surface-secondary p-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                disabled={isPending}
                className={`
                  flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium
                  transition-all duration-normal ease-oe
                  ${
                    activeTab === tab.id
                      ? 'bg-oe-blue text-white shadow-sm'
                      : 'text-content-secondary hover:text-content-primary hover:bg-surface-primary'
                  }
                  ${isPending ? 'opacity-60 pointer-events-none' : ''}
                `}
              >
                <span className="shrink-0">{tab.icon}</span>
                <span className="hidden sm:inline">
                  {t(tab.labelKey, { defaultValue: tab.label })}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Tab content */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <div className="px-6 py-5">
            {/* ── Tab 1: Text Description ─────────────────────────── */}
            {activeTab === 'text' && (
              <div className="space-y-4">
                <div className="relative">
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t('ai.describe_placeholder', {
                      defaultValue:
                        'Describe your project...\n\nExample: "3-story residential building, 1200 m\u00b2 total area, reinforced concrete frame with brick facade, flat roof, standard MEP installations. Location: Berlin, Germany."',
                    })}
                    rows={5}
                    className="w-full rounded-xl border border-border bg-surface-primary px-4 py-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)] transition-all duration-normal ease-oe hover:border-content-tertiary resize-none leading-relaxed"
                    disabled={isPending}
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-content-tertiary">
                    {description.length > 0 && `${description.length} chars`}
                  </div>
                </div>

                {/* Full options row for text tab */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.location', { defaultValue: 'Location' })}
                    </label>
                    <input
                      type="text"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                      placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary"
                      disabled={isPending}
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.currency_label', { defaultValue: 'Currency' })}
                    </label>
                    <select
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {CURRENCIES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.standard_label', { defaultValue: 'Standard' })}
                    </label>
                    <select
                      value={standard}
                      onChange={(e) => setStandard(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {STANDARDS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.building_type', { defaultValue: 'Building Type' })}
                    </label>
                    <select
                      value={buildingType}
                      onChange={(e) => setBuildingType(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {BUILDING_TYPES.map((bt) => (
                        <option key={bt.value} value={bt.value}>
                          {bt.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.area', { defaultValue: 'Area (m\u00b2)' })}
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={areaM2}
                      onChange={(e) => setAreaM2(e.target.value)}
                      placeholder="1200"
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary"
                      disabled={isPending}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── Tab 2: Photo / Scan ─────────────────────────────── */}
            {activeTab === 'photo' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.photo as string}
                    formatLabel={FORMAT_LABELS.photo as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={imagePreviewUrl}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 3: PDF Document ─────────────────────────────── */}
            {activeTab === 'pdf' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.pdf as string}
                    formatLabel={FORMAT_LABELS.pdf as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                    hint={t('ai.pdf_hint', {
                      defaultValue:
                        'Upload BOQ documents, specifications, or drawings in PDF format.',
                    })}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 4: Excel / CSV ──────────────────────────────── */}
            {activeTab === 'excel' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.excel as string}
                    formatLabel={FORMAT_LABELS.excel as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                    hint={t('ai.excel_hint', {
                      defaultValue:
                        'Works best with columns: Description, Unit, Quantity, Rate/Price.',
                    })}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 5: CAD / BIM ────────────────────────────────── */}
            {activeTab === 'cad' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.cad as string}
                    formatLabel={FORMAT_LABELS.cad as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <div className="mt-3 flex items-start gap-2 rounded-lg bg-oe-blue-subtle/50 px-3 py-2.5">
                  <Info size={14} className="shrink-0 mt-0.5 text-oe-blue" />
                  <p className="text-xs text-oe-blue leading-relaxed">
                    {t('ai.cad_info', {
                      defaultValue:
                        'CAD/BIM files (.rvt, .ifc, .dwg, .dgn) require the DDC converter to be installed. Elements will be extracted and used to generate a cost estimate. Download converters from GitHub and place them in ~/.openestimator/converters/.',
                    })}
                  </p>
                </div>
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 6: Paste from Clipboard ─────────────────────── */}
            {activeTab === 'paste' && (
              <div>
                <div className="relative">
                  <textarea
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder={t('ai.paste_placeholder', {
                      defaultValue:
                        'Paste your BOQ data here (from Excel, Word, or any table)...\n\nExample:\nPos\tDescription\tUnit\tQty\tRate\n01.01\tExcavation\tm3\t250\t18.50\n01.02\tConcrete C30/37\tm3\t120\t145.00\n01.03\tReinforcement BSt 500\tkg\t12000\t1.85',
                    })}
                    rows={8}
                    className="w-full rounded-xl border border-border bg-surface-primary px-4 py-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)] transition-all duration-normal ease-oe hover:border-content-tertiary resize-none leading-relaxed font-mono"
                    disabled={isPending}
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-content-tertiary">
                    {pasteText.length > 0 && `${pasteText.length} chars`}
                  </div>
                </div>
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('ai.paste_info', {
                    defaultValue:
                      'Auto-detects tab-separated, semicolon, or comma-delimited data. AI will parse and structure your data into estimate items.',
                  })}
                </p>
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* Submit button */}
            <div className="mt-5 flex items-center justify-between">
              <div className="text-xs text-content-tertiary">
                {aiSettings?.status === 'connected' && aiSettings.preferred_model && (
                  <span className="flex items-center gap-1.5">
                    <Zap size={12} />
                    {t('ai.powered_by', {
                      defaultValue: 'Powered by {{model}}',
                      model: aiSettings.preferred_model,
                    })}
                  </span>
                )}
              </div>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={isPending}
                disabled={!canSubmit}
                icon={<Sparkles size={18} />}
              >
                {submitLabel}
              </Button>
            </div>
          </div>
        </form>
      </Card>

      {/* Loading state */}
      {isPending && <LoadingState />}

      {/* Error state */}
      {isError && (
        <div className="animate-card-in">
          <Card className="border-semantic-error/20">
            <CardContent className="!mt-0">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-semantic-error-bg">
                  <AlertCircle size={18} className="text-semantic-error" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-semantic-error">
                    {t('ai.generation_failed', { defaultValue: 'Estimate generation failed' })}
                  </p>
                  <p className="mt-1 text-sm text-content-secondary">
                    {mutationError?.message ||
                      t('ai.try_again', {
                        defaultValue: 'Please try again or check your AI settings.',
                      })}
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    onClick={resetMutationErrors}
                    icon={<RotateCcw size={14} />}
                  >
                    {t('ai.dismiss', { defaultValue: 'Dismiss' })}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Results */}
      {result && !isPending && (
        <div className="space-y-4 animate-card-in" style={{ animationDelay: '50ms' }}>
          {/* Results header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('ai.results', { defaultValue: 'Estimate Results' })}
              </h2>
              <Badge variant="success" size="sm">
                {result.items.length} {t('ai.items', { defaultValue: 'items' })}
              </Badge>
              {result.confidence > 0 && (
                <Badge
                  variant={
                    result.confidence >= 0.7
                      ? 'success'
                      : result.confidence >= 0.4
                        ? 'warning'
                        : 'error'
                  }
                  size="sm"
                >
                  {Math.round(result.confidence * 100)}%{' '}
                  {t('ai.confidence', { defaultValue: 'confidence' })}
                </Badge>
              )}
            </div>
            <div className="text-xs text-content-tertiary">
              {t('ai.generated_in', {
                defaultValue: 'Generated in {{duration}}s using {{model}}',
                duration: (result.duration_ms / 1000).toFixed(1),
                model: result.model_used,
              })}
            </div>
          </div>

          {/* Results table */}
          <Card padding="none">
            <ResultsTable result={result} />
          </Card>

          {/* Action buttons */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              icon={<RotateCcw size={14} />}
            >
              {t('ai.new_estimate', { defaultValue: 'New Estimate' })}
            </Button>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Download size={14} />}
                onClick={() =>
                  addToast({
                    type: 'info',
                    title: t('ai.export_coming_soon', { defaultValue: 'Export coming soon' }),
                  })
                }
              >
                {t('ai.export_pdf', { defaultValue: 'Export PDF' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Save size={14} />}
                onClick={() => setSaveDialogOpen(true)}
              >
                {t('ai.save_as_boq', { defaultValue: 'Save as BOQ' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Save dialog */}
      <SaveToBOQDialog
        open={saveDialogOpen}
        onClose={() => setSaveDialogOpen(false)}
        onSave={(projectId, boqName) => saveMutation.mutate({ projectId, boqName })}
        saving={saveMutation.isPending}
      />
    </div>
  );
}
