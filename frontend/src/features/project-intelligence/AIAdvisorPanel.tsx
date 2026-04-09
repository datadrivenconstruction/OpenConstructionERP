/**
 * AIAdvisorPanel — AI-powered recommendation panel with chat interface.
 *
 * Two modes:
 * - Recommendations mode: auto-fetches analysis on load
 * - Chat mode: user can ask follow-up questions
 *
 * Detects when no LLM provider is configured and shows a setup banner
 * linking to Settings > AI Configuration.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { apiPost } from '@/shared/lib/api';
import {
  MessageSquare,
  Send,
  Loader2,
  Sparkles,
  AlertCircle,
  Info,
  Settings,
} from 'lucide-react';
import clsx from 'clsx';

interface AIAdvisorPanelProps {
  projectId: string;
  role: string;
  projectName: string;
  score: {
    overall: number;
    overall_grade: string;
  };
}

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

/** Heuristic: if the recommendation text matches the rule-based fallback pattern,
 *  AI is likely not configured. */
function looksLikeFallback(text: string): boolean {
  return (
    text.includes('Priority actions:') ||
    text.includes('No critical gaps detected') ||
    text.includes('AI recommendations require an LLM provider')
  );
}

export function AIAdvisorPanel({ projectId, role }: AIAdvisorPanelProps) {
  const { t } = useTranslation();
  const [recommendation, setRecommendation] = useState<string | null>(null);
  const [aiConfigured, setAiConfigured] = useState(true);
  const [loadingRec, setLoadingRec] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const [chatMode, setChatMode] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Fetch recommendations on mount and role change
  const fetchRecommendations = useCallback(async () => {
    setLoadingRec(true);
    setRecError(null);
    try {
      const data = await apiPost<{ text: string; role: string; language: string }>(
        `/v1/project_intelligence/recommendations/?project_id=${projectId}`,
        { role, language: 'en' },
      );
      const text = data.text || '';
      setRecommendation(text);
      setAiConfigured(!looksLikeFallback(text));
    } catch (err: any) {
      setRecError(err.message || 'Failed to load recommendations');
    } finally {
      setLoadingRec(false);
    }
  }, [projectId, role]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  // Scroll to bottom when new chat messages appear
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // Send chat message
  const sendMessage = useCallback(async () => {
    const question = chatInput.trim();
    if (!question || chatLoading) return;

    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', text: question }]);
    setChatLoading(true);

    try {
      const data = await apiPost<{ text: string; question: string }>(
        `/v1/project_intelligence/chat/?project_id=${projectId}`,
        { question, role, language: 'en' },
      );
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', text: data.text || 'No response' },
      ]);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: t('project_intelligence.chat_error', {
            defaultValue: 'Sorry, I could not process your question. Please try again.',
          }),
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  }, [chatInput, chatLoading, projectId, role, t]);

  return (
    <div className="bg-surface-secondary rounded-xl border border-border-light overflow-hidden">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-amber-400" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('project_intelligence.ai_advisor', { defaultValue: 'AI Advisor' })}
          </h3>
          <span className="text-2xs text-content-quaternary capitalize">{role}</span>
        </div>
        <div className="flex items-center gap-2">
          {chatMode && (
            <button
              onClick={() => {
                setChatMode(false);
                setChatMessages([]);
              }}
              className="text-2xs text-content-tertiary hover:text-content-secondary transition-colors"
            >
              {t('project_intelligence.back_to_rec', { defaultValue: 'Back to recommendations' })}
            </button>
          )}
          <button
            onClick={() => setChatMode(!chatMode)}
            className={clsx(
              'p-1 rounded transition-colors',
              chatMode
                ? 'text-oe-blue bg-oe-blue/10'
                : 'text-content-tertiary hover:text-content-secondary'
            )}
            title={t('project_intelligence.chat_toggle', { defaultValue: 'Toggle chat' })}
          >
            <MessageSquare size={14} />
          </button>
        </div>
      </div>

      {/* AI not configured banner */}
      {!loadingRec && !aiConfigured && (
        <div className="mx-4 mt-3 flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950/40">
          <Info size={16} className="mt-0.5 shrink-0 text-blue-500" />
          <div className="flex-1 text-xs leading-relaxed text-blue-800 dark:text-blue-300">
            <p className="font-medium">
              {t('project_intelligence.ai_not_configured_title', {
                defaultValue: 'AI provider not connected',
              })}
            </p>
            <p className="mt-1">
              {t('project_intelligence.ai_not_configured_desc', {
                defaultValue:
                  'Connect an AI provider (Anthropic Claude, OpenAI, or Google Gemini) to get personalized, context-aware recommendations for your project. Without AI, you still see rule-based analysis below.',
              })}
            </p>
            <Link
              to="/settings"
              className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-blue-100 px-3 py-1.5 font-medium text-blue-700 transition-colors hover:bg-blue-200 dark:bg-blue-900/60 dark:text-blue-200 dark:hover:bg-blue-900"
            >
              <Settings size={12} />
              {t('project_intelligence.go_to_ai_settings', {
                defaultValue: 'Settings — AI Configuration',
              })}
            </Link>
          </div>
        </div>
      )}

      {/* Content area */}
      <div className="p-4 min-h-[200px] max-h-[400px] overflow-y-auto">
        {!chatMode ? (
          // Recommendations mode
          <div>
            {loadingRec && (
              <div className="flex items-center gap-2 text-sm text-content-tertiary animate-pulse">
                <Loader2 size={14} className="animate-spin" />
                {t('project_intelligence.analyzing_project', {
                  defaultValue: 'Analyzing project...',
                })}
              </div>
            )}
            {recError && (
              <div className="flex items-center gap-2 text-sm text-red-400">
                <AlertCircle size={14} />
                <span>{recError}</span>
                <button
                  onClick={fetchRecommendations}
                  className="ml-2 text-xs text-oe-blue hover:underline"
                >
                  {t('common.retry', { defaultValue: 'Retry' })}
                </button>
              </div>
            )}
            {!loadingRec && !recError && recommendation && (
              <div
                className="text-sm text-content-secondary leading-relaxed whitespace-pre-wrap"
                aria-live="polite"
              >
                {recommendation}
              </div>
            )}
            {!loadingRec && !recError && !recommendation && (
              <p className="text-sm text-content-tertiary">
                {t('project_intelligence.no_recommendations', {
                  defaultValue:
                    'No recommendations available yet. Try refreshing the analysis.',
                })}
              </p>
            )}
          </div>
        ) : (
          // Chat mode
          <div className="space-y-3">
            {chatMessages.length === 0 && (
              <p className="text-xs text-content-tertiary text-center py-4">
                {t('project_intelligence.chat_prompt', {
                  defaultValue:
                    'Ask any question about this project. For example: "Why is my score so low?" or "What should I do first?"',
                })}
              </p>
            )}
            {chatMessages.map((msg, i) => (
              <div
                key={i}
                className={clsx(
                  'rounded-lg px-3 py-2 text-xs',
                  msg.role === 'user'
                    ? 'bg-oe-blue/10 text-oe-blue ml-8'
                    : 'bg-surface-tertiary text-content-secondary mr-8'
                )}
              >
                <p className="whitespace-pre-wrap">{msg.text}</p>
              </div>
            ))}
            {chatLoading && (
              <div className="flex items-center gap-2 text-xs text-content-tertiary mr-8 bg-surface-tertiary rounded-lg px-3 py-2">
                <Loader2 size={12} className="animate-spin" />
                {t('project_intelligence.thinking', { defaultValue: 'Thinking...' })}
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        )}
      </div>

      {/* Chat input */}
      {chatMode && (
        <div className="px-4 pb-4 pt-2 border-t border-border-light">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
            }}
            className="flex items-center gap-2"
          >
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={t('project_intelligence.ask_placeholder', {
                defaultValue: 'Ask about this project...',
              })}
              className="flex-1 text-xs bg-surface-tertiary border border-border-light rounded-md px-3 py-2 text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              disabled={chatLoading}
            />
            <button
              type="submit"
              disabled={chatLoading || !chatInput.trim()}
              className="p-2 text-white bg-oe-blue rounded-md hover:bg-oe-blue-dark transition-colors disabled:opacity-50"
              aria-label={t('common.send', { defaultValue: 'Send' })}
            >
              <Send size={14} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
