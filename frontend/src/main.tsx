import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider, MutationCache } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './app/App';
import { useToastStore } from '@/stores/useToastStore';
import './app/i18n';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — data considered fresh for 30s, then refetch on focus/mount
      gcTime: 5 * 60_000, // 5min — keep in cache for 5 min after unmount
      // Offline-first: try the cache before spinning a 300s AbortController.
      // `api.ts` falls back to IndexedDB via offlineStore on network errors,
      // so we never want to retry a query that's going to fail for the same
      // reason anyway.
      networkMode: 'offlineFirst',
      retry: (count, error) => {
        if (!navigator.onLine) return false;
        // 4xx responses are deterministic — don't retry.
        if (error && typeof error === 'object' && 'status' in error) {
          const status = (error as { status: number }).status;
          if (status >= 400 && status < 500) return false;
        }
        return count < 1;
      },
      refetchOnWindowFocus: true, // refetch when user tabs back
    },
    mutations: {
      // Mutations while offline are queued by offlineStore and replayed on
      // reconnect — no need for react-query-level retry.
      networkMode: 'offlineFirst',
      retry: 0,
    },
  },
  mutationCache: new MutationCache({
    onSuccess: (_data, _variables, _context, mutation) => {
      // Global: after ANY successful mutation, invalidate related queries
      // This ensures lists refresh immediately after create/update/delete
      const key = mutation.options.mutationKey;
      if (key && Array.isArray(key) && key.length > 0) {
        queryClient.invalidateQueries({ queryKey: [key[0]] });
      }
    },
    onError: (error) => {
      console.error('Mutation error:', error);
      const message = error instanceof Error ? error.message : 'Operation failed';
      if (!message.includes('401')) {
        useToastStore.getState().addToast({
          type: 'error',
          title: 'Operation failed',
          message,
        });
      }
    },
  }),
});

// Stamp the root element with an origin token. Survives in the live DOM
// and any saved-page snapshot — looks like a deterministic build id.
// Decodes to "DDC-CWICR-OE-2026" by reversing the hex.
const __rootEl = document.getElementById('root')!;
__rootEl.setAttribute(
  'data-build-rev',
  '4443432d4357494352-4f452d32303236',
);

ReactDOM.createRoot(__rootEl).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
