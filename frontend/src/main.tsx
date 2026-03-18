import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider, MutationCache } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './app/App';
import './app/i18n';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
  mutationCache: new MutationCache({
    onError: (error) => {
      // Global error handler — shows toast-like message for any unhandled mutation error
      console.error('Mutation error:', error);
      const message = error instanceof Error ? error.message : 'Operation failed';
      // Only show if not a 401 (which redirects to login)
      if (!message.includes('401')) {
        // Create a temporary toast notification
        const toast = document.createElement('div');
        toast.className = 'fixed bottom-4 right-4 z-50 rounded-xl bg-red-600 px-4 py-3 text-sm text-white shadow-lg animate-slide-up';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
      }
    },
  }),
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
