import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { X, Bug, Lightbulb, MessageCircle, ExternalLink, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

interface FeedbackDialogProps {
  open: boolean;
  onClose: () => void;
}

type FeedbackCategory = 'bug' | 'idea' | 'general';

const CATEGORIES: { key: FeedbackCategory; icon: typeof Bug; labelKey: string; defaultLabel: string }[] = [
  { key: 'bug', icon: Bug, labelKey: 'feedback.category_bug', defaultLabel: 'Bug Report' },
  { key: 'idea', icon: Lightbulb, labelKey: 'feedback.category_idea', defaultLabel: 'Feature Idea' },
  { key: 'general', icon: MessageCircle, labelKey: 'feedback.category_general', defaultLabel: 'General' },
];

const GITHUB_ISSUES_URL =
  'https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new';

export function FeedbackDialog({ open, onClose }: FeedbackDialogProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  const [category, setCategory] = useState<FeedbackCategory>('general');
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [email, setEmail] = useState('');
  const [sending, setSending] = useState(false);

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setCategory('general');
      setSubject('');
      setDescription('');
      setEmail('');
      setSending(false);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose]);

  // Focus dialog
  useEffect(() => {
    if (open) dialogRef.current?.focus();
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!subject.trim() || !description.trim()) return;

    setSending(true);
    try {
      await apiPost('/v1/feedback', {
        category,
        subject: subject.trim(),
        description: description.trim(),
        email: email.trim() || null,
        page_path: location.pathname,
      });
      addToast({
        type: 'success',
        title: t('feedback.success', { defaultValue: 'Thank you! Your feedback has been received.' }),
      });
      onClose();
    } catch {
      addToast({
        type: 'error',
        title: t('feedback.error', { defaultValue: 'Could not send feedback. Please try again or report on GitHub.' }),
      });
    } finally {
      setSending(false);
    }
  }

  function openGitHub() {
    const params = new URLSearchParams({
      title: subject.trim() ? `[${category}] ${subject.trim()}` : '',
      body: description.trim() || '',
    });
    window.open(`${GITHUB_ISSUES_URL}?${params}`, '_blank', 'noopener');
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('feedback.title', { defaultValue: 'Send Feedback' })}
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-md mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h2 className="text-base font-semibold text-content-primary">
            {t('feedback.title', { defaultValue: 'Send Feedback' })}
          </h2>
          <button
            onClick={onClose}
            className={clsx(
              'flex h-8 w-8 items-center justify-center rounded-lg',
              'text-content-tertiary transition-colors',
              'hover:bg-surface-secondary hover:text-content-secondary',
            )}
            aria-label={t('common.cancel', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 pb-6 space-y-4">
          {/* Category pills */}
          <div className="flex gap-2">
            {CATEGORIES.map((cat) => {
              const Icon = cat.icon;
              const active = category === cat.key;
              return (
                <button
                  key={cat.key}
                  type="button"
                  onClick={() => setCategory(cat.key)}
                  className={clsx(
                    'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all',
                    active
                      ? cat.key === 'bug'
                        ? 'bg-semantic-error-bg text-semantic-error border border-semantic-error/20'
                        : cat.key === 'idea'
                          ? 'bg-[#7c3aed]/10 text-[#7c3aed] border border-[#7c3aed]/20'
                          : 'bg-oe-blue/10 text-oe-blue border border-oe-blue/20'
                      : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary border border-transparent',
                  )}
                >
                  <Icon size={13} />
                  {t(cat.labelKey, { defaultValue: cat.defaultLabel })}
                </button>
              );
            })}
          </div>

          {/* Subject */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('feedback.subject', { defaultValue: 'Subject' })}
              <span className="text-semantic-error ml-0.5">*</span>
            </label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={t('feedback.subject_placeholder', { defaultValue: 'Brief summary...' })}
              required
              maxLength={200}
              className={clsx(
                'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2',
                'text-sm text-content-primary placeholder:text-content-quaternary',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                'transition-colors',
              )}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('feedback.description', { defaultValue: 'Description' })}
              <span className="text-semantic-error ml-0.5">*</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('feedback.description_placeholder', { defaultValue: 'Tell us what happened or what you\'d like to see...' })}
              required
              rows={4}
              maxLength={2000}
              className={clsx(
                'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2',
                'text-sm text-content-primary placeholder:text-content-quaternary',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                'transition-colors resize-none',
              )}
            />
          </div>

          {/* Email */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('feedback.email', { defaultValue: 'Email (optional)' })}
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className={clsx(
                'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2',
                'text-sm text-content-primary placeholder:text-content-quaternary',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                'transition-colors',
              )}
            />
            <p className="mt-1 text-2xs text-content-quaternary">
              {t('feedback.email_hint', { defaultValue: 'For follow-up — we won\'t spam' })}
            </p>
          </div>

          {/* Page context */}
          <div className="text-2xs text-content-quaternary">
            {t('feedback.page_context', { defaultValue: 'Page: {{page}}', page: location.pathname })}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-1">
            <button
              type="button"
              onClick={openGitHub}
              className="flex items-center gap-1 text-xs text-content-tertiary hover:text-content-secondary transition-colors"
            >
              {t('feedback.github_link', { defaultValue: 'Or report on GitHub' })}
              <ExternalLink size={11} />
            </button>
            <button
              type="submit"
              disabled={sending || !subject.trim() || !description.trim()}
              className={clsx(
                'flex items-center gap-2 rounded-lg px-4 py-2',
                'text-sm font-medium text-white transition-all',
                'bg-oe-blue hover:bg-oe-blue-hover',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {sending && <Loader2 size={14} className="animate-spin" />}
              {t('feedback.submit', { defaultValue: 'Send Feedback' })}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
