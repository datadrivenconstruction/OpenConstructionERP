import { useState, useCallback, useEffect } from 'react';
import type { ReactNode } from 'react';
import clsx from 'clsx';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { FeedbackDialog, OnboardingTour } from '@/shared/ui';
import { FloatingQueuePanel } from './FloatingQueuePanel';
import { GlobalProgress } from '@/shared/ui/GlobalProgress';
import { OfflineBanner } from '@/shared/ui/OfflineBanner';

import { useSwipeGesture, useEdgeSwipe } from '@/shared/hooks/useSwipeGesture';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { useOfflineSync } from '@/shared/hooks/useOnlineStatus';

interface AppLayoutProps {
  title?: string;
  children: ReactNode;
}

export function AppLayout({ title, children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const isRTL = useIsRTL();

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);
  const openSidebar = useCallback(() => setSidebarOpen(true), []);

  useEffect(() => {
    document.title = title ? `${title} | OpenConstructionERP` : 'OpenConstructionERP';
  }, [title]);

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
    <div className="min-h-screen bg-surface-secondary">
      <OfflineBanner />
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

      {/* Main area — offset from the sidebar side (left in LTR, right in RTL) */}
      <div className="lg:pl-sidebar">
        <Header
          title={title}
          onMenuClick={openSidebar}
        />
        <main className="px-3 py-4 sm:px-4 lg:px-6">
          <div className="mx-auto max-w-content">
            {children}
          </div>
        </main>
      </div>

      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />

      {/* Floating queue panel — shows background task progress */}
      <FloatingQueuePanel />

      {/* Onboarding tour — auto-starts on first visit */}
      <OnboardingTour />
    </div>
  );
}
