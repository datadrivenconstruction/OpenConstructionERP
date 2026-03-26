/**
 * TranslationManager — in-app UI for viewing and editing translation keys.
 *
 * Features:
 *  - Table of all keys with columns: Key, English (default), Current Language
 *  - Search/filter by key name or value
 *  - Inline editing: click a cell to edit the translation for current language
 *  - Saves custom overrides to localStorage under `oe_custom_translations_{lang}`
 *  - "Reset to default" button per key
 *  - "Export translations" button (downloads JSON file)
 *  - "Import translations" button (uploads JSON file)
 *  - Stats: total keys, translated (customised) count, missing count
 */

import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search,
  Download,
  Upload,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  X,
  Pencil,
  Check,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge } from '@/shared/ui';
import { triggerDownload } from '@/shared/lib/api';
import i18n from '@/app/i18n';

// ── Constants ─────────────────────────────────────────────────────────────────

const LS_KEY_PREFIX = 'oe_custom_translations_';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Load custom translations from localStorage for a given language code. */
export function loadCustomTranslations(lang: string): Record<string, string> {
  try {
    const raw = localStorage.getItem(`${LS_KEY_PREFIX}${lang}`);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, string>;
  } catch {
    return {};
  }
}

/** Persist custom translations to localStorage and push them into i18next. */
export function saveCustomTranslations(
  lang: string,
  overrides: Record<string, string>,
): void {
  localStorage.setItem(`${LS_KEY_PREFIX}${lang}`, JSON.stringify(overrides));
  // Merge into i18next so changes take effect immediately (deep=true, overwrite=true)
  i18n.addResourceBundle(lang, 'translation', overrides, true, true);
}

/**
 * Return a flat map of ALL translation keys for a given language, starting
 * with the English bundled baseline and then overlaying language-specific
 * resources already loaded by i18next.
 */
function getAllKeysForLanguage(lang: string): Record<string, string> {
  // Start from English baseline (always complete)
  const enBundle = (i18n.getResourceBundle('en', 'translation') as Record<string, string>) ?? {};
  // Get the target language bundle (may be partial)
  const langBundle =
    lang === 'en'
      ? {}
      : ((i18n.getResourceBundle(lang, 'translation') as Record<string, string>) ?? {});

  return { ...enBundle, ...langBundle };
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface TranslationRow {
  key: string;
  english: string;
  current: string;
  isCustom: boolean;
}

// ── EditCell ──────────────────────────────────────────────────────────────────

interface EditCellProps {
  value: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  placeholder: string;
}

function EditCell({ value, onSave, onCancel, placeholder }: EditCellProps) {
  const [localValue, setLocalValue] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') onSave(localValue);
    if (e.key === 'Escape') onCancel();
  };

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        value={localValue}
        onChange={(e) => setLocalValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="flex-1 h-7 rounded-md border border-oe-blue bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 min-w-0"
      />
      <button
        onClick={() => onSave(localValue)}
        className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-semantic-success hover:bg-semantic-success/10 transition-colors"
        title="Save"
      >
        <Check size={13} />
      </button>
      <button
        onClick={onCancel}
        className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary transition-colors"
        title="Cancel"
      >
        <X size={13} />
      </button>
    </div>
  );
}

// ── TranslationManager ────────────────────────────────────────────────────────

export function TranslationManager() {
  const { t, i18n: i18next } = useTranslation();
  const currentLang = i18next.language ?? 'en';

  // Custom overrides stored separately so we can detect which keys are modified
  const [customOverrides, setCustomOverrides] = useState<Record<string, string>>(
    () => loadCustomTranslations(currentLang),
  );

  // Reload overrides when language switches
  useEffect(() => {
    setCustomOverrides(loadCustomTranslations(currentLang));
  }, [currentLang]);

  // Search query
  const [query, setQuery] = useState('');

  // Editing state: key currently being edited
  const [editingKey, setEditingKey] = useState<string | null>(null);

  // File input ref for import
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Build full row list from all English keys + current lang overrides
  const allRows = useMemo<TranslationRow[]>(() => {
    const enBundle =
      (i18n.getResourceBundle('en', 'translation') as Record<string, string>) ?? {};
    const langBundle =
      currentLang === 'en'
        ? {}
        : ((i18n.getResourceBundle(currentLang, 'translation') as Record<string, string>) ?? {});

    return Object.keys(enBundle)
      .sort()
      .map((key) => {
        const english = enBundle[key] ?? '';
        const fromLangBundle = langBundle[key] ?? '';
        const fromOverride = customOverrides[key] ?? '';
        const current = fromOverride || fromLangBundle || (currentLang === 'en' ? english : '');
        const isCustom = key in customOverrides;
        return { key, english, current, isCustom };
      });
  }, [currentLang, customOverrides]);

  // Stats
  const totalKeys = allRows.length;
  const translatedCount = useMemo(
    () => allRows.filter((r) => r.current !== '' && r.current !== r.english).length,
    [allRows],
  );
  const customCount = useMemo(() => allRows.filter((r) => r.isCustom).length, [allRows]);
  const missingCount = useMemo(
    () => (currentLang === 'en' ? 0 : allRows.filter((r) => r.current === '').length),
    [allRows, currentLang],
  );

  // Filtered rows
  const filteredRows = useMemo(() => {
    if (!query.trim()) return allRows;
    const q = query.toLowerCase();
    return allRows.filter(
      (r) =>
        r.key.toLowerCase().includes(q) ||
        r.english.toLowerCase().includes(q) ||
        r.current.toLowerCase().includes(q),
    );
  }, [allRows, query]);

  // ── Handlers ──

  const handleSave = useCallback(
    (key: string, value: string) => {
      const next = { ...customOverrides };
      if (value.trim() === '') {
        delete next[key];
      } else {
        next[key] = value;
      }
      setCustomOverrides(next);
      saveCustomTranslations(currentLang, next);
      setEditingKey(null);
    },
    [customOverrides, currentLang],
  );

  const handleReset = useCallback(
    (key: string) => {
      const next = { ...customOverrides };
      delete next[key];
      setCustomOverrides(next);
      saveCustomTranslations(currentLang, next);
    },
    [customOverrides, currentLang],
  );

  const handleExport = useCallback(() => {
    const allTranslations = getAllKeysForLanguage(currentLang);
    // Merge in any custom overrides on top
    const merged = { ...allTranslations, ...customOverrides };
    const json = JSON.stringify(merged, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    triggerDownload(blob, `translations_${currentLang}.json`);
  }, [currentLang, customOverrides]);

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const parsed = JSON.parse(ev.target?.result as string) as Record<string, string>;
          // Only keep string values
          const clean: Record<string, string> = {};
          for (const [k, v] of Object.entries(parsed)) {
            if (typeof v === 'string') clean[k] = v;
          }
          setCustomOverrides(clean);
          saveCustomTranslations(currentLang, clean);
        } catch {
          // Silently ignore invalid JSON
        }
      };
      reader.readAsText(file);
      // Reset input so re-importing the same file works
      e.target.value = '';
    },
    [currentLang],
  );

  // ── Render ──

  return (
    <Card data-testid="translation-manager">
      <CardHeader
        title={t('settings.translation_manager_title', {
          defaultValue: 'Translation Manager',
        })}
        subtitle={t('settings.translation_manager_subtitle', {
          defaultValue: 'View and customise translation keys for the current language.',
        })}
      />

      <CardContent>
        {/* Stats bar */}
        <div
          className="mb-4 flex flex-wrap gap-3"
          data-testid="tm-stats"
        >
          <div className="flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5">
            <span className="text-xs text-content-tertiary">
              {t('settings.tm_total_keys', { defaultValue: 'Total keys' })}
            </span>
            <span className="text-sm font-semibold text-content-primary" data-testid="tm-stat-total">
              {totalKeys}
            </span>
          </div>
          <div className="flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5">
            <CheckCircle2 size={13} className="text-semantic-success" />
            <span className="text-xs text-content-tertiary">
              {t('settings.tm_translated', { defaultValue: 'Translated' })}
            </span>
            <span className="text-sm font-semibold text-semantic-success" data-testid="tm-stat-translated">
              {translatedCount}
            </span>
          </div>
          <div className="flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5">
            <Pencil size={13} className="text-oe-blue" />
            <span className="text-xs text-content-tertiary">
              {t('settings.tm_custom', { defaultValue: 'Custom overrides' })}
            </span>
            <span className="text-sm font-semibold text-oe-blue" data-testid="tm-stat-custom">
              {customCount}
            </span>
          </div>
          {missingCount > 0 && (
            <div className="flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5">
              <AlertCircle size={13} className="text-semantic-warning" />
              <span className="text-xs text-content-tertiary">
                {t('settings.tm_missing', { defaultValue: 'Missing' })}
              </span>
              <span className="text-sm font-semibold text-semantic-warning" data-testid="tm-stat-missing">
                {missingCount}
              </span>
            </div>
          )}
        </div>

        {/* Toolbar */}
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          {/* Search input */}
          <div className="relative flex-1 max-w-sm">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('settings.tm_search_placeholder', {
                defaultValue: 'Search keys or values...',
              })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-8 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-normal"
              data-testid="tm-search"
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Upload size={13} />}
              onClick={handleImportClick}
              data-testid="tm-import-btn"
            >
              {t('settings.tm_import', { defaultValue: 'Import' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={13} />}
              onClick={handleExport}
              data-testid="tm-export-btn"
            >
              {t('settings.tm_export', { defaultValue: 'Export' })}
            </Button>
          </div>
        </div>

        {/* Hidden file input for import */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={handleFileChange}
          data-testid="tm-file-input"
        />

        {/* Translation table */}
        <div className="overflow-hidden rounded-lg border border-border-light">
          {/* Table header */}
          <div className="grid grid-cols-[2fr_2fr_2fr_auto] gap-0 bg-surface-secondary border-b border-border-light">
            <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('settings.tm_col_key', { defaultValue: 'Key' })}
            </div>
            <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary border-l border-border-light">
              {t('settings.tm_col_english', { defaultValue: 'English' })}
            </div>
            <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary border-l border-border-light">
              {t('settings.tm_col_current', { defaultValue: 'Current Language' })}
            </div>
            <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary border-l border-border-light w-20">
              {t('settings.tm_col_actions', { defaultValue: '' })}
            </div>
          </div>

          {/* Rows */}
          <div className="max-h-[480px] overflow-y-auto" data-testid="tm-table-body">
            {filteredRows.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-content-tertiary">
                {t('settings.tm_no_results', { defaultValue: 'No keys match your search.' })}
              </div>
            ) : (
              filteredRows.map((row) => (
                <div
                  key={row.key}
                  className={`grid grid-cols-[2fr_2fr_2fr_auto] gap-0 border-b border-border-light last:border-b-0 hover:bg-surface-secondary/50 transition-colors ${
                    row.isCustom ? 'bg-oe-blue-subtle/30' : ''
                  }`}
                  data-testid={`tm-row-${row.key}`}
                >
                  {/* Key */}
                  <div className="flex items-center gap-1.5 px-3 py-2 min-w-0">
                    <code className="truncate text-xs text-content-secondary font-mono" title={row.key}>
                      {row.key}
                    </code>
                    {row.isCustom && (
                      <Badge variant="blue" size="sm" className="flex-shrink-0">
                        {t('settings.tm_custom_badge', { defaultValue: 'custom' })}
                      </Badge>
                    )}
                  </div>

                  {/* English */}
                  <div className="flex items-center border-l border-border-light px-3 py-2 min-w-0">
                    <span
                      className="truncate text-sm text-content-secondary"
                      title={row.english}
                    >
                      {row.english || (
                        <span className="italic text-content-tertiary">
                          {t('settings.tm_empty', { defaultValue: '(empty)' })}
                        </span>
                      )}
                    </span>
                  </div>

                  {/* Current language — editable */}
                  <div className="flex items-center border-l border-border-light px-3 py-2 min-w-0">
                    {editingKey === row.key ? (
                      <EditCell
                        value={row.current}
                        onSave={(v) => handleSave(row.key, v)}
                        onCancel={() => setEditingKey(null)}
                        placeholder={row.english}
                      />
                    ) : (
                      <button
                        className="group flex w-full items-center gap-1 text-left"
                        onClick={() => setEditingKey(row.key)}
                        title={t('settings.tm_click_to_edit', { defaultValue: 'Click to edit' })}
                        data-testid={`tm-edit-cell-${row.key}`}
                      >
                        <span
                          className={`flex-1 truncate text-sm ${
                            row.current
                              ? 'text-content-primary'
                              : 'italic text-semantic-warning'
                          }`}
                          title={row.current || row.english}
                        >
                          {row.current ||
                            (currentLang !== 'en' ? (
                              <span className="italic text-semantic-warning text-xs">
                                {t('settings.tm_missing_label', { defaultValue: '(missing)' })}
                              </span>
                            ) : (
                              row.english
                            ))}
                        </span>
                        <Pencil
                          size={11}
                          className="flex-shrink-0 text-content-tertiary opacity-0 group-hover:opacity-100 transition-opacity"
                        />
                      </button>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center justify-center border-l border-border-light px-2 py-2 w-20">
                    {row.isCustom && (
                      <button
                        onClick={() => handleReset(row.key)}
                        title={t('settings.tm_reset_tooltip', { defaultValue: 'Reset to default' })}
                        className="flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-warning hover:bg-semantic-warning/10 transition-colors"
                        data-testid={`tm-reset-${row.key}`}
                      >
                        <RotateCcw size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Footer count */}
        {query.trim() && (
          <p className="mt-2 text-xs text-content-tertiary">
            {t('settings.tm_showing', {
              defaultValue: 'Showing {{count}} of {{total}} keys',
              count: filteredRows.length,
              total: totalKeys,
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
