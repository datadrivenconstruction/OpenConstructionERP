import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import i18next from 'i18next';
import { Sparkles, Database, ArrowUp, AlertTriangle, Settings, Globe } from 'lucide-react';
import { Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { Link } from 'react-router-dom';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Types ──────────────────────────────────────────────────────── */

interface CostSource {
  code: string;
  description: string;
  rate: number;
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
  const isUser = msg.role === 'user';

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
            {msg.sources.map((s, j) => (
              <p
                key={j}
                className={`text-[11px] leading-tight ${
                  isUser ? 'text-white/60' : 'text-content-quaternary'
                }`}
              >
                {s.code}: {s.description.slice(0, 50)}
                {s.description.length > 50 ? '…' : ''}{' '}
                <span className="font-medium">
                  {s.rate} /{s.unit}
                </span>
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Option buttons — rendered below assistant bubble */}
      {msg.options && msg.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 max-w-[85%] sm:max-w-[75%]">
          {msg.options.map((opt, i) => (
            <button
              key={i}
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

/* ── Main Component ──────────────────────────────────────────────── */

export function AdvisorPage() {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null); // null = loading
  const [aiProvider, setAiProvider] = useState<string>('');
  const [region, setRegion] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);

  // Check if AI is configured on mount
  useEffect(() => {
    apiGet<Record<string, unknown>>('/v1/ai/settings')
      .then((s) => {
        const hasKey =
          !!s.anthropic_api_key_set ||
          !!s.openai_api_key_set ||
          !!s.gemini_api_key_set ||
          !!s.openrouter_api_key_set ||
          !!s.mistral_api_key_set ||
          !!s.groq_api_key_set ||
          !!s.deepseek_api_key_set;
        setAiConfigured(hasKey);
        setAiProvider((s.provider as string) || '');
      })
      .catch(() => setAiConfigured(false));
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
    async (text?: string) => {
      const msg = (text || input).trim();
      if (!msg || loading) return;

      setInput('');
      setMessages((prev) => [...prev, { role: 'user', content: msg, timestamp: Date.now() }]);
      setLoading(true);

      try {
        // Build conversation history for context (last 10 messages)
        const history = messages.slice(-10).map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const data = await apiPost<AdvisorResponse>('/v1/ai/advisor/chat', {
          message: msg,
          project_id: activeProjectId || undefined,
          region: region || undefined,
          locale: i18next.language,
          history,
        });

        // Parse options from the response
        const { cleanText, options } = parseOptions(data.answer);

        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: cleanText,
            sources: data.sources,
            options: options.length > 0 ? options : undefined,
            timestamp: Date.now(),
          },
        ]);
      } catch (err) {
        addToast({
          type: 'error',
          title: t('ai.advisor_error', { defaultValue: 'AI Advisor Error' }),
          message: err instanceof Error ? err.message : '',
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
      } finally {
        setLoading(false);
        inputRef.current?.focus();
      }
    },
    [input, loading, activeProjectId, addToast, t],
  );

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
    <div className="max-w-content mx-auto animate-fade-in flex flex-col" style={{ height: 'calc(100vh - 80px)' }}>
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('nav.ai_advisor', 'AI Cost Advisor') },
        ]}
        className="mb-3 shrink-0"
      />

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
            <h1 className="text-[15px] font-semibold text-content-primary leading-tight">
              {t('ai.advisor_title', { defaultValue: 'AI Cost Advisor' })}
            </h1>
            <p className="text-[11px] text-content-tertiary leading-tight truncate">
              {t('ai.advisor_desc_short', { defaultValue: 'Ask about costs, materials, and pricing from CWICR database + AI' })}
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
              <div className="flex flex-wrap justify-center gap-2 mb-5 max-w-md">
                {[
                  { icon: Database, label: t('ai.advisor_cap_db', { defaultValue: '55K+ cost items (CWICR)' }) },
                  { icon: Globe, label: t('ai.advisor_cap_regions', { defaultValue: '11 regional databases' }) },
                  { icon: Sparkles, label: t('ai.advisor_cap_ai', { defaultValue: 'AI-powered answers' }) },
                ].map((cap, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-surface-secondary px-3 py-1 text-2xs text-content-tertiary">
                    <cap.icon size={11} />
                    {cap.label}
                  </span>
                ))}
              </div>

              {/* Suggestion chips */}
              <div className="flex flex-wrap justify-center gap-2 max-w-lg">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
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
            </div>
          )}

          {/* Message list */}
          {messages.map((msg, i) => (
            <ChatBubble
              key={i}
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
