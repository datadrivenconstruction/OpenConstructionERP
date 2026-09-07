// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Library, Search, X, Layers, Globe, AlertCircle, Loader2, Eye, Save } from 'lucide-react';

import { Button, Card, Badge, EmptyState, SkeletonGrid, Breadcrumb, DismissibleInfo } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { unitGlyph } from '@/shared/lib/unitLabels';
import { currencyFractionDigits } from '@/shared/lib/money';
import { projectsApi } from '@/features/projects/api';

import {
  assembliesApi,
  type AssemblyTemplate,
  type AppliedTemplateResponse,
  type AppliedTemplateCurrencySubtotal,
  type ResourceType,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

/* -- Constants ------------------------------------------------------------ */

const CATEGORY_FILTERS: { value: string; key: string }[] = [
  { value: '', key: 'assemblies.library.category_all' },
  { value: 'concrete', key: 'assemblies.library.category_concrete' },
  { value: 'masonry', key: 'assemblies.library.category_masonry' },
  { value: 'drywall', key: 'assemblies.library.category_drywall' },
  { value: 'steel', key: 'assemblies.library.category_steel' },
  { value: 'roofing', key: 'assemblies.library.category_roofing' },
  { value: 'insulation', key: 'assemblies.library.category_insulation' },
  { value: 'finishing', key: 'assemblies.library.category_finishing' },
  { value: 'mep', key: 'assemblies.library.category_mep' },
  { value: 'earthwork', key: 'assemblies.library.category_earthwork' },
];

type BadgeVariant = 'blue' | 'success' | 'warning' | 'error' | 'neutral';

const CATEGORY_BADGE: Record<string, BadgeVariant> = {
  concrete: 'blue',
  masonry: 'warning',
  drywall: 'neutral',
  steel: 'neutral',
  roofing: 'warning',
  insulation: 'blue',
  finishing: 'success',
  mep: 'success',
  earthwork: 'warning',
};

/** Minimal `t` shape used by the label helpers below (repo convention). */
type Translate = (key: string, opts?: { defaultValue?: string }) => string;

/** Localized category label — reuses the filter-chip keys, falling back to a
 *  capitalized raw value for any category without a dedicated key. */
function categoryLabel(cat: string, t: Translate): string {
  if (!cat) return '';
  const cap = cat.charAt(0).toUpperCase() + cat.slice(1);
  return t(`assemblies.library.category_${cat}`, { defaultValue: cap });
}

/** Localized resource-role label — reuses the editor's type_*_full keys so a
 *  template component's role (material / labor / …) reads in the user's
 *  language instead of a raw English token. */
function roleLabel(role: string, t: Translate): string {
  if (!role) return '';
  const cap = role.charAt(0).toUpperCase() + role.slice(1);
  return t(`assemblies.type_${role}_full`, { defaultValue: cap });
}

/* -- Page ---------------------------------------------------------------- */

export function AssemblyLibraryPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [category, setCategory] = useState('');
  const [selected, setSelected] = useState<AssemblyTemplate | null>(null);

  // Debounce the search box.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(id);
  }, [search]);

  const params: Record<string, string> = { limit: '200', offset: '0' };
  if (debouncedSearch) params.q = debouncedSearch;
  if (category) params.category = category;

  const { data, isLoading } = useQuery({
    queryKey: ['assembly-templates', debouncedSearch, category],
    queryFn: () => assembliesApi.listTemplates(params),
    placeholderData: (prev) => prev,
  });

  const templates = data?.items ?? [];
  const total = data?.total ?? 0;

  const lang = ((i18n.language || 'en').split('-')[0] ?? 'en') as string;
  const localisedName = (tpl: AssemblyTemplate): string =>
    tpl.name_translations?.[lang] || tpl.name;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.assemblies', 'Assemblies'), to: '/assemblies' },
          { label: t('assemblies.library.title', 'Assembly library') },
        ]}
      />
      {/* Canonical top block — the breadcrumb above carries the Assemblies >
          Assembly library trail, and the module name + icon are shown by the
          global top app bar. The page renders only its subtitle + the count. */}
      <PageHeader
        srTitle={t('assemblies.library.title', 'Assembly library')}
        subtitle={t(
          'assemblies.library.description',
          'Canonical recipe templates, pick a starting point and apply it to your project.'
        )}
        actions={
          <Badge variant="neutral">
            {`${total} ${t('assemblies.library.templates_found', 'templates')}`}
          </Badge>
        }
      />

      <DismissibleInfo
        storageKey="assemblies-library"
        title={t('assembly_library.intro_title', { defaultValue: 'Find a ready recipe instead of building one' })}
        links={[
          { label: t('nav.assemblies', { defaultValue: 'Assemblies' }), onClick: () => navigate('/assemblies') },
          { label: t('assemblies.new_assembly', { defaultValue: 'New Assembly' }), onClick: () => navigate('/assemblies/new') },
          { label: t('nav.boq', { defaultValue: 'Bill of Quantities' }), onClick: () => navigate('/boq') },
        ]}
      >
        {t('assembly_library.intro_body', {
          defaultValue:
            'Search the shared library of assembly templates by trade and category, preview the components and rates, and save the ones you want into your own assemblies. Saved assemblies are then ready to apply to BOQ positions on any project.',
        })}
      </DismissibleInfo>

      {/* Search bar */}
      <div className="relative">
        <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t(
            'assemblies.library.search_placeholder',
            'Search by name, tag, or translation…'
          )}
          className="w-full rounded-lg border border-zinc-300 bg-white py-2.5 ps-10 pe-10 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        {search && (
          <button
            type="button"
            onClick={() => setSearch('')}
            className="absolute end-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800"
            aria-label={t('common.clear', 'Clear')}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Category filter chips */}
      <div className="flex flex-wrap gap-2">
        {CATEGORY_FILTERS.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => setCategory(c.value)}
            className={
              'rounded-full border px-3 py-1 text-sm transition-colors ' +
              (category === c.value
                ? 'border-blue-600 bg-blue-600 text-white'
                : 'border-zinc-300 bg-white text-zinc-700 hover:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-zinc-600')
            }
          >
            {t(c.key, c.value || 'All')}
          </button>
        ))}
      </div>

      {/* Grid */}
      {isLoading ? (
        <SkeletonGrid items={9} />
      ) : templates.length === 0 ? (
        <EmptyState
          icon={<Library className="h-8 w-8" />}
          title={t('assemblies.library.empty_title', 'No templates match the current filter')}
          description={t(
            'assemblies.library.empty_description',
            'Adjust the search or category to broaden your results.'
          )}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {templates.map((tpl) => (
            <TemplateCard
              key={tpl.id}
              template={tpl}
              localisedName={localisedName(tpl)}
              onClick={() => setSelected(tpl)}
            />
          ))}
        </div>
      )}

      {/* Drawer */}
      {selected && (
        <TemplateDrawer
          template={selected}
          localisedName={localisedName(selected)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

/* -- Card ---------------------------------------------------------------- */

function TemplateCard({
  template,
  localisedName,
  onClick,
}: {
  template: AssemblyTemplate;
  localisedName: string;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const badgeColor = CATEGORY_BADGE[template.category] ?? 'neutral';

  // The three the create form offers and the BOQ side honours. NRM was
  // offered by the picker and badged by nothing, so a template classified
  // against it looked unclassified everywhere it was read back.
  const din = template.classification?.din276;
  const mf = template.classification?.masterformat;
  const nrm = template.classification?.nrm;

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md"
      onClick={onClick}
    >
      <div className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {localisedName}
          </h3>
          <Badge variant={badgeColor}>{categoryLabel(template.category, t)}</Badge>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {din && (
            <Badge variant="blue" size="sm">
              {`DIN ${din}`}
            </Badge>
          )}
          {mf && (
            <Badge variant="neutral" size="sm">
              {`MF ${mf}`}
            </Badge>
          )}
          {nrm && (
            <Badge variant="purple" size="sm">
              {`NRM ${nrm}`}
            </Badge>
          )}
        </div>

        <div className="mt-auto flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
          <span className="flex items-center gap-1">
            <Layers className="h-3.5 w-3.5" />
            {template.component_count}{' '}
            {t('assemblies.library.components', 'components')}
          </span>
          <span className="font-mono text-zinc-700 dark:text-zinc-300">
            {t('assemblies.library.per_unit', 'per')} {unitGlyph(template.unit)}
          </span>
        </div>
      </div>
    </Card>
  );
}

/* -- Drawer / Apply form ------------------------------------------------- */

interface ProjectLite {
  id: string;
  name: string;
}

/**
 * The preview table's totals row.
 *
 * `grandTotal` is null whenever the preview spans more than one currency: the
 * server refuses to name a total it could only reach by adding two currencies
 * together. That null must be branched on, never coerced — `Number(null)` is 0
 * and `Number(undefined)` is NaN, so the obvious one-liner prints a confident
 * "0.00" for a preview whose real total is unknown, which is a worse answer
 * than the blended number this whole change removed.
 *
 * Exported so the null branch can be rendered on its own in a test, the way
 * `ComponentRow` is exported from the editor page.
 */
export function PreviewTotalsFooter({
  grandTotal,
  currencyLabel,
  buckets,
}: {
  grandTotal: number | null;
  currencyLabel: string;
  buckets: AppliedTemplateCurrencySubtotal[];
}) {
  const { t } = useTranslation();

  if (grandTotal != null) {
    return (
      <tfoot>
        <tr className="font-semibold">
          <td colSpan={3} className="py-2 text-right">
            {t('assemblies.library.grand_total', 'Grand total')}
          </td>
          <td className="py-2 text-right font-mono">
            {`${fmtFixed(Number(grandTotal), currencyFractionDigits(currencyLabel))} ${currencyLabel}`.trim()}
          </td>
        </tr>
      </tfoot>
    );
  }

  // Each currency on its own line, the way MultiCurrencyTotal already does it.
  return (
    <tfoot>
      <tr>
        <td colSpan={4} className="pt-2 text-right text-[11px] font-normal text-zinc-500 dark:text-zinc-400">
          {t(
            'assemblies.library.no_single_total',
            'No single total: this preview covers more than one currency, and part of it could not be converted.'
          )}
        </td>
      </tr>
      {buckets.map((sub) => (
        <tr key={sub.currency || 'unset'} className="font-semibold">
          <td colSpan={3} className="py-1 text-right">
            {sub.currency
              ? t('assemblies.library.subtotal_in', 'Subtotal in {{currency}}', { currency: sub.currency })
              : t('assemblies.library.subtotal_currency_not_set', 'Subtotal, currency not set')}
          </td>
          <td className="py-1 text-right font-mono">
            {`${fmtFixed(Number(sub.amount), currencyFractionDigits(sub.currency))} ${sub.currency}`.trim()}
          </td>
        </tr>
      ))}
    </tfoot>
  );
}

function TemplateDrawer({
  template,
  localisedName,
  onClose,
}: {
  template: AssemblyTemplate;
  localisedName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Issue #270: render the preview quantities + restate rates in the user's
  // measurement system. The money totals (per-component total + grand total)
  // are invariant and stay verbatim.
  const q = useDisplayQuantity();

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [projectId, setProjectId] = useState<string>('');
  const [quantity, setQuantity] = useState<string>('1');
  const [applying, setApplying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<AppliedTemplateResponse | null>(null);

  const { data: projects } = useQuery({
    queryKey: ['projects-for-library'],
    queryFn: () => projectsApi.list() as Promise<ProjectLite[]>,
  });

  // Default to the project chosen in the top bar so applying a template
  // matches the rest of the app, falling back to the first project only
  // when none is active. The drawer remounts on each open, so this re-seeds
  // from the current active project every time. The user can still pick
  // another project below.
  useEffect(() => {
    if (projectId) return;
    if (activeProjectId) {
      setProjectId(activeProjectId);
      return;
    }
    const first = projects?.[0];
    if (first) setProjectId(first.id);
  }, [projects, projectId, activeProjectId]);

  // Step 1 — Preview. Resolves the template against the project's cost
  // catalogue WITHOUT persisting anything (the backend documents this as a
  // non-persisted preview). The persist step is the explicit "Save as
  // assembly" action below.
  const handlePreview = async () => {
    if (!projectId) {
      addToast({
        type: 'error',
        title: t(
          'assemblies.library.no_project',
          'Pick a project to apply this template.'
        ),
      });
      return;
    }
    const qty = Number(quantity);
    if (!Number.isFinite(qty) || qty <= 0) {
      addToast({
        type: 'error',
        title: t('assemblies.library.invalid_quantity', 'Quantity must be > 0.'),
      });
      return;
    }
    setApplying(true);
    try {
      const resp = await assembliesApi.applyTemplate(template.id, {
        project_id: projectId,
        quantity: qty,
      });
      setResult(resp);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('assemblies.library.preview_failed', 'Could not build the preview.'),
        message: (err as { message?: string })?.message,
      });
    } finally {
      setApplying(false);
    }
  };

  // Step 2 — Persist. Turns the previewed, catalogue-resolved components into
  // a real, project-scoped Assembly via the existing create + addComponent
  // endpoints (same machinery the AI Generate flow uses). This is the honest
  // "we actually wrote something" step: the new assembly then appears in the
  // assemblies list and can be applied to a BOQ from its editor.
  const handleSaveAsAssembly = async () => {
    if (!result || !projectId) return;
    setSaving(true);
    try {
      const codeSuffix = Date.now().toString(36).slice(-4).toUpperCase();
      const assembly = await assembliesApi.create({
        code: `TPL-${codeSuffix}`,
        name: localisedName,
        unit: result.unit,
        category: template.category || 'general',
        classification: template.classification,
        bid_factor: 1.0,
        project_id: projectId,
      });

      for (const c of result.components) {
        await assembliesApi.addComponent(assembly.id, {
          cost_item_id: c.matched_cost_item_id || undefined,
          description: c.matched_description || c.description,
          resource_type: (c.role || 'material') as ResourceType,
          factor: c.factor,
          quantity: 1,
          unit: c.unit,
          unit_cost: Number(c.unit_rate) || 0,
        });
      }

      queryClient.invalidateQueries({ queryKey: ['assemblies'] });
      queryClient.invalidateQueries({ queryKey: ['assemblies-stats'] });
      queryClient.invalidateQueries({ queryKey: ['assemblies-all-for-banner'] });

      addToast({
        type: 'success',
        title: t('assemblies.library.saved_title', 'Assembly created from template'),
        message: t(
          'assemblies.library.saved_message',
          '{{name}} was added to your assemblies. Open it to fine-tune rates and apply it to a BOQ.',
          { name: localisedName }
        ),
      });
      onClose();
      navigate(`/assemblies/${assembly.id}`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('assemblies.library.save_failed', 'Could not create the assembly.'),
        message: (err as { message?: string })?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  // When the matched item carried no currency (no priced match resolved its
  // currency), fall back to the project's own currency so the preview never
  // renders a bare number with a trailing space; blank only if nothing is known.
  const currencyLabel =
    (result?.currency || '').trim() ||
    (projects?.find((p) => p.id === projectId) as { currency?: string } | undefined)?.currency ||
    '';

  // A component row shows its own money. The server sends each matched item's
  // currency because it is not necessarily the response's target: a component
  // the platform could not convert keeps its native figure, and labelling it
  // with the target code would be the exact misreading this fix removes.
  const rowCurrency = (c: { currency?: string }) => (c.currency || '').trim() || currencyLabel;

  // Per-currency buckets. Present on any current server; guarded because a
  // stale cached bundle can outlive a deploy.
  const currencyBuckets = result?.totals_by_currency ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40">
      <div
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-xl dark:bg-zinc-900"
        role="dialog"
        aria-labelledby="template-drawer-title"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-zinc-200 bg-white px-5 py-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div>
            <h2
              id="template-drawer-title"
              className="text-lg font-semibold text-zinc-900 dark:text-zinc-100"
            >
              {localisedName}
            </h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              {categoryLabel(template.category, t)} · {t('assemblies.library.per_unit', 'per')}{' '}
              {unitGlyph(template.unit)} · {template.component_count}{' '}
              {t('assemblies.library.components', 'components')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800"
            aria-label={t('common.close', 'Close')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-5 px-5 py-5">
          {/* Translations */}
          {Object.keys(template.name_translations || {}).length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                <Globe className="mr-1 inline h-3.5 w-3.5" />
                {t('assemblies.library.translations', 'Translations')}
              </h3>
              <ul className="space-y-1 text-sm">
                {Object.entries(template.name_translations).map(([k, v]) => (
                  <li key={k} className="flex gap-2">
                    <span className="w-8 font-mono text-zinc-400">{k}</span>
                    <span className="text-zinc-700 dark:text-zinc-300">{v}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Classification */}
          {(template.classification?.din276 ||
            template.classification?.masterformat ||
            template.classification?.nrm) && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                {t('assemblies.library.classification', 'Classification')}
              </h3>
              <div className="flex gap-2">
                {template.classification.din276 && (
                  <Badge variant="blue">{`DIN 276 · ${template.classification.din276}`}</Badge>
                )}
                {template.classification.masterformat && (
                  <Badge variant="neutral">
                    {`MasterFormat · ${template.classification.masterformat}`}
                  </Badge>
                )}
                {template.classification.nrm && (
                  <Badge variant="purple">
                    {`NRM · ${template.classification.nrm}`}
                  </Badge>
                )}
              </div>
            </section>
          )}

          {/* Components */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              {t('assemblies.library.components', 'Components')}
            </h3>
            <ul className="divide-y divide-zinc-200 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
              {template.components.map((c, idx) => (
                <li key={idx} className="flex items-center justify-between px-3 py-2 text-sm">
                  <div>
                    <div className="text-zinc-800 dark:text-zinc-200">{c.description}</div>
                    <div className="text-xs text-zinc-500">{roleLabel(c.role, t)}</div>
                  </div>
                  <div className="text-right font-mono text-xs text-zinc-600 dark:text-zinc-400">
                    {c.factor} {unitGlyph(c.unit)}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          {/* Tags */}
          {template.tags.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                {t('assemblies.library.tags', 'Tags')}
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {template.tags.map((tag) => (
                  <Badge key={tag} variant="neutral" size="sm">
                    {tag}
                  </Badge>
                ))}
              </div>
            </section>
          )}

          {/* Apply form */}
          <section className="rounded-md border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
            <h3 className="mb-1 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {t('assemblies.library.preview_heading', 'Preview against a project')}
            </h3>
            <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
              {t(
                'assemblies.library.preview_explainer',
                'Resolves each template component against the project cost catalogue so you can review rates. Nothing is saved until you create an assembly from the preview.'
              )}
            </p>
            <div className="space-y-3">
              <label className="block text-sm">
                <span className="mb-1 block text-zinc-700 dark:text-zinc-300">
                  {t('assemblies.library.project', 'Project')}
                </span>
                <select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                >
                  <option value="">
                    {t('assemblies.library.pick_project', '- pick a project -')}
                  </option>
                  {(projects ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-zinc-700 dark:text-zinc-300">
                  {t('assemblies.library.quantity', 'Quantity')} ({template.unit})
                </span>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </label>
              <Button
                onClick={handlePreview}
                disabled={applying || !projectId}
                className="w-full"
              >
                {applying ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Eye className="mr-1.5 h-4 w-4" />
                )}
                {t('assemblies.library.preview_button', 'Preview pricing')}
              </Button>
            </div>
          </section>

          {/* Result */}
          {result && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                {t('assemblies.library.preview', 'Preview')}
              </h3>
              {result.warnings.length > 0 && (
                <div className="mb-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <div>
                    {result.warnings.map((w, i) => (
                      <div key={i}>{w}</div>
                    ))}
                  </div>
                </div>
              )}
              <table className="w-full text-xs">
                <thead className="text-left text-zinc-500">
                  <tr>
                    <th className="py-1 pr-2">
                      {t('assemblies.library.component', 'Component')}
                    </th>
                    <th className="py-1 pr-2 text-right">
                      {t('assemblies.library.qty', 'Qty')}
                    </th>
                    <th className="py-1 pr-2 text-right">
                      {t('assemblies.library.rate', 'Rate')}
                    </th>
                    <th className="py-1 text-right">
                      {t('assemblies.library.total', 'Total')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {result.components.map((c, i) => {
                    const matched = Boolean(c.matched_cost_item_id);
                    return (
                      <tr key={i} className={matched ? '' : 'bg-zinc-50/60 dark:bg-zinc-800/30'}>
                        <td className="py-1.5 pr-2">
                          <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200">
                            {c.description}
                            {!matched && (
                              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                                {t('assemblies.library.not_matched', 'not matched')}
                              </span>
                            )}
                          </div>
                          {c.matched_code && (
                            <div className="font-mono text-[10px] text-zinc-500">
                              {c.matched_code}
                            </div>
                          )}
                        </td>
                        <td className="py-1.5 pr-2 text-right font-mono">
                          {(() => {
                            const d = q.convert(c.scaled_quantity, c.unit || '');
                            return `${fmtFixed(d.value, 2)} ${c.unit ? d.unit : ''}`.trim();
                          })()}
                        </td>
                        <td className="py-1.5 pr-2 text-right font-mono">
                          {matched
                            ? `${fmtFixed(q.convertRate(Number(c.unit_rate), c.unit || ''), currencyFractionDigits(rowCurrency(c)))} ${rowCurrency(c)}`.trim()
                            : '—'}
                        </td>
                        <td className="py-1.5 text-right font-mono">
                          {matched
                            ? `${fmtFixed(c.total, currencyFractionDigits(rowCurrency(c)))} ${rowCurrency(c)}`.trim()
                            : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <PreviewTotalsFooter
                  grandTotal={result.grand_total}
                  currencyLabel={currencyLabel}
                  buckets={currencyBuckets}
                />
              </table>

              {/* Persist step — the honest "this actually writes something"
                  action. Creates a real project-scoped assembly from the
                  previewed components. */}
              <div className="mt-4 flex flex-col gap-2 rounded-md border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t(
                    'assemblies.library.save_explainer',
                    'Create a reusable assembly in this project from the preview above. You can then refine rates and apply it to a BOQ from the assembly editor.'
                  )}
                </p>
                <Button
                  onClick={handleSaveAsAssembly}
                  disabled={saving || result.components.length === 0}
                  className="w-full"
                >
                  {saving ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-1.5 h-4 w-4" />
                  )}
                  {t('assemblies.library.save_button', 'Create assembly from template')}
                </Button>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default AssemblyLibraryPage;
