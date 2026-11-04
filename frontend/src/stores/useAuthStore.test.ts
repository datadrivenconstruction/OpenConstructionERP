// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useAuthStore } from './useAuthStore';
import { COMPANY_TYPE_STORAGE_KEY } from '@/app/layout/useCompanyWorkspace';

describe('useAuthStore', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.setState({ accessToken: null, isAuthenticated: false, userEmail: null, userId: null });
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

  describe('on a browser two people share', () => {
    const tokenFor = (userId: string) => `header.${btoa(JSON.stringify({ sub: userId }))}.signature`;

    it('reads the user id from the token and keeps it across a refresh and a reload', () => {
      useAuthStore.getState().setTokens(tokenFor('user-a'), 'refresh-1', true, 'a@example.com');
      expect(useAuthStore.getState().userId).toBe('user-a');
      useAuthStore.getState().setTokens(tokenFor('user-a'), 'refresh-2', true, 'a@example.com');
      expect(useAuthStore.getState().userId).toBe('user-a');
      useAuthStore.getState().loadFromStorage();
      expect(useAuthStore.getState().userId).toBe('user-a');
      useAuthStore.getState().logout();
      expect(useAuthStore.getState().userId).toBeNull();
    });

    it('has no user id for a token that carries none', () => {
      useAuthStore.getState().setTokens('access123', 'refresh456', true, 'test@example.com');
      expect(useAuthStore.getState().userId).toBeNull();
    });

    it('forgets the cached company profile on logout', () => {
      useAuthStore.getState().setTokens(tokenFor('user-a'), 'refresh-1', true, 'a@example.com');
      localStorage.setItem(COMPANY_TYPE_STORAGE_KEY, 'general_contractor');
      useAuthStore.getState().logout();
      expect(localStorage.getItem(COMPANY_TYPE_STORAGE_KEY)).toBeNull();
    });

    it('forgets it when another account signs in, and keeps it on a token refresh', () => {
      useAuthStore.getState().setTokens(tokenFor('user-a'), 'refresh-1', true, 'a@example.com');
      localStorage.setItem(COMPANY_TYPE_STORAGE_KEY, 'general_contractor');
      useAuthStore.getState().setTokens(tokenFor('user-a'), 'refresh-2', true, 'a@example.com');
      expect(localStorage.getItem(COMPANY_TYPE_STORAGE_KEY)).toBe('general_contractor');
      useAuthStore.getState().setTokens(tokenFor('user-b'), 'refresh-3', true, 'b@example.com');
      expect(localStorage.getItem(COMPANY_TYPE_STORAGE_KEY)).toBeNull();
    });
  });

  describe('refreshAccessToken', () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it('returns null and does not log out when no refresh token is stored', async () => {
      const token = await useAuthStore.getState().refreshAccessToken();
      expect(token).toBeNull();
    });

    it('rotates tokens on success and keeps the remember=true tier', async () => {
      useAuthStore.getState().setTokens('old_access', 'old_refresh', true, 'user@example.com');
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ access_token: 'new_access', refresh_token: 'new_refresh' }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const token = await useAuthStore.getState().refreshAccessToken();

      expect(token).toBe('new_access');
      expect(useAuthStore.getState().accessToken).toBe('new_access');
      // remember=true → tokens live in localStorage, not sessionStorage.
      expect(localStorage.getItem('oe_access_token')).toBe('new_access');
      expect(localStorage.getItem('oe_refresh_token')).toBe('new_refresh');
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/users/auth/refresh/',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('returns null without mutating state when the refresh token is rejected (401)', async () => {
      useAuthStore.getState().setTokens('old_access', 'bad_refresh', false, 'user@example.com');
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) }));

      const token = await useAuthStore.getState().refreshAccessToken();

      expect(token).toBeNull();
      // Session is NOT torn down here — the API client decides to log out.
      expect(useAuthStore.getState().accessToken).toBe('old_access');
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    it('coalesces concurrent refreshes into a single network call', async () => {
      useAuthStore.getState().setTokens('old_access', 'old_refresh', false, 'user@example.com');
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ access_token: 'new_access', refresh_token: 'new_refresh' }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const [a, b, c] = await Promise.all([
        useAuthStore.getState().refreshAccessToken(),
        useAuthStore.getState().refreshAccessToken(),
        useAuthStore.getState().refreshAccessToken(),
      ]);

      expect(a).toBe('new_access');
      expect(b).toBe('new_access');
      expect(c).toBe('new_access');
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });
});

describe('field data purge on session change', () => {
  it('purges on logout and on user switch, not on same-user refresh', async () => {
    const mod = await import('@/shared/lib/offline/fieldSession');
    const spy = vi.spyOn(mod, 'purgeFieldUserData').mockResolvedValue(undefined);
    useAuthStore.getState().setTokens('a1', 'r1', true, 'one@example.com');
    spy.mockClear();
    useAuthStore.getState().setTokens('a2', 'r2', true, 'one@example.com');
    expect(spy).not.toHaveBeenCalled();
    useAuthStore.getState().setTokens('a3', 'r3', true, 'two@example.com');
    expect(spy).toHaveBeenCalledTimes(1);
    useAuthStore.getState().logout();
    expect(spy).toHaveBeenCalledTimes(2);
    spy.mockRestore();
  });
});
