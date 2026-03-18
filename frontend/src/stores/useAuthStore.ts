import { create } from 'zustand';

interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
  setTokens: (access: string, refresh: string) => void;
  logout: () => void;
  loadFromStorage: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  isAuthenticated: false,

  setTokens: (access, refresh) => {
    localStorage.setItem('oe_access_token', access);
    localStorage.setItem('oe_refresh_token', refresh);
    set({ accessToken: access, isAuthenticated: true });
  },

  logout: () => {
    localStorage.removeItem('oe_access_token');
    localStorage.removeItem('oe_refresh_token');
    set({ accessToken: null, isAuthenticated: false });
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('oe_access_token');
    set({ accessToken: token, isAuthenticated: Boolean(token) });
  },
}));
