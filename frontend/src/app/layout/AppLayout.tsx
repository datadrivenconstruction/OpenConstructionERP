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

  // When a partner pack is active, present the app in the pack's language
  // (e.g. French for batimatech-ca). Forces once per activation; the deactivate
  // dialog reverts to English.
  usePartnerPackLocale();

  // When the user has white-labelled the workspace with their own company
  // name, the browser tab follows the same brand as the sidebar so the whole
  // experience reads as "their" tool. Falls back to OpenConstructionERP.
  const brandName = useBrandingStore((s) => (s.companyName.trim() ? s.companyName.trim() : null));

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
    <div className="min-h-screen">
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

      {/* Floating chat — always-visible button + slide-in panel that talks
          to the erp_chat backend. The button hides itself on /chat (no
          duplication of the full-page experience) and on auth-bypass routes
          (/login, /onboarding). The panel is mounted at the layout level so
          the conversation survives navigation. */}
      <FloatingChatButton />
      <FloatingChatPanel />

      {/* Global onboarding tour (ProductTour) mounts once at App.tsx
          top level — moving it out of here was the fix for
          BUG-UI02-TOUR-PERSISTENT. When mounted inside AppLayout, it
          remounted on every route change (the page wrapper ``P``
          recreates the layout per Route), and a tour
          clicked-but-not-completed re-rendered from step 1 on every
          navigation. The legacy `OnboardingTour` (storage key
          `oe_tour_completed`, no dot) used to be mounted alongside it
          and is now collapsed into ProductTour — see App.tsx for the
          legacy-key migration. */}
    </div>
  );
}
