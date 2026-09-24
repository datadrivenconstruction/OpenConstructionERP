// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Sidebar, FloatingRecentButton } from './Sidebar';
import { Header, resolvePageTitleKey } from './Header';
import { DesktopToolbar } from './DesktopToolbar';
import { FeedbackDialog } from '@/shared/ui';
import { FloatingQueuePanel } from './FloatingQueuePanel';
import { GlobalProgress } from '@/shared/ui/GlobalProgress';
import { GlobalUploadIndicator } from '@/shared/ui/GlobalUploadIndicator';
import { DwgUploadIndicator } from '@/shared/ui/DwgUploadIndicator';
import { GlobalCatalogueInstallIndicator } from '@/shared/ui/GlobalCatalogueInstallIndicator';
import { DemoBanner } from '@/shared/ui/DemoBanner';
import { ReviewPromptCard } from '@/shared/ui/ReviewPromptCard';
import { FloatingChatButton } from '@/features/erp-chat/FloatingChatButton';
import { FloatingChatPanel } from '@/features/erp-chat/FloatingChatPanel';
import {
  DashboardBackdrop,
  backdropVariantForPath,
} from '@/features/dashboard/components/DashboardBackdrop';

import { useSwipeGesture, useEdgeSwipe } from '@/shared/hooks/useSwipeGesture';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { useOfflineSync } from '@/shared/hooks/useOnlineStatus';
import { usePartnerPackLocale } from '@/shared/hooks/usePartnerPackLocale';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { useReviewPromptStore } from '@/stores/useReviewPromptStore';
import { useGlobalPresenceSocket } from '@/features/global_presence';

interface AppLayoutProps {
  title?: string;
  children: ReactNode;
}

export function AppLayout({ title, children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const isRTL = useIsRTL();
  const location = useLocation();
  const backdropVariant = backdropVariantForPath(location.pathname);
  const { t, i18n } = useTranslation();

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);
  const openSidebar = useCallback(() => setSidebarOpen(true), []);

  // Global presence: one WebSocket for the whole session, sends route
  // updates on navigation and idle/active status on tab visibility.
  useGlobalPresenceSocket();

  // When a partner pack is active, present the app in the pack's language
  // (e.g. French for batimatech-ca). Forces once per activation; the deactivate
  // dialog reverts to English.
  usePartnerPackLocale();

  // When the user has white-labelled the workspace with their own company
  // name, the browser tab follows the same brand as the sidebar so the whole
  // experience reads as "their" tool. Falls back to OpenConstructionERP.
  const brandName = useBrandingStore((s) => (s.companyName.trim() ? s.companyName.trim() : null));

  // Count today towards "distinct days the app was opened". This has to run
  // from the shell, unconditionally, and NOT from ReviewPromptCard: if the
  // day were recorded by the card, the counter would only advance on days
  // the card already rendered and could never reach its own threshold. The
  // write is idempotent per day. AppLayout mounts once per signed-in session
  // (App.tsx `AppShell` hoists it above the router outlet), so this effect
  // runs when the shell mounts, not on every navigation.
  const recordActiveDay = useReviewPromptStore((s) => s.recordActiveDay);
  useEffect(() => {
    recordActiveDay();
  }, [recordActiveDay]);

  useEffect(() => {
    // Translate the browser-tab title through the same map the on-screen
    // page heading uses, so the tab also follows the active language.
    const key = resolvePageTitleKey(title);
    const translated = title ? (key ? t(key, { defaultValue: title }) : title) : null;
    const suffix = brandName ?? 'OpenConstructionERP';
    document.title = translated ? `${translated} | ${suffix}` : suffix;
    // i18n.language in deps so the tab re-translates on a language switch.
  }, [title, t, i18n.language, brandName]);

  // Lock body scroll when mobile sidebar is open
  useEffect(() => {
    if (sidebarOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [sidebarOpen]);

  // Auto-replay offline mutations when coming back online
  useOfflineSync();

  // In RTL: swipe right on sidebar → close it; swipe left from right edge → open it
  const sidebarRef = useSwipeGesture<HTMLDivElement>({
    onSwipeLeft: isRTL ? undefined : closeSidebar,
    onSwipeRight: isRTL ? closeSidebar : undefined,
    enabled: sidebarOpen,
  });

  // In RTL: swipe left from right edge → open sidebar
  useEdgeSwipe({
    onSwipeRight: isRTL ? undefined : openSidebar,
    onSwipeLeft: isRTL ? openSidebar : undefined,
    enabled: !sidebarOpen,
  });

  return (
    // `oe-ai-dock-shell` (index.css) pads the whole shell by
    // --oe-ai-dock-offset: the AI dock's width while it is open in push
    // mode, 0 otherwise. On the ROOT rather than the `lg:pl-sidebar`
    // wrapper, so the demo banner shrinks with the page and the RTL rule on
    // that wrapper (which rewrites both of its horizontal paddings) is never
    // in play. Full-bleed pages (`-mx-4 sm:-mx-7` inside <main>) follow the
    // narrower wrapper and stay aligned.
    <div className="min-h-screen oe-ai-dock-shell">
      {/* Single global backdrop — route-aware variant. Mounted at the
          AppLayout level (not per-page) so pages don't need a `relative
          isolate` wrapper, which would otherwise trap full-screen modals
          beneath the sticky header. The backdrop itself paints the base
          `bg-surface-secondary` wash on its layer 1, so the AppLayout
          root MUST NOT also set `bg-surface-secondary` — otherwise it
          paints above the `fixed -z-10` backdrop in the root stacking
          context and hides the tinted spotlight. */}
      <DashboardBackdrop variant={backdropVariant} />
      <DemoBanner />
      <GlobalProgress />

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm lg:hidden animate-fade-in"
          onClick={closeSidebar}
        />
      )}

      {/* Sidebar — fixed on desktop, slide-in on mobile.
          In LTR the sidebar is anchored left; in RTL it is anchored right.
          The CSS rules in index.css handle the `left-0`→`right-0` flip for
          `.oe-sidebar` when `dir="rtl"` is set on <html>. */}
      <div
        ref={sidebarRef}
        className={clsx(
          'oe-sidebar fixed inset-y-0 z-50 transition-transform duration-normal ease-oe',
          // LTR: attach to left edge; RTL: CSS overrides to right edge
          'left-0',
          'lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <Sidebar onClose={closeSidebar} />
      </div>

      {/* Main area — offset from the sidebar side (left in LTR, right in RTL).
          Consistent padding (px-4 sm:px-7) across all modules.
          Full-bleed pages (BIM viewer, DWG takeoff, AI chat) negate it
          via `-mx-4 sm:-mx-7` on their root div. */}
      <div className="lg:pl-sidebar">
        {/* Desktop-only browser-style chrome (Back/Forward/Reload/Home,
            address field, open-in-browser, favorites). Renders null in the
            normal web build. Sits above the Header so it reads as window
            chrome. */}
        <DesktopToolbar />
        <Header
          title={title}
          onMenuClick={openSidebar}
        />
        <main className="px-4 pt-6 pb-4 sm:px-7">
          {children}
        </main>
      </div>

      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />

      {/* Floating queue panel — shows background task progress */}
      <FloatingQueuePanel />

      {/* Global BIM upload indicator — survives route changes */}
      <GlobalUploadIndicator />

      {/* Global DWG upload indicator — same lifecycle as the BIM one, sits
          in the stack above it. Both ignore the current route so a user
          can kick off a DWG upload and immediately navigate anywhere. */}
      <DwgUploadIndicator />

      {/* Catalogue install indicator — surfaces v3 snapshot downloads
          kicked off from /match-elements so the user can navigate away
          while the 200–500 MB snapshot downloads in the background. */}
      <GlobalCatalogueInstallIndicator />

      {/* Floating Recent button — bottom-right corner */}
      <FloatingRecentButton />

      {/* AI assistant — the round button and the dock it opens (Alt+A
          toggles it too). The dock pushes the page aside on wide screens
          (see `oe-ai-dock-shell` above) and floats over it otherwise. Both
          stay out of /chat, which is the full-page version of the same
          assistant. Mounted at the layout level so the conversation
          survives navigation. */}
      <FloatingChatButton />
      <FloatingChatPanel />

      {/* Occasional, non-blocking ask for a rating or review. Mounted here
          rather than at App.tsx top level on purpose: this shell is behind
          auth, and /login, /register, /forgot-password and /onboarding all
          render OUTSIDE it, so those surfaces are excluded structurally
          instead of by a route blocklist that would rot. AppLayout mounts
          once per signed-in session (App.tsx `AppShell`), and every piece of
          state the card needs lives in useReviewPromptStore anyway, not in
          the component. */}
      <ReviewPromptCard />

      {/* Global onboarding tour (ProductTour) mounts once at App.tsx
          top level — moving it out of here was the fix for
          BUG-UI02-TOUR-PERSISTENT. When it was mounted inside AppLayout,
          it remounted on every route change (back then the page wrapper
          ``P`` recreated the layout per Route; App.tsx `AppShell` has
          since hoisted the layout so it mounts once), and a tour
          clicked-but-not-completed re-rendered from step 1 on every
          navigation. The legacy `OnboardingTour` (storage key
          `oe_tour_completed`, no dot) used to be mounted alongside it
          and is now collapsed into ProductTour — see App.tsx for the
          legacy-key migration. */}
    </div>
  );
}
