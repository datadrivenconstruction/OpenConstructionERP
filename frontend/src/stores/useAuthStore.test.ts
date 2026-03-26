import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from './useAuthStore';

describe('useAuthStore', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.setState({ accessToken: null, isAuthenticated: false, userEmail: null });
  });

  it('should start unauthenticated', () => {
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(state.userEmail).toBeNull();
  });

  it('should set tokens with remember=true (localStorage)', () => {
    useAuthStore.getState().setTokens('access123', 'refresh456', true, 'test@example.com');
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe('access123');
    expect(state.userEmail).toBe('test@example.com');
    expect(localStorage.getItem('oe_access_token')).toBe('access123');
    expect(localStorage.getItem('oe_user_email')).toBe('test@example.com');
  });

  it('should set tokens with remember=false (sessionStorage)', () => {
    useAuthStore.getState().setTokens('access123', 'refresh456', false, 'test@example.com');
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(sessionStorage.getItem('oe_access_token')).toBe('access123');
    expect(localStorage.getItem('oe_access_token')).toBeNull();
  });

  it('should clear everything on logout', () => {
    useAuthStore.getState().setTokens('access123', 'refresh456', true, 'test@example.com');
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(state.userEmail).toBeNull();
    expect(localStorage.getItem('oe_access_token')).toBeNull();
    expect(localStorage.getItem('oe_user_email')).toBeNull();
  });

  it('should load from localStorage', () => {
    localStorage.setItem('oe_access_token', 'stored_token');
    localStorage.setItem('oe_user_email', 'stored@example.com');
    useAuthStore.getState().loadFromStorage();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe('stored_token');
    expect(state.userEmail).toBe('stored@example.com');
  });

  it('should load from sessionStorage when localStorage is empty', () => {
    sessionStorage.setItem('oe_access_token', 'session_token');
    useAuthStore.getState().loadFromStorage();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe('session_token');
  });

  it('should remain unauthenticated when both storages are empty', () => {
    useAuthStore.getState().loadFromStorage();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
  });
});
