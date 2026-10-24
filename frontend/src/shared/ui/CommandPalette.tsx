// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Search,
  FolderOpen,
  Table2,
  Database,
  CalendarDays,
  FileText,
  Sparkles,
  CornerDownLeft,
  Users,
  HelpCircle,
  CheckSquare,
  ClipboardList,
  AlertTriangle,
  Globe,
  Keyboard,
  RotateCcw,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi, type BOQ } from '@/features/boq/api';
import { apiGet } from '@/shared/lib/api';
import { getIconOverride, useIconOverridesVersion } from '@/app/layout/menuIcons';
import { registerAppActions } from '@/app/actions/coreActions';
import type { PaletteAction } from '@/shared/lib/actions/registry';
import { MIN_SCORE, fuzzyScore, matchProject, splitProjectQuery } from '@/shared/lib/actions/fuzzy';
import {
  bindingOwners,
  checkShortcut,
  eventToChord,
  formatShortcut,
  SEQUENCE_TIMEOUT_MS,
  useShortcutStore,
  type ShortcutProblem,
} from '@/shared/lib/actions/shortcuts';
import {
  loadRecentActions,
  useActionRunner,
  useActionShortcuts,
  useAvailableActions,
  useBindings,
} from '@/shared/lib/actions/useActionRunner';
import { askAi } from '@/shared/lib/actions/askAi';

registerAppActions();

/* ── Types ─────────────────────────────────────────────────────────────── */

/** A row: an action (maybe aimed at a project), a record link, or the AI hand-off. */
type PaletteRow =
  | { kind: 'action'; id: string; action: PaletteAction; project?: { id: string; name: string } | null; score: number }
  | { kind: 'link'; id: string; label: string; description?: string; icon: LucideIcon; path: string }
  | { kind: 'ask'; id: string; text: string };

interface RowGroup {
  title: string;
  items: PaletteRow[];
}

/** Below this best score the typed text reads as a question, so "Ask AI" goes first. */
const ASK_FIRST_BELOW = 0.55;
const MAX_ACTION_ROWS = 10;

interface GlobalSearchResult {
  module: string;
  type: string;
  id: string;
  title: string;
  subtitle: string;
  url: string;
  score: number;
}

interface UnifiedSearchHit {
  id: string;
  score: number;
  title: string;
  snippet: string;
  text: string;
  module: string;
  project_id: string;
  tenant_id: string;
  payload: Record<string, unknown>;
  collection: string;
}

interface UnifiedSearchResponse {
  query: string;
  types: string[];
  project_id: string | null;
  total: number;
  hits: UnifiedSearchHit[];
  facets: Record<string, number>;
}

function hitToResult(hit: UnifiedSearchHit): GlobalSearchResult {
  const payload = hit.payload as Record<string, unknown> | undefined;
  const url =
    (typeof payload?.url === 'string' && payload.url) ||
    (hit.module && hit.id ? `/${hit.module}/${hit.id}` : '');
  return {
    module: hit.module,
    type: hit.collection,
    id: hit.id,
    title: hit.title,
    subtitle: hit.snippet,
    url,
    score: hit.score,
  };
}

/** Map module names from global search API to Lucide icons. */
const GLOBAL_SEARCH_ICONS: Record<string, LucideIcon> = {
  boq: Table2,
  contacts: Users,
  documents: FileText,
  rfi: HelpCircle,
  tasks: CheckSquare,
  costs: Database,
  meetings: CalendarDays,
  inspections: ClipboardList,
  ncr: AlertTriangle,
};

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/* ── Component ─────────────────────────────────────────────────────────── */

const SHORTCUT_PROBLEM_KEYS: Record<ShortcutProblem, [string, string]> = {
  invalid: ['palette.shortcut.invalid', 'That key cannot be used.'],
  reserved: ['palette.shortcut.reserved', 'The browser or the system already uses this key.'],
  needs_modifier: ['palette.shortcut.needs_modifier', 'Use two keys in a row (G then B) or add Ctrl / Cmd.'],
  conflict: ['palette.shortcut.conflict', 'Already used by "{{action}}".'],
};

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { t, i18n } = useTranslation();
  useIconOverridesVersion();
  const navigate = useNavigate();
  const location = useLocation();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [boqs, setBoqs] = useState<(BOQ & { projectName?: string })[]>([]);
  const [boqsLoaded, setBoqsLoaded] = useState(false);
  const [globalResults, setGlobalResults] = useState<GlobalSearchResult[]>([]);
  const [globalSearchLoading, setGlobalSearchLoading] = useState(false);
  const globalSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Rebinding: which action is listening for keys, and why the last try was refused.
  const [recordingFor, setRecordingFor] = useState<string | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const recordFirst = useRef<{ key: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  const actions = useAvailableActions();
  const bindings = useBindings();
  const overrides = useShortcutStore((s) => s.overrides);
  const setBinding = useShortcutStore((s) => s.setBinding);
  const resetBinding = useShortcutStore((s) => s.resetBinding);
  const runAction = useActionRunner();
  useActionShortcuts(open);

  const lang = i18n.language;
  const titleOf = useCallback(
    (a: PaletteAction) => String(t(a.titleKey, { defaultValue: a.defaultTitle })),
    [t],
  );

  // Debounced global search: fires 300ms after the user stops typing.
  useEffect(() => {
    if (!open) return;
    const trimmed = (splitProjectQuery(query)?.action ?? query).trim();
    if (trimmed.length < 2) {
      setGlobalResults([]);
      return;
    }

    if (globalSearchTimer.current) clearTimeout(globalSearchTimer.current);
    globalSearchTimer.current = setTimeout(() => {
      setGlobalSearchLoading(true);
      apiGet<UnifiedSearchResponse>(
        `/v1/search/?q=${encodeURIComponent(trimmed)}&final_limit=10`,
      )
        .then((data) => {
          setGlobalResults((data.hits ?? []).map(hitToResult));
        })
        .catch(() => {
          setGlobalResults([]);
        })
        .finally(() => {
          setGlobalSearchLoading(false);
        });
    }, 300);

    return () => {
      if (globalSearchTimer.current) clearTimeout(globalSearchTimer.current);
    };
  }, [query, open]);

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
    if (!open) return;
    setQuery('');
    setActiveIndex(0);
    setRecordingFor(null);
    setRecordError(null);
    // Cancel on unmount / re-close so a queued frame can't fire focus()
    // against an unmounted ref.
    const rafId = requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    return () => cancelAnimationFrame(rafId);
  }, [open]);

  const actionTargets = useCallback(
    (a: PaletteAction) => {
      const out = [titleOf(a)];
      if (a.keywordsKey) out.push(String(t(a.keywordsKey, { defaultValue: a.defaultKeywords ?? '' })));
      else if (a.defaultKeywords) out.push(a.defaultKeywords);
      // The English title still finds the action for people who think in English.
      if (a.defaultTitle && lang !== 'en') out.push(a.defaultTitle);
      return out;
    },
    [t, titleOf, lang],
  );

  // Build results
  const results = useMemo((): RowGroup[] => {
    const projectLink = (p: Project): PaletteRow => ({
      kind: 'link',
      id: `project-${p.id}`,
      label: p.name,
      description: p.description,
      icon: FolderOpen,
      path: `/projects/${p.id}`,
    });
    const boqLink = (b: BOQ & { projectName?: string }): PaletteRow => ({
      kind: 'link',
      id: `boq-${b.id}`,
      label: b.name,
      description: b.projectName,
      icon: Table2,
      path: `/boq/${b.id}`,
    });
    const trimmed = query.trim();
    const groups: RowGroup[] = [];
    const byId = new Map(actions.map((a) => [a.id, a]));
    const recentIds = loadRecentActions();

    if (!trimmed) {
      const recentRows: PaletteRow[] = [];
      for (const r of recentIds) {
        const a = byId.get(r.actionId);
        if (!a) continue;
        const project = r.projectId ? { id: r.projectId, name: r.projectName ?? '' } : null;
        recentRows.push({ kind: 'action', id: `recent-${a.id}-${r.projectId ?? ''}`, action: a, project, score: 1 });
      }
      if (recentRows.length > 0) {
        groups.push({ title: t('command_palette.recent', { defaultValue: 'Recent' }), items: recentRows });
      }
      const quick = actions
        .filter((a) => a.group !== 'navigate' && a.group !== 'project')
        .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
      if (quick.length > 0) {
        groups.push({
          title: t('palette.group.actions', { defaultValue: 'Actions' }),
          items: quick.map((a): PaletteRow => ({ kind: 'action', id: a.id, action: a, score: 1 })),
        });
      }
      if (projects.length > 0) {
        groups.push({
          title: t('command_palette.projects', { defaultValue: 'Projects' }),
          items: projects.slice(0, 5).map(projectLink),
        });
      }
      if (boqs.length > 0) {
        groups.push({
          title: t('command_palette.boqs', { defaultValue: 'Bills of Quantities' }),
          items: boqs.slice(0, 5).map(boqLink),
        });
      }
      groups.push({
        title: t('command_palette.pages', { defaultValue: 'Pages' }),
        items: actions
          .filter((a) => a.group === 'navigate')
          .map((a): PaletteRow => ({ kind: 'action', id: a.id, action: a, score: 1 })),
      });
      return groups;
    }

    const recentBoost = new Set(recentIds.map((r) => r.actionId));
    const ask: PaletteRow = { kind: 'ask', id: 'ask-ai', text: trimmed };
    const aiGroup: RowGroup = { title: t('palette.group.ai', { defaultValue: 'AI assistant' }), items: [ask] };
    const scoped = splitProjectQuery(trimmed);

    // "project Berlin > quantities": the project first, then its actions.
    if (scoped) {
      const project = matchProject(scoped.project, projects, lang);
      if (project) {
        const target = { id: project.id, name: project.name };
        const rows = actions
          .filter((a) => a.scope === 'project')
          .map((a) => ({ a, s: scoped.action ? fuzzyScore(scoped.action, actionTargets(a), lang) : 0.5 }))
          .filter(({ s }) => s >= MIN_SCORE)
          .sort((x, y) => y.s - x.s || (y.a.priority ?? 0) - (x.a.priority ?? 0))
          .map(({ a, s }): PaletteRow => ({ kind: 'action', id: `${a.id}@${project.id}`, action: a, project: target, score: s }));
        groups.push({ title: project.name, items: rows });
      } else {
        groups.push({
          title: t('command_palette.projects', { defaultValue: 'Projects' }),
          items: projects
            .filter((p) => fuzzyScore(scoped.project, [p.name], lang) >= MIN_SCORE)
            .slice(0, 5)
            .map(projectLink),
        });
      }
      groups.push(aiGroup);
      return groups.filter((g) => g.items.length > 0);
    }

    const scored = actions
      .map((a) => ({ a, s: fuzzyScore(trimmed, actionTargets(a), lang) + (recentBoost.has(a.id) ? 0.05 : 0) }))
      .filter(({ s }) => s >= MIN_SCORE)
      .sort((x, y) => y.s - x.s || (y.a.priority ?? 0) - (x.a.priority ?? 0))
      .slice(0, MAX_ACTION_ROWS);
    const best = scored[0]?.s ?? 0;
    if (best < ASK_FIRST_BELOW) groups.push(aiGroup);

    if (scored.length > 0) {
      groups.push({
        title: t('palette.group.actions', { defaultValue: 'Actions' }),
        items: scored.map(({ a, s }): PaletteRow => ({ kind: 'action', id: a.id, action: a, score: s })),
      });
    }

    const matchingProjects = projects
      .filter((p) => fuzzyScore(trimmed, [p.name, p.description ?? ''], lang) >= 0.6)
      .slice(0, 5)
      .map(projectLink);
    if (matchingProjects.length > 0) {
      groups.push({ title: t('command_palette.projects', { defaultValue: 'Projects' }), items: matchingProjects });
    }

    const matchingBoqs = boqs
      .filter((b) => fuzzyScore(trimmed, [b.name, b.description ?? '', b.projectName ?? ''], lang) >= 0.6)
      .slice(0, 5)
      .map(boqLink);
    if (matchingBoqs.length > 0) {
      groups.push({ title: t('command_palette.boqs', { defaultValue: 'Bills of Quantities' }), items: matchingBoqs });
    }

    // Global search results (from backend API), grouped by module.
    if (globalResults.length > 0) {
      const moduleGroups = new Map<string, PaletteRow[]>();
      for (const gr of globalResults) {
        if (!gr.url) continue;
        if (!moduleGroups.has(gr.module)) moduleGroups.set(gr.module, []);
        moduleGroups.get(gr.module)!.push({
          kind: 'link',
          id: `global-${gr.type}-${gr.id}`,
          label: gr.title,
          description: gr.subtitle,
          icon: GLOBAL_SEARCH_ICONS[gr.module] ?? Globe,
          path: gr.url,
        });
      }
      for (const [moduleName, items] of moduleGroups) {
        const moduleLabel = moduleName.charAt(0).toUpperCase() + moduleName.slice(1);
        groups.push({
          title: t(`command_palette.global_${moduleName}`, { defaultValue: moduleLabel }),
          items,
        });
      }
    }

    if (best >= ASK_FIRST_BELOW) groups.push(aiGroup);
    return groups;
  }, [query, actions, projects, boqs, globalResults, t, lang, actionTargets]);

  // Flat list for keyboard navigation
  const flatResults = useMemo(() => results.flatMap((g) => g.items), [results]);

  // Clamp active index when results change
  useEffect(() => {
    setActiveIndex((prev) => Math.min(prev, Math.max(0, flatResults.length - 1)));
  }, [flatResults.length]);

  const selectResult = useCallback(
    (row: PaletteRow) => {
      onClose();
      if (row.kind === 'action') runAction(row.action, row.project ?? null);
      else if (row.kind === 'link') navigate(row.path);
      else askAi(row.text, { pathname: location.pathname, navigate });
    },
    [navigate, onClose, runAction, location.pathname],
  );

  /* ── Rebinding ─────────────────────────────────────────────────────── */

  const stopRecording = useCallback(() => {
    if (recordFirst.current) clearTimeout(recordFirst.current.timer);
    recordFirst.current = null;
    setRecordingFor(null);
    inputRef.current?.focus();
  }, []);

  const tryBind = useCallback(
    (actionId: string, shortcut: string) => {
      const problem = checkShortcut(shortcut, actionId, bindingOwners(bindings));
      if (problem) {
        const [key, fallback] = SHORTCUT_PROBLEM_KEYS[problem.problem];
        const holder = problem.holder ? actions.find((a) => a.id === problem.holder) : undefined;
        setRecordError(String(t(key, { defaultValue: fallback, action: holder ? titleOf(holder) : problem.holder })));
        return;
      }
      setBinding(actionId, shortcut);
      setRecordError(null);
      stopRecording();
    },
    [bindings, actions, setBinding, stopRecording, t, titleOf],
  );

  const handleRecordKey = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!recordingFor) return false;
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Escape') {
        setRecordError(null);
        stopRecording();
        return true;
      }
      if (e.key === 'Backspace' || e.key === 'Delete') {
        setBinding(recordingFor, null);
        setRecordError(null);
        stopRecording();
        return true;
      }
      const chord = eventToChord(e.nativeEvent);
      if (!chord) return true;
      if (chord.includes('+') || !/^[A-Z0-9]$/.test(chord)) {
        if (recordFirst.current) clearTimeout(recordFirst.current.timer);
        recordFirst.current = null;
        tryBind(recordingFor, chord);
        return true;
      }
      const first = recordFirst.current;
      if (first) {
        clearTimeout(first.timer);
        recordFirst.current = null;
        tryBind(recordingFor, `${first.key} ${chord}`);
        return true;
      }
      const forAction = recordingFor;
      recordFirst.current = {
        key: chord,
        timer: setTimeout(() => {
          recordFirst.current = null;
          tryBind(forAction, chord);
        }, SEQUENCE_TIMEOUT_MS),
      };
      return true;
    },
    [recordingFor, setBinding, stopRecording, tryBind],
  );

  // Keyboard handling
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (handleRecordKey(e)) return;
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
          if (selected) selectResult(selected);
          break;
        }
        case 'Escape':
          e.preventDefault();
          onClose();
          break;
      }
    },
    [flatResults, activeIndex, selectResult, onClose, handleRecordKey],
  );

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const activeEl = listRef.current.querySelector('[data-active="true"]');
    if (activeEl) {
      activeEl.scrollIntoView?.({ block: 'nearest' });
    }
  }, [activeIndex]);

  if (!open) return null;

  // Count items to build flat index for rendering
  let flatIndex = -1;
  const changeShortcutLabel = t('palette.shortcut.change', { defaultValue: 'Change shortcut' });
  const resetShortcutLabel = t('palette.shortcut.reset', { defaultValue: 'Restore the default shortcut' });

  const dialog = (
    <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onClose}
      />

      {/* Palette */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('command_palette.title', { defaultValue: 'Command Palette' })}
        className={clsx(
          'relative z-10 w-full max-w-xl mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'flex flex-col overflow-hidden',
          'max-h-[min(520px,65vh)]',
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
            placeholder={t('palette.placeholder', {
              defaultValue: 'Type an action, a page or a question. "Project > page" works too',
            })}
            aria-label={t('command_palette.title', { defaultValue: 'Command Palette' })}
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

        {recordingFor && (
          <div
            role="status"
            className="px-4 py-2 text-xs border-b border-border-light bg-oe-blue-subtle text-oe-blue-text"
            data-testid="palette-recording"
          >
            {recordError ??
              t('palette.shortcut.recording', {
                defaultValue:
                  'Press the new shortcut: two keys in a row (G then B) or Ctrl / Cmd with a key. Esc cancels, Backspace removes it.',
              })}
          </div>
        )}

        {/* Results */}
        <div ref={listRef} className="overflow-y-auto px-2 py-2">
          {flatResults.length === 0 && query.trim() !== '' && !globalSearchLoading && (
            <div className="px-3 py-8 text-center text-sm text-content-tertiary">
              {t('command_palette.no_results', { defaultValue: 'No results found' })}
            </div>
          )}
          {globalSearchLoading && query.trim().length >= 2 && (
            <div className="px-3 py-3 text-center text-xs text-content-tertiary animate-pulse">
              {t('command_palette.searching', { defaultValue: 'Searching across all modules...' })}
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
                let Icon: LucideIcon;
                let label: string;
                let description: string | undefined;
                let shortcut: string | undefined;
                if (item.kind === 'action') {
                  const a = item.action;
                  // A menu row takes the icon the user gave that menu item.
                  Icon = (a.path && a.group === 'navigate' && getIconOverride(a.path)) || a.icon || Zap;
                  label = item.project ? `${item.project.name} › ${titleOf(a)}` : titleOf(a);
                  shortcut = bindings.get(a.id);
                  if (a.scope === 'project' && !item.project) {
                    description = t('palette.project_scoped_hint', {
                      defaultValue: 'For the active project. Type "project name > {{title}}" for another one',
                      title: titleOf(a),
                    });
                  }
                } else if (item.kind === 'link') {
                  Icon = item.icon;
                  label = item.label;
                  description = item.description;
                } else {
                  Icon = Sparkles;
                  label = t('palette.ask_ai', { defaultValue: 'Ask AI: "{{text}}"', text: item.text });
                  description = t('palette.ask_ai_hint', {
                    defaultValue:
                      'Opens the assistant with this text and the current page. Nothing is sent until you press Enter there.',
                  });
                }
                const actionId = item.kind === 'action' ? item.action.id : null;
                const overridden = actionId !== null && actionId in overrides;

                return (
                  <div
                    key={item.id}
                    data-active={isActive}
                    data-testid={`palette-row-${item.id}`}
                    onMouseEnter={() => setActiveIndex(idx)}
                    className={clsx(
                      'group flex w-full items-center gap-1 rounded-lg pe-1 text-sm transition-colors',
                      isActive
                        ? 'bg-oe-blue-subtle text-oe-blue-text'
                        : 'text-content-primary hover:bg-surface-secondary',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => selectResult(item)}
                      title={shortcut ? `${label} (${formatShortcut(shortcut)})` : label}
                      className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
                    >
                      <Icon size={16} strokeWidth={1.75} className="shrink-0 opacity-70" />
                      <div className="flex-1 min-w-0">
                        <span className="truncate block">{label}</span>
                        {description && (
                          <span className="truncate block text-xs text-content-tertiary">{description}</span>
                        )}
                      </div>
                      {shortcut && (
                        <kbd className="shrink-0 font-mono text-2xs text-content-tertiary bg-surface-secondary border border-border-light rounded px-1.5 py-0.5">
                          {formatShortcut(shortcut)}
                        </kbd>
                      )}
                      {isActive && !actionId && (
                        <CornerDownLeft size={14} className="shrink-0 text-content-tertiary" />
                      )}
                    </button>
                    {actionId && (
                      <>
                        <button
                          type="button"
                          aria-label={`${changeShortcutLabel}: ${label}`}
                          title={changeShortcutLabel}
                          data-testid={`palette-rebind-${actionId}`}
                          onClick={() => {
                            setRecordError(null);
                            setRecordingFor(actionId);
                          }}
                          className={clsx(
                            'shrink-0 rounded p-1 text-content-tertiary hover:text-content-primary focus:opacity-100',
                            recordingFor === actionId || isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
                          )}
                        >
                          <Keyboard size={14} />
                        </button>
                        {overridden && (
                          <button
                            type="button"
                            aria-label={resetShortcutLabel}
                            title={resetShortcutLabel}
                            onClick={() => resetBinding(actionId)}
                            className="shrink-0 rounded p-1 text-content-tertiary hover:text-content-primary opacity-0 group-hover:opacity-100 focus:opacity-100"
                          >
                            <RotateCcw size={13} />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer hints */}
        <div className="border-t border-border-light px-4 py-2 flex flex-wrap items-center gap-4 text-2xs text-content-tertiary">
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
            {t('palette.hint_run', { defaultValue: 'run' })}
          </span>
          <span className="flex items-center gap-1">
            <Keyboard size={11} />
            {t('palette.hint_rebind', { defaultValue: 'change shortcut' })}
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
