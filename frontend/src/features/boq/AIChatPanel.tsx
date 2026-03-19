import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { X, Send, Check, Settings, AlertCircle, Sparkles } from 'lucide-react';
import { Button } from '@/shared/ui';
import {
  boqApi,
  type AIChatItem,
  type AIChatResponse,
  type AIChatContext,
  type CreatePositionData,
} from './api';
import { ApiError } from '@/shared/lib/api';

/* ── Types ──────────────────────────────────────────────────────────── */

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  text: string;
  items?: AIChatItem[];
}

interface AIChatPanelProps {
  boqId: string;
  context: AIChatContext;
  isOpen: boolean;
  onClose: () => void;
  onAddPositions: (items: CreatePositionData[]) => void;
}

/* ── Component ──────────────────────────────────────────────────────── */

export function AIChatPanel({
  boqId,
  context,
  isOpen,
  onClose,
  onAddPositions,
}: AIChatPanelProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 200);
    }
  }, [isOpen]);

  // AI chat mutation
  const chatMutation = useMutation({
    mutationFn: (message: string) =>
      boqApi.aiChat(boqId, { message, context }),
    onSuccess: (response: AIChatResponse, _message: string) => {
      // Remove the loading indicator
      setMessages((prev) => prev.filter((m) => m.id !== 'loading'));

      // Add assistant response
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: response.message,
        items: response.items.length > 0 ? response.items : undefined,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Select all items by default
      if (response.items.length > 0) {
        const allKeys = new Set(
          response.items.map((_, idx) => `${assistantMsg.id}-${idx}`),
        );
        setSelectedItems((prev) => new Set([...prev, ...allKeys]));
      }
    },
    onError: (error: unknown) => {
      // Remove the loading indicator
      setMessages((prev) => prev.filter((m) => m.id !== 'loading'));

      let errorText = t('boq.ai_chat_error', {
        defaultValue: 'AI request failed. Please try again.',
      });

      if (error instanceof ApiError) {
        const body = error.body as { detail?: string } | undefined;
        if (body?.detail) {
          errorText = body.detail;
        }
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'error',
          text: errorText,
        },
      ]);
    },
  });

  const handleSend = useCallback(() => {
    const trimmed = inputValue.trim();
    if (!trimmed || chatMutation.isPending) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: trimmed,
    };
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: 'loading', role: 'assistant', text: '' },
    ]);
    setInputValue('');

    // Send to AI
    chatMutation.mutate(trimmed);
  }, [inputValue, chatMutation]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const toggleItem = useCallback((key: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const handleAddItems = useCallback(
    (msgId: string, items: AIChatItem[], addAll: boolean) => {
      const positionsToAdd: CreatePositionData[] = [];

      items.forEach((item, idx) => {
        const key = `${msgId}-${idx}`;
        if (addAll || selectedItems.has(key)) {
          positionsToAdd.push({
            boq_id: boqId,
            ordinal: item.ordinal || String(idx + 1),
            description: item.description,
            unit: item.unit,
            quantity: item.quantity,
            unit_rate: item.unit_rate,
          });
        }
      });

      if (positionsToAdd.length > 0) {
        onAddPositions(positionsToAdd);
      }
    },
    [boqId, selectedItems, onAddPositions],
  );

  /** Format a number for display. */
  const fmtNum = (n: number) =>
    new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  const isNoApiKey = messages.some(
    (m) => m.role === 'error' && m.text.includes('No AI API key configured'),
  );

  return (
    <div
      className={`fixed right-0 top-0 z-50 h-full w-[360px] bg-surface-elevated border-l border-border-light shadow-xl flex flex-col transition-transform duration-300 ease-in-out ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-oe-blue" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('boq.ai_assistant', { defaultValue: 'AI Assistant' })}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      {/* ── Messages ──────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Welcome message if empty */}
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue-subtle/40">
              <Sparkles size={22} className="text-oe-blue" />
            </div>
            <p className="text-sm text-content-secondary max-w-[260px]">
              {t('boq.ai_welcome', {
                defaultValue:
                  'Ask me to generate BOQ positions. For example: "Add MEP items for a 5-story office building"',
              })}
            </p>
          </div>
        )}

        {messages.map((msg) => {
          // Loading indicator
          if (msg.id === 'loading') {
            return (
              <div key="loading" className="flex items-start gap-2">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle/40">
                  <Sparkles size={12} className="text-oe-blue" />
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            );
          }

          // Error message
          if (msg.role === 'error') {
            return (
              <div key={msg.id} className="flex items-start gap-2">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-semantic-error-bg">
                  <AlertCircle size={12} className="text-semantic-error" />
                </div>
                <div className="flex-1 rounded-lg bg-semantic-error-bg px-3 py-2">
                  <p className="text-xs text-semantic-error">{msg.text}</p>
                  {isNoApiKey && (
                    <a
                      href="/settings"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
                    >
                      <Settings size={11} />
                      {t('boq.go_to_settings', { defaultValue: 'Go to Settings' })}
                    </a>
                  )}
                </div>
              </div>
            );
          }

          // User message
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-lg bg-oe-blue px-3 py-2">
                  <p className="text-xs text-white whitespace-pre-wrap">{msg.text}</p>
                </div>
              </div>
            );
          }

          // Assistant message
          return (
            <div key={msg.id} className="flex items-start gap-2">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle/40 mt-0.5">
                <Sparkles size={12} className="text-oe-blue" />
              </div>
              <div className="flex-1 min-w-0">
                {/* Summary text */}
                {msg.text && (
                  <p className="text-xs text-content-secondary mb-2">{msg.text}</p>
                )}

                {/* Generated items table */}
                {msg.items && msg.items.length > 0 && (
                  <div className="rounded-lg border border-border-light overflow-hidden bg-surface-primary">
                    <table className="w-full text-2xs">
                      <thead>
                        <tr className="border-b border-border-light bg-surface-secondary">
                          <th className="w-7 px-1.5 py-1.5" />
                          <th className="px-2 py-1.5 text-left font-medium text-content-tertiary">
                            {t('boq.description', { defaultValue: 'Description' })}
                          </th>
                          <th className="w-10 px-1 py-1.5 text-center font-medium text-content-tertiary">
                            {t('boq.unit', { defaultValue: 'Unit' })}
                          </th>
                          <th className="w-16 px-1.5 py-1.5 text-right font-medium text-content-tertiary">
                            {t('boq.total', { defaultValue: 'Total' })}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {msg.items.map((item, idx) => {
                          const key = `${msg.id}-${idx}`;
                          const isSelected = selectedItems.has(key);
                          return (
                            <tr
                              key={key}
                              onClick={() => toggleItem(key)}
                              className={`border-t border-border-light cursor-pointer transition-colors ${
                                isSelected ? 'bg-oe-blue-subtle/20' : 'hover:bg-surface-secondary'
                              }`}
                            >
                              <td className="px-1.5 py-1.5 text-center">
                                <div
                                  className={`h-3.5 w-3.5 rounded border flex items-center justify-center mx-auto ${
                                    isSelected
                                      ? 'bg-oe-blue border-oe-blue'
                                      : 'border-border bg-surface-elevated'
                                  }`}
                                >
                                  {isSelected && <Check size={9} className="text-white" strokeWidth={3} />}
                                </div>
                              </td>
                              <td className="px-2 py-1.5 text-content-primary truncate max-w-0">
                                <span className="block truncate" title={item.description}>
                                  {item.description}
                                </span>
                              </td>
                              <td className="px-1 py-1.5 text-center text-content-secondary font-mono uppercase">
                                {item.unit}
                              </td>
                              <td className="px-1.5 py-1.5 text-right tabular-nums text-content-primary">
                                {fmtNum(item.total)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>

                    {/* Action buttons */}
                    <div className="flex items-center gap-2 px-2 py-2 border-t border-border-light bg-surface-secondary">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => handleAddItems(msg.id, msg.items!, true)}
                      >
                        {t('boq.add_all_to_boq', { defaultValue: 'Add all to BOQ' })}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleAddItems(msg.id, msg.items!, false)}
                      >
                        {t('boq.add_selected', {
                          defaultValue: `Add selected (${[...selectedItems].filter((k) => k.startsWith(msg.id)).length})`,
                        })}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Input ─────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border-light px-4 py-3 bg-surface-primary">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('boq.ai_placeholder', {
              defaultValue: 'Describe positions to generate...',
            })}
            disabled={chatMutation.isPending}
            className="flex-1 rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary outline-none focus:ring-2 focus:ring-oe-blue/20 focus:border-oe-blue/40 disabled:opacity-50 transition-all"
          />
          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || chatMutation.isPending}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
