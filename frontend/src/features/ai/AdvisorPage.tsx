import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import i18next from 'i18next';
import {
  Sparkles,
  Database,
  ArrowUp,
  AlertTriangle,
  Settings,
  Globe,
  Search,
  Calculator,
  MessageSquarePlus,
  Info,
  Bot,
  ArrowUpRight,
} from 'lucide-react';
import { Breadcrumb, AIDisclaimerBanner, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useLLMRun } from './hooks/useLLMRun';

/* ── Types ──────────────────────────────────────────────────────── */

interface CostSource {
  code: string;
  description: string;
  rate: number;
  /** ISO currency of the source rate. May be empty for legacy rows. */
  currency?: string;
  unit: string;
  region: string;
}

interface AdvisorResponse {
  answer: string;
  sources: CostSource[];
  query: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: CostSource[];
  options?: string[];
  /** The user question this assistant message answered (for "Use in Quick
   *  Estimate" - CONN-81). Only set on assistant messages. */
  query?: string;
  timestamp: number;
}

/* ── Helpers ─────────────────────────────────────────────────────── */

/** Extract numbered options from AI text and return clean text + options array */
function parseOptions(text: string): { cleanText: string; options: string[] } {
  const lines = text.split('\n');
  const options: string[] = [];
  const textLines: string[] = [];
  let inOptions = false;

  for (const line of lines) {
    const trimmed = line.trim();
    // Match patterns: "1. Text", "1) Text", "- **Text**"
    const numMatch = trimmed.match(/^(\d+)[.)]\s+(.+)/);
    if (numMatch) {
      inOptions = true;
      // Strip markdown bold
      options.push(numMatch[2]!.replace(/\*\*/g, '').trim());
    } else if (inOptions && trimmed === '') {
      // Blank line after options = end of options block
      inOptions = false;
    } else {
      textLines.push(line);
    }
  }

  return {
    cleanText: textLines
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim(),
    options,
  };
}

/** Format time as HH:MM */
function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Simple markdown-to-JSX: bold, italic, line breaks */
function renderMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    // Split by newlines for line breaks
    return part.split('\n').map((line, j, arr) => (
      <span key={`${i}-${j}`}>
        {line}
        {j < arr.length - 1 && <br />}
      </span>
    ));
  });
}

/* ── Provider detection ──────────────────────────────────────────── */

/**
 * Provider catalogue used for "is AI configured" + active-provider detection.
 * `key` is the settings flag prefix (`<key>_api_key_set`); `match` are tokens
 * looked for in `preferred_model` to map a model preference back to a provider.
 */
const PROVIDER_DISPLAY: ReadonlyArray<{ key: string; label: string; match: string[] }> = [
  { key: 'anthropic', label: 'Anthropic Claude', match: ['claude', 'anthropic'] },
  { key: 'openai', label: 'OpenAI', match: ['gpt', 'openai'] },
  { key: 'gemini', label: 'Google Gemini', match: ['gemini', 'google'] },
  { key: 'openrouter', label: 'OpenRouter', match: ['openrouter', 'router'] },
  { key: 'mistral', label: 'Mistral AI', match: ['mistral'] },
  { key: 'groq', label: 'Groq', match: ['groq', 'llama'] },
  { key: 'deepseek', label: 'DeepSeek', match: ['deepseek'] },
  { key: 'together', label: 'Together AI', match: ['together'] },
  { key: 'fireworks', label: 'Fireworks AI', match: ['fireworks'] },
  { key: 'perplexity', label: 'Perplexity', match: ['perplexity', 'sonar'] },
  { key: 'cohere', label: 'Cohere', match: ['cohere', 'command'] },
  { key: 'ai21', label: 'AI21 Labs', match: ['ai21', 'jamba'] },
  { key: 'xai', label: 'xAI Grok', match: ['xai', 'grok'] },
  { key: 'zhipu', label: 'Zhipu AI', match: ['zhipu', 'glm'] },
  { key: 'baidu', label: 'Baidu ERNIE', match: ['baidu', 'ernie'] },
  { key: 'yandex', label: 'Yandex GPT', match: ['yandex'] },
  { key: 'gigachat', label: 'GigaChat', match: ['gigachat'] },
  { key: 'kimi', label: 'Kimi', match: ['kimi', 'moonshot'] },
  { key: 'ollama', label: 'Ollama', match: ['ollama'] },
  { key: 'vllm', label: 'vLLM', match: ['vllm'] },
];

/**
 * Derive the active-provider display name shown in the status pill.
 *
 * The settings API has no `provider` field; the active provider is implied by
 * `preferred_model` (mapped via PROVIDER_DISPLAY.match) and, failing that, the
 * first provider whose key is configured.
 */
function resolveActiveProvider(
  s: Record<string, unknown>,
  configured: ReadonlyArray<{ key: string; label: string }>,
): string {
  const preferred = String(s.preferred_model || '').toLowerCase();
  if (preferred) {
    const byModel = PROVIDER_DISPLAY.find((p) => p.match.some((m) => preferred.includes(m)));
    // Only trust the model->provider mapping when that provider actually has a
    // configured key; otherwise fall through to the first configured one.
    if (byModel && configured.some((c) => c.key === byModel.key)) {
      return byModel.label;
    }
  }
  return configured.length > 0 ? configured[0]!.label : '';
}

/* ── Typing Indicator (3 dots) ───────────────────────────────────── */

function TypingDots() {
  return (
    <div className="flex items-center gap-[5px] px-4 py-3">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block h-[7px] w-[7px] rounded-full bg-content-tertiary/60"
          style={{
            animation: 'oeTypingDot 1.4s ease-in-out infinite',
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </div>
  );
}

/* ── Chat Bubble ─────────────────────────────────────────────────── */

function ChatBubble({
  msg,
  onOptionClick,
  isLast,
}: {
  msg: ChatMessage;
  onOptionClick: (text: string) => void;
  isLast: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isUser = msg.role === 'user';

  // Source code -> Cost Database deep link (CONN-81). The advisor's sources
  // carry the CWICR `code` + raw `region` token (e.g. DE_BERLIN), which is the
  // exact shape the /costs page consumes. ?region= is honoured today; the ?q=
  // (code) consumer on CostsPage lands with its own batch.
  const sourceTo = (s: CostSource): string => {
    const params = new URLSearchParams();
    if (s.code) params.set('q', s.code);
    if (s.region) params.set('region', s.region);
    const qs = params.toString();
    return qs ? `/costs?${qs}` : '/costs';
  };

  return (
    <div
      className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} animate-msg-in`}
      style={{ animationDelay: isLast ? '0ms' : '0ms' }}
    >
      {/* Bubble */}
      <div
        className={`relative max-w-[85%] sm:max-w-[75%] px-[14px] py-[9px] text-[15px] leading-[1.38] ${
          isUser
            ? 'bg-oe-blue text-white rounded-[20px] rounded-br-[6px]'
            : 'bg-surface-secondary text-content-primary rounded-[20px] rounded-bl-[6px]'
        }`}
      >
        <div className="whitespace-pre-wrap break-words">
          {renderMarkdown(msg.content)}
        </div>

        {/* Sources */}
        {msg.sources && msg.sources.length > 0 && (
          <div
            className={`mt-2 pt-2 border-t ${
              isUser ? 'border-white/20' : 'border-border-light'
            }`}
          >
            <p
              className={`flex items-center gap-1 text-[11px] font-medium mb-1 ${
                isUser ? 'text-white/70' : 'text-content-tertiary'
              }`}
            >
              <Database size={10} />
              {t('ai.advisor_sources', { defaultValue: 'Sources:' })}
            </p>
            {msg.sources.map((s, j) => {
              const rateLabel = s.currency
                ? t('ai.advisor_source_rate', {
                    defaultValue: '{{rate}} {{currency}}/{{unit}}',
                    rate: s.rate,
                    currency: s.currency,
                    unit: s.unit,
                  })
                : t('ai.advisor_source_rate_nocur', {
                    defaultValue: '{{rate}}/{{unit}}',
                    rate: s.rate,
                    unit: s.unit,
                  });
              const body = (
                <>
                  {s.code}: {s.description.slice(0, 50)}
                  {s.description.length > 50 ? '…' : ''}{' '}
                  <span className="font-medium">{rateLabel}</span>
                </>
              );
              // On the user bubble (rare) keep plain text; on the assistant
              // bubble make the source a deep link into the Cost Database.
              if (isUser) {
                return (
                  <p key={j} className="text-[11px] leading-tight text-white/60">
                    {body}
                  </p>
                );
              }
              return (
                <button
                  key={j}
                  type="button"
                  onClick={() => navigate(sourceTo(s))}
                  title={t('ai.advisor_source_open', {
                    defaultValue: 'Open {{code}} in the Cost Database',
                    code: s.code,
                  })}
                  className="block w-full text-left text-[11px] leading-tight text-content-quaternary
                    rounded px-1 -mx-1 hover:bg-oe-blue/[0.06] hover:text-oe-blue transition-colors"
                >
                  {body}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Option buttons — rendered below assistant bubble */}
      {msg.options && msg.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 max-w-[85%] sm:max-w-[75%]">
          {msg.options.map((opt, i) => (
            <button
              key={opt}
              onClick={() => onOptionClick(opt)}
              className="inline-flex items-center gap-1.5 rounded-full border border-oe-blue/30
                bg-oe-blue/[0.06] px-3.5 py-[7px] text-[13px] font-medium text-oe-blue
                transition-all duration-150 ease-out
                hover:bg-oe-blue hover:text-white hover:border-oe-blue hover:shadow-sm
                active:scale-[0.97]"
            >
              <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-oe-blue/10 text-[11px] font-semibold">
                {i + 1}
              </span>
              {opt}
            </button>
          ))}
        </div>
      )}

      {/* Turn this answer into an estimate (CONN-81). Carries the answered
          question to the Quick Estimate text tab. ?tab=text is honoured today;
          the ?q= prefill consumer on QuickEstimatePage lands with its own
          batch. */}
      {!isUser && msg.query && (
        <div className="mt-2 max-w-[85%] sm:max-w-[75%]">
          <button
            type="button"
            onClick={() =>
              navigate(`/ai-estimate?tab=text&q=${encodeURIComponent(msg.query!)}`)
            }
            className="inline-flex items-center gap-1.5 rounded-full border border-border-light
              bg-surface-elevated px-3 py-[6px] text-[12px] font-medium text-content-secondary
              transition-colors hover:border-oe-blue/40 hover:bg-oe-blue/[0.06] hover:text-oe-blue"
          >
            <Calculator size={13} />
            {t('ai.advisor_use_in_estimate', { defaultValue: 'Use in Quick Estimate' })}
          </button>
        </div>
      )}

      {/* Timestamp */}
      <p
        className={`mt-[3px] text-[11px] ${
          isUser ? 'text-content-quaternary/50 mr-1' : 'text-content-quaternary/50 ml-1'
        }`}
      >
        {formatTime(msg.timestamp)}
      </p>
    </div>
  );
}

/* ── AI tools cross-link strip (CONN-82) ─────────────────────────── */

/**
 * The AI surfaces (Agents, Chat, Quick Estimate) are siblings the Advisor
 * never pointed at. This compact strip links to the others (the Advisor itself
 * is dropped) so the empty state reads as one connected toolset. Defined
 * locally to keep the Advisor's lazy chunk free of the heavier AgentsPage
 * module. Plain react-router Links only.
 */
function AiToolsStrip() {
  const { t } = useTranslation();
  const tools = [
    { to: '/ai-agents', icon: Bot, label: t('nav.ai_agents', { defaultValue: 'AI Agents' }) },
    { to: '/chat', icon: Sparkles, label: t('nav.erp_chat', { defaultValue: 'AI Chat' }) },
    {
      to: '/ai-estimate',
      icon: Calculator,
      label: t('nav.ai_estimate', { defaultValue: 'AI Quick Estimate' }),
    },
  ];
  return (
    <section aria-label={t('ai.cross_strip_label', { defaultValue: 'Other AI tools' })}>
      <p className="flex items-center gap-1.5 text-2xs font-semibold text-content-tertiary uppercase tracking-wide mb-2">
        <Sparkles size={11} />
        {t('ai.cross_strip_title', { defaultValue: 'Other AI tools' })}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {tools.map((tool) => {
          const Icon = tool.icon;
          return (
            <Link
              key={tool.to}
              to={tool.to}
              className="group flex items-center gap-2 rounded-lg bg-surface-primary border border-border-light px-3 py-2 text-xs text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
            >
              <Icon size={14} className="shrink-0 text-oe-blue/70" />
              <span className="flex-1 truncate font-medium">{tool.label}</span>
              <ArrowUpRight size={13} className="shrink-0 text-content-tertiary group-hover:text-oe-blue" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

/* ── Main Component ──────────────────────────────────────────────── */

// Region tokens the selector below offers; a ?region deep-link is only honoured
// when it matches one of these so the <select> always renders a real option.
const ADVISOR_REGION_OPTIONS = new Set([
  'DE_BERLIN',
  'UK_LONDON',
  'USA_USD',
  'CA_TORONTO',
  'FR_PARIS',
  'ES_BARCELONA',
  'AE_DUBAI',
  'SA_RIYADH',
]);

export function AdvisorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // Deep-link prefill (e.g. "Benchmark this rate" from the Cost Database,
  // CONN-81): ?q seeds the question, ?region pre-selects the region. We never
  // auto-send - the user reviews and submits. Read once for the initial state.
  const questionFromUrl = searchParams.get('q') ?? '';
  const regionFromUrl = searchParams.get('region') ?? '';
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(questionFromUrl);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null); // null = loading
  const [aiProvider, setAiProvider] = useState<string>('');
  const [region, setRegion] = useState(
    regionFromUrl && ADVISOR_REGION_OPTIONS.has(regionFromUrl) ? regionFromUrl : '',
  );
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const addToast = useToastStore((s) => s.addToast);

  // ── Advisor chat run — backed by useLLMRun for AbortController-aware
  //    cancellation (unmount during a long LLM round-trip no longer
  //    delivers a phantom assistant bubble) and normalised Error so the
  //    toast `.message` access is always safe.
  //
  //    `mutationFn` re-builds the request payload on every invocation
  //    so it always sees the freshest closure values for `messages`,
  //    `region`, and `activeProjectId` — react-query reads the latest
  //    `mutationFn` from each render, so this stays in lock-step with
  //    UI state without needing manual queryKeys.
  const advisorRun = useLLMRun<{ msg: string }, AdvisorResponse>({
    mutationFn: ({ msg }, { signal }) => {
      // Build conversation history for context (last 10 messages).
      // Captured here so the latest message list is always sent, even
      // when the user fires multiple requests in quick succession.
      const history = messages.slice(-10).map((m) => ({
        role: m.role,
        content: m.content,
      }));
      return apiPost<AdvisorResponse>(
        '/v1/ai/advisor/chat/',
        {
          message: msg,
          project_id: activeProjectId || undefined,
          region: region || undefined,
          locale: i18next.language,
          history,
        },
        { signal },
      );
    },
    onSuccess: (data) => {
      const { cleanText, options } = parseOptions(data.answer);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: cleanText,
          sources: data.sources,
          options: options.length > 0 ? options : undefined,
          query: data.query,
          timestamp: Date.now(),
        },
      ]);
      inputRef.current?.focus();
    },
    onError: (err) => {
      // A cancelled in-flight request (user navigated away or fired a new
      // send) surfaces as a DOMException with name 'AbortError'. That is not
      // a failure — don't show a phantom error bubble or toast for it.
      if (err.name === 'AbortError') return;
      addToast({
        type: 'error',
        title: t('ai.advisor_error', { defaultValue: 'AI Advisor Error' }),
        message: err.message,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: t('ai.advisor_unavailable', {
            defaultValue: 'Unable to get a response. Please check AI settings.',
          }),
          timestamp: Date.now(),
        },
      ]);
      inputRef.current?.focus();
    },
  });
  // Keep the existing `loading` identifier so the rest of the JSX (typing
  // dots, send-button disabled, textarea disabled, `canSend`) stays
  // bit-identical — only the source of truth changed.
  const loading = advisorRun.isPending;

  // Check if AI is configured on mount
  useEffect(() => {
    apiGet<Record<string, unknown>>('/v1/ai/settings/')
      .then((s) => {
        // Every provider whose key is set (and decryptable) reports a
        // `<provider>_api_key_set` boolean. Treat the AI as configured when
        // ANY of them is true — the previous list omitted half the providers
        // (together/fireworks/perplexity/cohere/ai21/xai/kimi/zhipu/...),
        // making those users see a false "not configured" warning.
        const flag = (key: string) => !!s[`${key}_api_key_set`];
        const configured = PROVIDER_DISPLAY.filter((p) => flag(p.key));
        setAiConfigured(configured.length > 0);
        // Derive the active provider from the preferred model first, falling
        // back to the first configured key. AISettingsResponse has no
        // `provider` field, so reading it always yielded '' (pill said "AI").
        setAiProvider(resolveActiveProvider(s, configured));
      })
      .catch(() => setAiConfigured(false));
  }, []);

  // The ?q / ?region seeds have been copied into state above; strip them so a
  // reload does not re-pin the prefill over the user's edits.
  useEffect(() => {
    if (!questionFromUrl && !regionFromUrl) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('q');
        next.delete('region');
        return next;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 50);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  const sendMessage = useCallback(
    (text?: string) => {
      const msg = (text || input).trim();
      if (!msg || loading) return;

      setInput('');
      setMessages((prev) => [...prev, { role: 'user', content: msg, timestamp: Date.now() }]);
      // The hook owns the in-flight controller, success/error toasts and
      // assistant-bubble append — see `advisorRun` above. `messages`,
      // `region` and `activeProjectId` are read inside the hook's
      // `mutationFn` closure on every invocation, so no extra deps here.
      advisorRun.run({ msg });
    },
    [input, loading, advisorRun],
  );

  const clearConversation = useCallback(() => {
    setMessages([]);
    setInput('');
    inputRef.current?.focus();
  }, []);

  const suggestions = useMemo(
    () => [
      t('ai.advisor_q1', { defaultValue: 'What is the average cost per m² of plaster?' }),
      t('ai.advisor_q2', { defaultValue: 'Compare concrete prices by region' }),
      t('ai.advisor_q3', { defaultValue: 'Suggest cheaper alternatives for steel' }),
      t('ai.advisor_q4', { defaultValue: 'What are typical labor rates for electricians?' }),
    ],
    [t],
  );

  const canSend = input.trim().length > 0 && !loading;

  return (
    <div className="w-full animate-fade-in flex flex-col" style={{ height: 'calc(100vh - 80px)' }}>
      <Breadcrumb
        items={[{ label: t('nav.ai_advisor', 'AI Cost Advisor') }]}
        className="mb-3 shrink-0"
      />

      {/* Canonical top block - the module name + icon are shown by the global
          top app bar. This chat page manages its own header bar below, so we
          emit only the sr-only h1 here (a full PageHeader row would reserve an
          empty min-h-9 midline above the chat with no subtitle or actions). */}
      <h1 className="sr-only">{t('nav.ai_advisor', 'AI Cost Advisor')}</h1>

      <AIDisclaimerBanner variant="compact" className="mb-3 shrink-0" />

      <DismissibleInfo
        storageKey="advisor"
        className="mb-3 shrink-0"
        title={t('advisor.intro_title', {
          defaultValue: 'Ask the price book a plain question',
        })}
        more={t('advisor.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('advisor.intro_more')} /> : undefined}
        links={[
          { label: t('advisor.intro_link_costs', { defaultValue: 'Cost database' }), onClick: () => navigate('/costs') },
          { label: t('advisor.intro_link_estimate', { defaultValue: 'Quick Estimate' }), onClick: () => navigate('/ai-estimate') },
        ]}
      >
        {t('advisor.intro_body', {
          defaultValue:
            'Ask in plain language what something should cost and the advisor answers from your installed regional cost databases, showing the source rates, units and regions behind each reply. Use it to sanity-check a number before you commit it to an estimate.',
        })}
      </DismissibleInfo>

      {/* AI not configured warning */}
      {aiConfigured === false && (
        <div className="mb-3 shrink-0 flex items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-4 py-3">
          <AlertTriangle size={18} className="text-amber-600 dark:text-amber-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
              {t('ai.not_configured_title', { defaultValue: 'AI is not configured' })}
            </p>
            <p className="text-xs text-amber-700 dark:text-amber-400/80">
              {t('ai.not_configured_desc', { defaultValue: 'Add your API key (Anthropic, OpenAI, or other) to use the AI Cost Advisor.' })}
            </p>
          </div>
          <Link
            to="/settings"
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 transition-colors shrink-0"
          >
            <Settings size={13} />
            {t('ai.go_to_settings', { defaultValue: 'Configure AI' })}
          </Link>
        </div>
      )}

      {/* Chat container — full height */}
      <div className="flex flex-1 flex-col min-h-0 rounded-2xl border border-border-light bg-surface-primary overflow-hidden shadow-sm">
        {/* Header bar */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-border-light bg-surface-elevated/50 backdrop-blur-sm shrink-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-blue-500 text-white shadow-sm">
            <Sparkles size={14} />
          </div>
          <div className="min-w-0 flex-1">
            {/* No visible module-name heading here — the top app bar already
                shows the module name + icon. We keep the assistant avatar and
                the contextual scope line, which carry real information. */}
            <p className="text-[13px] font-medium text-content-primary leading-tight truncate">
              {activeProjectId && activeProjectName
                ? t('ai.advisor_scoped', {
                    defaultValue: 'Using {{project}} region & currency as default context',
                    project: activeProjectName,
                  })
                : t('ai.advisor_desc_short', {
                    defaultValue: 'Ask about costs, materials, and pricing from CWICR database + AI',
                  })}
            </p>
          </div>

          {/* Region selector */}
          <div className="flex items-center gap-2 shrink-0">
            <Globe size={13} className="text-content-tertiary" />
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="h-7 rounded-lg border border-border bg-surface-primary px-2 text-2xs text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
            >
              <option value="">{t('ai.all_regions', { defaultValue: 'All regions' })}</option>
              <option value="DE_BERLIN">Germany (Berlin)</option>
              <option value="UK_LONDON">UK (London)</option>
              <option value="USA_USD">USA (USD)</option>
              <option value="CA_TORONTO">Canada (Toronto)</option>
              <option value="FR_PARIS">France (Paris)</option>
              <option value="ES_BARCELONA">Spain (Barcelona)</option>
              <option value="AE_DUBAI">UAE (Dubai)</option>
              <option value="SA_RIYADH">Saudi Arabia</option>
            </select>
          </div>

          {messages.length > 0 && (
            <button
              onClick={clearConversation}
              className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-2xs font-medium text-content-secondary hover:text-content-primary hover:border-border transition-colors shrink-0"
              title={t('ai.advisor_new_chat', { defaultValue: 'Start a new conversation' })}
            >
              <MessageSquarePlus size={13} />
              {t('ai.advisor_new_chat', { defaultValue: 'New chat' })}
            </button>
          )}

          {aiConfigured && (
            <span className="flex items-center gap-1.5 text-2xs text-semantic-success font-medium shrink-0">
              <span className="h-1.5 w-1.5 rounded-full bg-semantic-success animate-pulse" />
              {aiProvider || 'AI'}
            </span>
          )}
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {/* Empty state */}
          {messages.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-violet-500/10 to-blue-500/10 mb-4">
                <Sparkles size={28} className="text-oe-blue/60" />
              </div>
              <p className="text-base font-medium text-content-primary mb-1">
                {t('ai.advisor_empty', { defaultValue: 'Ask me anything about construction costs' })}
              </p>
              <p className="text-xs text-content-tertiary max-w-md mb-4 leading-relaxed">
                {t('ai.advisor_purpose', {
                  defaultValue:
                    'Use this as a research companion while estimating: ask about typical rates, material alternatives, regional price differences or methods. Answers draw on the CWICR cost database plus AI knowledge - they inform decisions, they do not replace a priced BOQ.',
                })}
              </p>
              <div className="flex flex-wrap justify-center gap-2 mb-4 max-w-md">
                {[
                  { icon: Database, label: t('ai.advisor_cap_db', { defaultValue: '55K+ cost items (CWICR)' }) },
                  { icon: Globe, label: t('ai.advisor_cap_regions', { defaultValue: 'Regional cost databases' }) },
                  { icon: Sparkles, label: t('ai.advisor_cap_ai', { defaultValue: 'AI-powered answers' }) },
                ].map((cap, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-surface-secondary px-3 py-1 text-2xs text-content-tertiary">
                    <cap.icon size={11} />
                    {cap.label}
                  </span>
                ))}
              </div>

              {/* Suggestion chips */}
              <div className="flex flex-wrap justify-center gap-2 max-w-lg mb-6">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    className="rounded-full border border-border-light bg-surface-elevated px-4 py-2 text-[13px] text-content-secondary
                      transition-all duration-150
                      hover:border-oe-blue/40 hover:bg-oe-blue/[0.06] hover:text-oe-blue
                      active:scale-[0.97]"
                  >
                    {s}
                  </button>
                ))}
              </div>

              {/* Cross-module: where to go next */}
              <div className="w-full max-w-lg rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-3 text-left">
                <p className="flex items-center gap-1.5 text-2xs font-semibold text-content-tertiary uppercase tracking-wide mb-2">
                  <Info size={11} />
                  {t('ai.advisor_next_steps', { defaultValue: 'Turn answers into an estimate' })}
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <Link
                    to="/costs"
                    className="flex items-center gap-2 rounded-lg bg-surface-primary border border-border-light px-3 py-2 text-xs text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
                  >
                    <Search size={14} className="shrink-0 text-oe-blue/70" />
                    <span>
                      {t('ai.advisor_link_costs', {
                        defaultValue: 'Browse the full CWICR cost database',
                      })}
                    </span>
                  </Link>
                  <Link
                    to="/ai-estimate"
                    className="flex items-center gap-2 rounded-lg bg-surface-primary border border-border-light px-3 py-2 text-xs text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
                  >
                    <Calculator size={14} className="shrink-0 text-oe-blue/70" />
                    <span>
                      {t('ai.advisor_link_estimate', {
                        defaultValue: 'Generate a full BOQ with AI Estimate',
                      })}
                    </span>
                  </Link>
                </div>
              </div>

              {/* AI tools cross-link strip (CONN-82) - reach the sibling AI
                  surfaces (Agents, Chat, Quick Estimate) in one click. */}
              <div className="w-full max-w-lg mt-4 text-left">
                <AiToolsStrip />
              </div>
            </div>
          )}

          {/* Message list */}
          {messages.map((msg, i) => (
            <ChatBubble
              key={`${msg.role}-${i}`}
              msg={msg}
              onOptionClick={sendMessage}
              isLast={i === messages.length - 1}
            />
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex items-start animate-msg-in">
              <div className="rounded-[20px] rounded-bl-[6px] bg-surface-secondary">
                <TypingDots />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input bar — iMessage style */}
        <div className="shrink-0 border-t border-border-light bg-surface-elevated/50 backdrop-blur-sm px-3 py-2">
          <div className="flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                placeholder={t('ai.advisor_placeholder', {
                  defaultValue: 'Ask about costs, materials, pricing...',
                })}
                rows={1}
                className="w-full resize-none rounded-[22px] border border-border bg-surface-primary
                  px-4 py-[10px] pr-10 text-[15px] leading-[1.35]
                  placeholder:text-content-tertiary/60
                  focus:outline-none focus:ring-2 focus:ring-oe-blue/20 focus:border-oe-blue/40
                  transition-all duration-150"
                disabled={loading}
                style={{ maxHeight: '120px' }}
              />
            </div>

            {/* Send button — circular, like iMessage */}
            <button
              onClick={() => sendMessage()}
              disabled={!canSend}
              className={`flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full
                transition-all duration-200 ease-out mb-[1px]
                ${
                  canSend
                    ? 'bg-oe-blue text-white shadow-sm hover:bg-oe-blue-hover active:scale-[0.93]'
                    : 'bg-content-quaternary/20 text-content-quaternary cursor-not-allowed'
                }`}
              aria-label={t('common.send', { defaultValue: 'Send' })}
            >
              <ArrowUp size={18} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
