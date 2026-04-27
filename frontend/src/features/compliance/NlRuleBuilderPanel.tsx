// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Natural-language Compliance Rule Builder (T13).
//
// A two-pane authoring tool:
//   • Left pane  — NL textarea + language selector + Generate / Save CTAs.
//   • Right pane — read-only DSL YAML preview with confidence badge.
//
// Editing either side keeps both in sync:
//   - Typing on the NL side and pressing Generate (or Ctrl/⌘+Enter)
//     calls /v1/compliance/dsl/from-nl and updates the YAML pane.
//   - The user can then click "Save as Compliance Rule" which posts
//     the YAML to the existing /v1/compliance/dsl/compile endpoint.
//
// AI fallback is opt-in via a checkbox. If the user has no API key
// configured the backend silently falls through to the deterministic
// pattern matcher — never crashes.

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Sparkles, Save, Wand2, AlertTriangle } from 'lucide-react';
import { Button, Card, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  parseNlToDsl,
  listNlPatterns,
  saveDslRule,
  type NlBuildResult,
} from './api';
import { DslPreview } from './DslPreview';
import { NlPatternHints } from './NlPatternHints';

type SupportedLang = 'en' | 'de' | 'ru';

const LANG_OPTIONS: { value: SupportedLang; label: string }[] = [
  { value: 'en', label: 'EN' },
  { value: 'de', label: 'DE' },
  { value: 'ru', label: 'RU' },
];

export function NlRuleBuilderPanel() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [text, setText] = useState('');
  const [lang, setLang] = useState<SupportedLang>('en');
  const [useAi, setUseAi] = useState(false);
  const [result, setResult] = useState<NlBuildResult | null>(null);

  // Pattern catalogue is loaded once.
  const { data: patterns = [] } = useQuery({
    queryKey: ['compliance', 'nl-patterns'],
    queryFn: listNlPatterns,
    staleTime: 60 * 60_000,
  });

  const generate = useMutation({
    mutationFn: () => parseNlToDsl({ text, lang, use_ai: useAi }),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dsl_yaml) {
        addToast({
          type: 'info',
          title: t('compliance.nl.no_match', {
            defaultValue: 'No pattern matched the input.',
          }),
        });
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('compliance.nl.save_failed', {
          defaultValue: 'Generation failed',
        }),
        message: err.message,
      });
    },
  });

  const save = useMutation({
    mutationFn: () => {
      if (!result?.dsl_yaml) {
        return Promise.reject(new Error('No DSL to save.'));
      }
      return saveDslRule(result.dsl_yaml, true);
    },
    onSuccess: (row) => {
      addToast({
        type: 'success',
        title: t('compliance.nl.saved', {
          defaultValue: 'Rule saved successfully.',
        }),
        message: row.rule_id,
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('compliance.nl.save_failed', {
          defaultValue: 'Could not save rule',
        }),
        message: err.message,
      });
    },
  });

  // Ctrl/⌘+Enter inside the textarea triggers Generate.
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (text.trim() && !generate.isPending) generate.mutate();
      }
    },
    [text, generate],
  );

  // If the user clears the textarea, drop the stale preview too.
  useEffect(() => {
    if (!text.trim() && result) {
      setResult(null);
    }
  }, [text, result]);

  const handlePickExample = useCallback((example: string) => {
    setText(example);
    setResult(null);
  }, []);

  const handleCopyYaml = useCallback(async () => {
    if (!result?.dsl_yaml) return;
    try {
      await navigator.clipboard.writeText(result.dsl_yaml);
      addToast({
        type: 'success',
        title: t('common.copied', { defaultValue: 'Copied' }),
      });
    } catch {
      // Clipboard may be blocked in some browsers — silent ignore.
    }
  }, [result, addToast, t]);

  const confidencePct =
    result && result.confidence > 0 ? Math.round(result.confidence * 100) : null;

  const methodLabel =
    result?.used_method === 'pattern'
      ? t('compliance.nl.method_pattern', { defaultValue: 'Pattern matched' })
      : result?.used_method === 'ai'
        ? t('compliance.nl.method_ai', { defaultValue: 'AI fallback' })
        : t('compliance.nl.method_fallback', { defaultValue: 'No match' });

  const methodVariant: 'success' | 'warning' | 'error' =
    result?.used_method === 'pattern'
      ? 'success'
      : result?.used_method === 'ai'
        ? 'warning'
        : 'error';

  return (
    <div className="w-full animate-fade-in" data-testid="nl-rule-builder-panel">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('compliance.nl.title', {
            defaultValue: 'Natural Language Rule Builder',
          })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('compliance.nl.subtitle', {
            defaultValue:
              'Describe your rule in plain English, German, or Russian — the builder generates valid DSL.',
          })}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[2fr_2fr_1fr]">
        {/* ── NL pane ─────────────────────────────────────────────── */}
        <Card>
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <label
                htmlFor="nl-input"
                className="text-sm font-semibold text-content-primary"
              >
                {t('compliance.nl.title', {
                  defaultValue: 'Natural Language',
                })}
              </label>
              <div className="flex items-center gap-1.5">
                {LANG_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setLang(opt.value)}
                    aria-pressed={lang === opt.value}
                    data-testid={`nl-lang-${opt.value}`}
                    className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                      lang === opt.value
                        ? 'bg-oe-blue text-content-inverse'
                        : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              id="nl-input"
              data-testid="nl-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={8}
              placeholder={t('compliance.nl.input_placeholder', {
                defaultValue:
                  'e.g. all walls must have a fire-rating property',
              })}
              className="w-full resize-none rounded-lg border border-border bg-surface-primary p-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input
                type="checkbox"
                data-testid="nl-use-ai"
                checked={useAi}
                onChange={(e) => setUseAi(e.target.checked)}
              />
              {t('compliance.nl.use_ai', { defaultValue: 'Use AI fallback' })}
              <span className="text-content-tertiary">
                {t('compliance.nl.ai_unavailable', {
                  defaultValue: '(skipped if no API key)',
                })}
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                size="md"
                icon={<Sparkles size={16} />}
                loading={generate.isPending}
                disabled={!text.trim()}
                onClick={() => generate.mutate()}
                data-testid="nl-generate"
              >
                {t('compliance.nl.generate', { defaultValue: 'Generate' })}
              </Button>
              <Button
                variant="secondary"
                size="md"
                icon={<Save size={16} />}
                loading={save.isPending}
                disabled={!result?.dsl_yaml || save.isPending}
                onClick={() => save.mutate()}
                data-testid="nl-save"
              >
                {t('compliance.nl.save_as_rule', {
                  defaultValue: 'Save as Compliance Rule',
                })}
              </Button>
            </div>
            {result && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant={methodVariant} size="sm">
                  {methodLabel}
                </Badge>
                {confidencePct !== null && (
                  <Badge variant="neutral" size="sm">
                    {confidencePct}%
                  </Badge>
                )}
                {result.matched_pattern && (
                  <span className="font-mono text-content-tertiary">
                    {result.matched_pattern}
                  </span>
                )}
              </div>
            )}
            {result && result.confidence > 0 && result.confidence < 0.6 && (
              <div className="flex items-start gap-2 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <p>
                  {t('compliance.nl.low_confidence', {
                    defaultValue:
                      'Low confidence — review the generated DSL carefully before saving.',
                  })}
                </p>
              </div>
            )}
            {result && result.errors.length > 0 && (
              <ul className="space-y-1 rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error">
                {result.errors.map((err, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    <span>{err}</span>
                  </li>
                ))}
              </ul>
            )}
            {result && result.suggestions.length > 0 && !result.dsl_yaml && (
              <div className="rounded-lg bg-oe-blue-subtle px-3 py-2 text-xs text-oe-blue">
                <div className="mb-1 flex items-center gap-1.5 font-medium">
                  <Wand2 size={12} />
                  {t('compliance.nl.no_match', {
                    defaultValue:
                      'No pattern matched. Try one of these forms:',
                  })}
                </div>
                <ul className="ml-4 list-disc space-y-0.5">
                  {result.suggestions.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>

        {/* ── DSL pane ───────────────────────────────────────────── */}
        <Card>
          <DslPreview yaml={result?.dsl_yaml ?? null} onCopy={handleCopyYaml} />
        </Card>

        {/* ── Hints sidebar ──────────────────────────────────────── */}
        <NlPatternHints patterns={patterns} onPick={handlePickExample} />
      </div>
    </div>
  );
}
