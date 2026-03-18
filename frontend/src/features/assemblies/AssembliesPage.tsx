import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Search, Plus, Layers, ChevronDown } from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { assembliesApi, type Assembly } from './api';

/* -- Constants ------------------------------------------------------------ */

const CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'concrete', label: 'Concrete' },
  { value: 'masonry', label: 'Masonry' },
  { value: 'steel', label: 'Steel' },
  { value: 'mep', label: 'MEP' },
  { value: 'earthwork', label: 'Earthwork' },
  { value: 'general', label: 'General' },
] as const;

const CATEGORY_COLORS: Record<string, 'blue' | 'success' | 'warning' | 'error' | 'neutral'> = {
  concrete: 'blue',
  masonry: 'warning',
  steel: 'neutral',
  mep: 'success',
  earthwork: 'warning',
  general: 'neutral',
};

/* -- Component ------------------------------------------------------------ */

export function AssembliesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');

  const params: Record<string, string> = {};
  if (query) params.q = query;
  if (category) params.category = category;

  const { data: assemblies, isLoading } = useQuery({
    queryKey: ['assemblies', query, category],
    queryFn: () => assembliesApi.list(params),
    placeholderData: (prev) => prev,
  });

  const items = assemblies ?? [];

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
  }, []);

  const fmt = (n: number) =>
    new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('assemblies.title', 'Assemblies')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {items.length > 0
              ? `${items.length} ${t('assemblies.assemblies_found', 'assemblies')}`
              : t('assemblies.description', 'Reusable cost recipes for common construction elements')}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => navigate('/assemblies/new')}
        >
          {t('assemblies.new_assembly', 'New Assembly')}
        </Button>
      </div>

      {/* Search & Filters */}
      <Card padding="none" className="mb-6">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          {/* Search input */}
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t(
                'assemblies.search_placeholder',
                'Search by name or code...',
              )}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
          </div>

          {/* Category filter */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-44"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </Card>

      {/* Results */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} padding="none" className="overflow-hidden">
              <div className="p-5 space-y-3">
                <Skeleton width={80} height={14} />
                <Skeleton height={18} className="w-3/4" />
                <Skeleton height={14} className="w-1/2" />
                <div className="flex items-center gap-2 pt-2">
                  <Skeleton width={60} height={22} rounded="full" />
                  <Skeleton width={40} height={22} rounded="full" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers size={24} strokeWidth={1.5} />}
          title={t('assemblies.no_results', 'No assemblies found')}
          description={
            query || category
              ? t('assemblies.no_results_hint', 'Try adjusting your search or filters')
              : t(
                  'assemblies.empty_hint',
                  'Create your first assembly to build reusable cost recipes',
                )
          }
          action={
            !query && !category ? (
              <Button
                variant="primary"
                icon={<Plus size={16} />}
                onClick={() => navigate('/assemblies/new')}
              >
                {t('assemblies.new_assembly', 'New Assembly')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((assembly) => (
            <AssemblyCard
              key={assembly.id}
              assembly={assembly}
              fmt={fmt}
              onClick={() => navigate(`/assemblies/${assembly.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* -- Assembly Card -------------------------------------------------------- */

function AssemblyCard({
  assembly,
  fmt,
  onClick,
}: {
  assembly: Assembly;
  fmt: (n: number) => string;
  onClick: () => void;
}) {
  const badgeVariant = CATEGORY_COLORS[assembly.category] ?? 'neutral';

  return (
    <Card
      padding="none"
      hoverable
      className="cursor-pointer group"
      onClick={onClick}
    >
      <div className="p-5">
        {/* Code */}
        <p className="text-xs font-mono text-content-tertiary mb-1.5">{assembly.code}</p>

        {/* Name */}
        <h3 className="text-sm font-semibold text-content-primary leading-snug line-clamp-2 group-hover:text-oe-blue transition-colors">
          {assembly.name}
        </h3>

        {/* Rate */}
        <p className="mt-3 text-lg font-bold text-content-primary tabular-nums">
          {fmt(assembly.total_rate)}
          <span className="ml-1 text-xs font-normal text-content-tertiary">
            / {assembly.unit}
          </span>
        </p>

        {/* Tags */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {assembly.category && (
            <Badge variant={badgeVariant} size="sm">
              {assembly.category}
            </Badge>
          )}
          <Badge variant="neutral" size="sm">
            {assembly.currency || 'EUR'}
          </Badge>
          {assembly.bid_factor !== 1.0 && (
            <Badge variant="blue" size="sm">
              BF {assembly.bid_factor}
            </Badge>
          )}
        </div>
      </div>
    </Card>
  );
}
