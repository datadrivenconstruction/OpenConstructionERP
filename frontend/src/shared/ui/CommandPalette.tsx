import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Search,
  LayoutDashboard,
  FolderOpen,
  FolderPlus,
  Table2,
  Database,
  Boxes,
  CalendarDays,
  TrendingUp,
  FileText,
  FilePlus2,
  FileBarChart,
  ShieldCheck,
  Leaf,
  Package,
  Settings,
  Sparkles,
  Download,
  CornerDownLeft,
  type LucideIcon,
} from 'lucide-react';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi, type BOQ } from '@/features/boq/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface SearchResult {
  id: string;
  type: 'page' | 'project' | 'boq' | 'recent';
  labelKey?: string;
  label?: string;
  description?: string;
  icon: LucideIcon;
  path: string;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/* ── Static page entries ───────────────────────────────────────────────── */

const PAGE_RESULTS: SearchResult[] = [
  { id: 'page-dashboard', type: 'page', labelKey: 'nav.dashboard', icon: LayoutDashboard, path: '/' },
  { id: 'page-projects', type: 'page', labelKey: 'projects.title', icon: FolderOpen, path: '/projects' },
  { id: 'page-boq', type: 'page', labelKey: 'boq.title', icon: Table2, path: '/boq' },
  { id: 'page-costs', type: 'page', labelKey: 'costs.title', icon: Database, path: '/costs' },
  { id: 'page-catalog', type: 'page', labelKey: 'catalog.title', icon: Boxes, path: '/catalog' },
  { id: 'page-ai-estimate', type: 'page', labelKey: 'nav.ai_estimate', icon: Sparkles, path: '/ai-estimate' },
  { id: 'page-schedule', type: 'page', labelKey: 'schedule.title', icon: CalendarDays, path: '/schedule' },
  { id: 'page-5d', type: 'page', labelKey: 'nav.5d_cost_model', icon: TrendingUp, path: '/5d' },
  { id: 'page-tendering', type: 'page', labelKey: 'tendering.title', icon: FileText, path: '/tendering' },
  { id: 'page-reports', type: 'page', labelKey: 'nav.reports', icon: FileBarChart, path: '/reports' },
  { id: 'page-validation', type: 'page', labelKey: 'validation.title', icon: ShieldCheck, path: '/validation' },
  { id: 'page-sustainability', type: 'page', labelKey: 'nav.sustainability', icon: Leaf, path: '/sustainability' },
  { id: 'page-modules', type: 'page', labelKey: 'modules.title', icon: Package, path: '/modules' },
  { id: 'page-settings', type: 'page', labelKey: 'nav.settings', icon: Settings, path: '/settings' },
  // Quick actions
  { id: 'action-new-project', type: 'page', labelKey: 'command_palette.action_new_project', description: 'Ctrl+N', icon: FolderPlus, path: '/projects/new' },
  { id: 'action-new-boq', type: 'page', labelKey: 'command_palette.action_new_boq', description: 'Ctrl+Shift+N', icon: FilePlus2, path: '/boq/new' },
  { id: 'action-validate', type: 'page', labelKey: 'command_palette.action_run_validation', description: 'Ctrl+Shift+V', icon: ShieldCheck, path: '/validation' },
  { id: 'action-import-db', type: 'page', labelKey: 'command_palette.action_import_database', icon: Download, path: '/costs/import' },
];

/* ── Recent items (stored in localStorage) ─────────────────────────────── */

const RECENT_KEY = 'oe_command_palette_recent';
const MAX_RECENT = 5;

interface RecentEntry {
  id: string;
  label: string;
  path: string;
  type: 'page' | 'project' | 'boq';
}

function loadRecent(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as RecentEntry[];
  } catch {
    return [];
  }
}

function saveRecent(entries: RecentEntry[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(entries.slice(0, MAX_RECENT)));
  } catch {
    // Silently ignore storage errors
  }
}

function pushRecent(entry: RecentEntry): void {
  const current = loadRecent().filter((r) => r.id !== entry.id);
  current.unshift(entry);
  saveRecent(current);
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [boqs, setBoqs] = useState<(BOQ & { projectName?: string })[]>([]);
  const [boqsLoaded, setBoqsLoaded] = useState(false);

  // Load projects once when palette opens
  useEffect(() => {
    if (!open) return;
    if (projectsLoaded) return;

    let cancelled = false;
    projectsApi
      .list()
      .then((data) => {
        if (!cancelled) {
          setProjects(data);
          setProjectsLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProjectsLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open, projectsLoaded]);

  // Load BOQs for the first few projects when palette opens and projects are loaded
  useEffect(() => {
    if (!open || !projectsLoaded || boqsLoaded || projects.length === 0) return;

    let cancelled = false;
    const projectSlice = projects.slice(0, 5);
    Promise.all(
      projectSlice.map((p) =>
        boqApi.list(p.id).then((list) =>
          list.map((b) => ({ ...b, projectName: p.name })),
        ).catch(() => [] as (BOQ & { projectName?: string })[]),
      ),
    ).then((results) => {
      if (!cancelled) {
        // Flatten and take top 5 most recent
        const allBoqs = results
          .flat()
          .sort((a, b) => new Date(b.updated_at ?? b.created_at).getTime() - new Date(a.updated_at ?? a.created_at).getTime())
          .slice(0, 5);
        setBoqs(allBoqs);
        setBoqsLoaded(true);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [open, projectsLoaded, boqsLoaded, projects]);

  // Reset state when opening
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIndex(0);
      // Small delay to let the portal mount, then focus
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
  }, [open]);

  // Build results
  const results = useMemo(() => {
    const lowerQuery = query.toLowerCase().trim();
    const groups: { title: string; items: SearchResult[] }[] = [];

    if (!lowerQuery) {
      // Show recent items when query is empty
      const recent = loadRecent();
      if (recent.length > 0) {
        groups.push({
          title: t('command_palette.recent', { defaultValue: 'Recent' }),
          items: recent.map((r) => ({
            id: `recent-${r.id}`,
            type: 'recent' as const,
            label: r.label,
            icon: r.type === 'project' ? FolderOpen : r.type === 'boq' ? Table2 : LayoutDashboard,
            path: r.path,
          })),
        });
      }

      // Show all pages
      groups.push({
        title: t('command_palette.pages', { defaultValue: 'Pages' }),
        items: PAGE_RESULTS,
      });

      // Show recent projects (top 5 from API)
      if (projects.length > 0) {
        groups.push({
          title: t('command_palette.projects', { defaultValue: 'Projects' }),
          items: projects.slice(0, 5).map(
            (p): SearchResult => ({
              id: `project-${p.id}`,
              type: 'project',
              label: p.name,
              description: p.description,
              icon: FolderOpen,
              path: `/projects/${p.id}`,
            }),
          ),
        });
      }

      // Show recent BOQs (top 5 from API)
      if (boqs.length > 0) {
        groups.push({
          title: t('command_palette.boqs', { defaultValue: 'Bills of Quantities' }),
          items: boqs.slice(0, 5).map(
            (b): SearchResult => ({
              id: `boq-${b.id}`,
              type: 'boq',
              label: b.name,
              description: b.projectName,
              icon: Table2,
              path: `/boq/${b.id}`,
            }),
          ),
        });
      }

      return groups;
    }

    // Filter pages
    const matchingPages = PAGE_RESULTS.filter((page) => {
      const label = page.labelKey ? t(page.labelKey).toLowerCase() : '';
      return label.includes(lowerQuery);
    });

    if (matchingPages.length > 0) {
      groups.push({
        title: t('command_palette.pages', { defaultValue: 'Pages' }),
        items: matchingPages,
      });
    }

    // Filter projects
    const matchingProjects = projects
      .filter(
        (p) =>
          p.name.toLowerCase().includes(lowerQuery) ||
          p.description?.toLowerCase().includes(lowerQuery),
      )
      .slice(0, 5)
      .map(
        (p): SearchResult => ({
          id: `project-${p.id}`,
          type: 'project',
          label: p.name,
          description: p.description,
          icon: FolderOpen,
          path: `/projects/${p.id}`,
        }),
      );

    if (matchingProjects.length > 0) {
      groups.push({
        title: t('command_palette.projects', { defaultValue: 'Projects' }),
        items: matchingProjects,
      });
    }

    // Filter BOQs
    const matchingBoqs = boqs
      .filter(
        (b) =>
          b.name.toLowerCase().includes(lowerQuery) ||
          b.description?.toLowerCase().includes(lowerQuery) ||
          b.projectName?.toLowerCase().includes(lowerQuery),
      )
      .slice(0, 5)
      .map(
        (b): SearchResult => ({
          id: `boq-${b.id}`,
          type: 'boq',
          label: b.name,
          description: b.projectName,
          icon: Table2,
          path: `/boq/${b.id}`,
        }),
      );

    if (matchingBoqs.length > 0) {
      groups.push({
        title: t('command_palette.boqs', { defaultValue: 'Bills of Quantities' }),
        items: matchingBoqs,
      });
    }

    return groups;
  }, [query, projects, boqs, t]);

  // Flat list for keyboard navigation
  const flatResults = useMemo(() => results.flatMap((g) => g.items), [results]);

  // Clamp active index when results change
  useEffect(() => {
    setActiveIndex((prev) => Math.min(prev, Math.max(0, flatResults.length - 1)));
  }, [flatResults.length]);

  // Navigate to a result
  const selectResult = useCallback(
    (result: SearchResult) => {
      const label = result.label ?? (result.labelKey ? t(result.labelKey) : '');
      pushRecent({
        id: result.id.replace(/^recent-/, ''),
        label,
        path: result.path,
        type: result.type === 'project' ? 'project' : result.type === 'boq' ? 'boq' : 'page',
      });
      navigate(result.path);
      onClose();
    },
    [navigate, onClose, t],
  );

  // Keyboard handling
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setActiveIndex((prev) => (prev + 1) % Math.max(1, flatResults.length));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setActiveIndex((prev) => (prev - 1 + flatResults.length) % Math.max(1, flatResults.length));
          break;
        case 'Enter': {
          e.preventDefault();
          const selected = flatResults[activeIndex];
          if (selected) {
            selectResult(selected);
          }
          break;
        }
        case 'Escape':
          e.preventDefault();
          onClose();
          break;
      }
    },
    [flatResults, activeIndex, selectResult, onClose],
  );

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const activeEl = listRef.current.querySelector('[data-active="true"]');
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  if (!open) return null;

  // Count items to build flat index for rendering
  let flatIndex = -1;

  const dialog = (
    <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Palette */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('command_palette.title', { defaultValue: 'Command Palette' })}
        className={clsx(
          'relative z-10 w-full max-w-lg mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'flex flex-col overflow-hidden',
          'max-h-[min(480px,60vh)]',
        )}
        onKeyDown={handleKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 border-b border-border-light">
          <Search size={18} className="shrink-0 text-content-tertiary" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            placeholder={t('command_palette.placeholder', {
              defaultValue: 'Search pages, projects, BOQs...',
            })}
            className={clsx(
              'flex-1 h-12 bg-transparent text-sm text-content-primary',
              'placeholder:text-content-tertiary',
              'focus:outline-none',
            )}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="text-2xs text-content-tertiary font-mono bg-surface-secondary border border-border-light rounded px-1.5 py-0.5">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="overflow-y-auto px-2 py-2">
          {flatResults.length === 0 && query.trim() !== '' && (
            <div className="px-3 py-8 text-center text-sm text-content-tertiary">
              {t('command_palette.no_results', { defaultValue: 'No results found' })}
            </div>
          )}

          {results.map((group) => (
            <div key={group.title} className="mb-1 last:mb-0">
              <div className="px-3 pt-2 pb-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
                {group.title}
              </div>
              {group.items.map((item) => {
                flatIndex += 1;
                const isActive = flatIndex === activeIndex;
                const idx = flatIndex;
                const Icon = item.icon;
                const label = item.label ?? (item.labelKey ? t(item.labelKey) : '');

                return (
                  <button
                    key={item.id}
                    data-active={isActive}
                    onClick={() => selectResult(item)}
                    onMouseEnter={() => setActiveIndex(idx)}
                    className={clsx(
                      'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left',
                      'text-sm transition-colors',
                      isActive
                        ? 'bg-oe-blue-subtle text-oe-blue'
                        : 'text-content-primary hover:bg-surface-secondary',
                    )}
                  >
                    <Icon size={16} strokeWidth={1.75} className="shrink-0 opacity-70" />
                    <div className="flex-1 min-w-0">
                      <span className="truncate block">{label}</span>
                      {item.description && (
                        <span className="truncate block text-xs text-content-tertiary">
                          {item.description}
                        </span>
                      )}
                    </div>
                    {isActive && (
                      <CornerDownLeft size={14} className="shrink-0 text-content-tertiary" />
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer hints */}
        <div className="border-t border-border-light px-4 py-2 flex items-center gap-4 text-2xs text-content-tertiary">
          <span className="flex items-center gap-1">
            <kbd className="font-mono bg-surface-secondary border border-border-light rounded px-1 py-0.5">
              &uarr;
            </kbd>
            <kbd className="font-mono bg-surface-secondary border border-border-light rounded px-1 py-0.5">
              &darr;
            </kbd>
            {t('command_palette.hint_navigate', { defaultValue: 'navigate' })}
          </span>
          <span className="flex items-center gap-1">
            <kbd className="font-mono bg-surface-secondary border border-border-light rounded px-1 py-0.5">
              &crarr;
            </kbd>
            {t('command_palette.hint_open', { defaultValue: 'open' })}
          </span>
          <span className="flex items-center gap-1">
            <kbd className="font-mono bg-surface-secondary border border-border-light rounded px-1 py-0.5">
              Esc
            </kbd>
            {t('command_palette.hint_close', { defaultValue: 'close' })}
          </span>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
