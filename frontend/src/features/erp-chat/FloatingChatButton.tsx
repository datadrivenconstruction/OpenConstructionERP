// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Floating chat button — always visible in the bottom-right corner.
 *
 * Hides itself on routes that already host a full chat experience or where
 * the user isn't authenticated (login, onboarding), so we don't duplicate or
 * leak the assistant before the user has accepted terms.
 *
 * The unread badge is driven by `useFloatingChatStore.unreadCount`, which the
 * panel bumps every time the assistant produces a message while the panel is
 * closed. Opening the panel resets the counter.
 *
 * While the dock is open the button is hidden: the dock occupies the same
 * corner and has its own close button (and Alt+A / Escape). It stays in the
 * DOM, only `hidden`, so the dock can hand focus back to it on close.
 *
 * A second, amber badge counts the changes the assistant prepared in the
 * current conversation that nobody has applied or rejected yet. It sits in
 * the opposite corner from the red unread badge and carries an icon, so the
 * two never read as one number in two colours.
 */

import { useId, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ClipboardCheck, MessageCircle } from 'lucide-react';
import {
  DOCK_SHORTCUT_ARIA,
  DOCK_SHORTCUT_KEYS,
  isFloatingChatHiddenOn,
  useFloatingChatStore,
} from './useFloatingChat';
import { useChatActionStore } from './actions/useChatActions';
import { useAuthStore } from '@/stores/useAuthStore';

export function FloatingChatButton() {
  const { t } = useTranslation();
  const location = useLocation();
  const pendingId = useId();
  const isOpen = useFloatingChatStore((s) => s.isOpen);
  const unreadCount = useFloatingChatStore((s) => s.unreadCount);
  const toggle = useFloatingChatStore((s) => s.toggle);
  const conversationActionIds = useFloatingChatStore((s) => s.conversationActionIds);
  // The shared proposal store holds the live status of every card, so a
  // change applied from the Changes tab or another view stops counting here
  // at once.
  const pendingCount = useChatActionStore((s) =>
    conversationActionIds.reduce((n, id) => (s.byId[id]?.status === 'proposed' ? n + 1 : n), 0),
  );
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const accessToken = useAuthStore((s) => s.accessToken);

  const hidden = useMemo(() => {
    // Require either explicit isAuthenticated OR the presence of a token in
    // storage — both flags are set after loadFromStorage(), but tests that
    // poke sessionStorage directly only flip the token, not isAuthenticated,
    // until the next React render cycle.
    if (!isAuthenticated && !accessToken) return true;
    return isFloatingChatHiddenOn(location.pathname);
  }, [location.pathname, isAuthenticated, accessToken]);

  if (hidden) return null;

  const label = t('chat.floating.open', { defaultValue: 'Ask AI about your data' });
  const badgeLabel = t('chat.floating.unread_badge', {
    defaultValue: '{{count}} new',
    count: unreadCount,
  });
  const pendingLabel = t('chat.floating.pending_badge', {
    count: pendingCount,
    defaultValue: '{{count}} change is waiting for your review',
    defaultValue_other: '{{count}} changes are waiting for your review',
  });
  const showPending = pendingCount > 0 && !isOpen;
  // Key names are not translated anywhere in the app (the shortcuts dialog
  // prints them as-is), so the tooltip appends the chord verbatim.
  const shortcut = DOCK_SHORTCUT_KEYS.join('+');

  return (
    <button
      type="button"
      onClick={toggle}
      data-testid="floating-chat-button"
      aria-label={label}
      // The button's name is fixed ("Ask AI ..."); the waiting changes are
      // its description, read right after the name.
      aria-describedby={showPending ? pendingId : undefined}
      aria-expanded={isOpen}
      aria-keyshortcuts={DOCK_SHORTCUT_ARIA}
      title={`${label} (${shortcut})`}
      className={[
        'fixed bottom-4 right-4 z-50',
        'h-14 w-14 rounded-full',
        isOpen ? 'hidden' : 'flex',
        'items-center justify-center',
        'text-white shadow-lg',
        'bg-gradient-to-br from-oe-blue to-oe-blue-dark',
        'transition-all duration-200 ease-out',
        'hover:scale-105 hover:shadow-xl',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
        'active:scale-95',
      ].join(' ')}
      style={{
        // Fallback for tokens that may not exist in every theme — keep the
        // button visible even if --oe-blue-dark hasn't been defined yet.
        background:
          'linear-gradient(135deg, var(--oe-blue, #2563eb) 0%, var(--oe-blue-dark, #1d4ed8) 100%)',
      }}
    >
      <MessageCircle size={24} strokeWidth={2} aria-hidden />
      {unreadCount > 0 && !isOpen && (
        <span
          aria-label={badgeLabel}
          className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full bg-red-500 text-white text-xs font-semibold flex items-center justify-center border-2 border-white"
        >
          {unreadCount > 9 ? '9+' : unreadCount}
        </span>
      )}
      {showPending && (
        <span
          id={pendingId}
          role="img"
          aria-label={pendingLabel}
          title={pendingLabel}
          data-testid="floating-chat-pending-badge"
          className="absolute -bottom-1 -left-1 flex h-5 min-w-[20px] items-center justify-center gap-0.5 rounded-full border-2 border-white bg-semantic-warning-vivid px-1 text-xs font-semibold text-neutral-950 dark:border-neutral-900"
        >
          <ClipboardCheck size={10} strokeWidth={2.5} aria-hidden />
          {pendingCount > 9 ? '9+' : pendingCount}
        </span>
      )}
    </button>
  );
}

export default FloatingChatButton;
