import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Send, Sparkles, Loader2, Database, MessageSquare } from 'lucide-react';
import { Card, Button, Breadcrumb } from '@/shared/ui';
import { apiPost } from '@/shared/lib/api';
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
  timestamp: number;
}

/* ── Component ──────────────────────────────────────────────────── */

export function AdvisorPage() {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const sendMessage = useCallback(
    async (text?: string) => {
      const msg = (text || input).trim();
      if (!msg || loading) return;

      setInput('');
      setMessages((prev) => [...prev, { role: 'user', content: msg, timestamp: Date.now() }]);
      setLoading(true);

      try {
        const data = await apiPost<AdvisorResponse>('/v1/ai/advisor/chat', {
          message: msg,
          project_id: activeProjectId || undefined,
        });
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.answer,
            sources: data.sources,
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

  const suggestions = [
    t('ai.advisor_q1', { defaultValue: 'What is the average cost of m\u00B2 plaster?' }),
    t('ai.advisor_q2', { defaultValue: 'Compare concrete prices by region' }),
    t('ai.advisor_q3', { defaultValue: 'Suggest cheaper alternatives for steel' }),
    t('ai.advisor_q4', { defaultValue: 'What are typical labor rates for electricians?' }),
  ];

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('nav.ai_advisor', 'AI Cost Advisor') },
        ]}
        className="mb-4"
      />

      <div className="mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 text-white">
            <Sparkles size={18} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-content-primary">
              {t('ai.advisor_title', { defaultValue: 'AI Cost Advisor' })}
            </h1>
            <p className="text-xs text-content-tertiary">
              {t('ai.advisor_desc', {
                defaultValue:
                  'Ask questions about costs, materials, and pricing from your database',
              })}
            </p>
          </div>
        </div>
      </div>

      <div className="flex gap-4" style={{ height: 'calc(100vh - 220px)' }}>
        {/* Chat area */}
        <div className="flex flex-1 flex-col">
          <Card padding="none" className="flex flex-1 flex-col overflow-hidden">
            {/* Messages */}
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              {messages.length === 0 && (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <MessageSquare size={40} className="mb-3 text-content-quaternary" />
                  <p className="mb-4 text-sm text-content-secondary">
                    {t('ai.advisor_empty', {
                      defaultValue: 'Ask me anything about construction costs',
                    })}
                  </p>
                  <div className="grid max-w-md grid-cols-2 gap-2">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => sendMessage(s)}
                        className="rounded-lg border border-border-light px-3 py-2 text-left text-xs text-content-secondary transition-colors hover:border-oe-blue/40 hover:bg-oe-blue-subtle/20"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                      msg.role === 'user'
                        ? 'rounded-br-md bg-oe-blue text-white'
                        : 'rounded-bl-md bg-surface-secondary text-content-primary'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="mt-2 border-t border-border-light/30 pt-2">
                        <p className="mb-1 text-2xs font-medium opacity-70">
                          <Database size={10} className="mr-1 inline" />
                          {t('ai.advisor_sources', { defaultValue: 'Sources:' })}
                        </p>
                        {msg.sources.map((s, j) => (
                          <div key={j} className="text-2xs opacity-80">
                            {s.code}: {s.description.slice(0, 50)}
                            {s.description.length > 50 ? '...' : ''} ({s.rate} /{s.unit})
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-md bg-surface-secondary px-4 py-3">
                    <Loader2 size={16} className="animate-spin text-oe-blue" />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-border-light px-4 py-3">
              <div className="flex items-center gap-2">
                <input
                  ref={inputRef}
                  type="text"
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
                  className="h-10 flex-1 rounded-lg border border-border bg-surface-primary px-3 text-sm placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  disabled={loading}
                />
                <Button
                  variant="primary"
                  size="sm"
                  icon={
                    loading ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Send size={14} />
                    )
                  }
                  onClick={() => sendMessage()}
                  disabled={!input.trim() || loading}
                >
                  {t('common.send', { defaultValue: 'Send' })}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
