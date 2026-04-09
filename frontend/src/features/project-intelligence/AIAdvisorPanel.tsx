/**
 * AIAdvisorPanel — AI-powered recommendation panel with chat interface.
 *
 * Two modes:
 * - Recommendations mode: auto-fetches analysis on load
 * - Chat mode: user can ask follow-up questions
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  MessageSquare,
  Send,
  Loader2,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import clsx from 'clsx';

const API_BASE = '/api/v1/project_intelligence';

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

export function AIAdvisorPanel({ projectId, role, }: AIAdvisorPanelProps) {
  const { t } = useTranslation();
  const [recommendation, setRecommendation] = useState<string | null>(null);
  const [loadingRec, setLoadingRec] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const [chatMode, setChatMode] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const headers = {
    Authorization: `Bearer ${localStorage.getItem('oe_token') || ''}`,
    'Content-Type': 'application/json',
  };

  // Fetch recommendations on mount and role change
  const fetchRecommendations = useCallback(async () => {
    setLoadingRec(true);
    setRecError(null);
    try {
      const res = await fetch(
        `${API_BASE}/recommendations/?project_id=${projectId}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({ role, language: 'en' }),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRecommendation(data.text || '');
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
      const res = await fetch(
        `${API_BASE}/chat/?project_id=${projectId}`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({ question, role, language: 'en' }),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', text: data.text || 'No response' },
      ]);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', text: 'Sorry, I could not process your question. Please try again.' },
      ]);
    } finally {
      setChatLoading(false);
    }
  }, [chatInput, chatLoading, projectId, role]);

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
                    'AI recommendations require an LLM provider. Configure one in Settings > AI.',
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
