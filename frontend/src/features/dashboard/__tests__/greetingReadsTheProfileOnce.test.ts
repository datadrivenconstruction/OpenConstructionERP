// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every dashboard open asked GET /v1/users/me/ twice. The auth store reads the
// profile once at app start (syncRoleFromServer) and keeps the name, and the
// dashboard then asked the same route again under ['me'] for the greeting,
// only to read that same name. On a failure its queryFn cached `null` under
// ['me'], which Settings, Projects and the approval cards read as the profile.
//
// The first half pins the source the greeting now reads: the store's one read
// of the profile, and the refresh Settings triggers after a rename. The second
// half pins the call sites, so the dashboard does not grow the request back.

import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import { createAuthStore, type AuthTabEnv } from '@/stores/useAuthStore';

class MemoryStorage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(key: string) {
    return this.data.has(key) ? this.data.get(key)! : null;
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
}

const b64url = (value: object) =>
  btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const jwt = (claims: object) => `h.${b64url(claims)}.s`;

function storeWithProfile(profile: { full_name?: string; role?: string }) {
  const current = { ...profile };
  const fetchMock = vi.fn(async (input: string) => {
    if (input === '/api/v1/users/me/') {
      return { ok: true, status: 200, json: async () => ({ ...current }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
  const local = new MemoryStorage();
  const env: AuthTabEnv = {
    local: () => local as unknown as Storage,
    session: () => new MemoryStorage() as unknown as Storage,
    channel: null,
    locks: null,
    fetch: fetchMock as unknown as AuthTabEnv['fetch'],
    reload: vi.fn(),
    goToLogin: vi.fn(),
  };
  const store = createAuthStore(env);
  return { store, fetchMock, local, current };
}

const profileReads = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.filter((c) => c[0] === '/api/v1/users/me/').length;

describe('the name the dashboard greets with', () => {
  it('is read from the profile once, at sign-in', async () => {
    const { store, fetchMock } = storeWithProfile({ full_name: 'Maria Schmidt', role: 'editor' });

    store.getState().setTokens(jwt({ sub: 'u1', role: 'viewer' }), jwt({ sub: 'u1', type: 'refresh' }), false, 'm@x.io');
    await vi.waitFor(() => expect(store.getState().userFullName).toBe('Maria Schmidt'));

    expect(profileReads(fetchMock)).toBe(1);
    expect(store.getState().userRole).toBe('editor');
  });

  it('follows a rename once Settings asks the store to refresh', async () => {
    const { store, fetchMock, local, current } = storeWithProfile({ full_name: 'Maria Schmidt' });
    store.getState().setTokens(jwt({ sub: 'u1' }), jwt({ sub: 'u1', type: 'refresh' }), false, 'm@x.io');
    await vi.waitFor(() => expect(store.getState().userFullName).toBe('Maria Schmidt'));

    current.full_name = 'Maria Weber';
    await store.getState().syncRoleFromServer();

    expect(store.getState().userFullName).toBe('Maria Weber');
    // Kept for the next reload, so the greeting paints the new name at once.
    expect(local.getItem('oe_user_full_name')).toBe('Maria Weber');
    expect(profileReads(fetchMock)).toBe(2);
  });

  it('drops a late answer that describes the account signed in before', async () => {
    const answers: Array<(body: object) => void> = [];
    const fetchMock = vi.fn(
      (input: string) =>
        new Promise<Response>((resolve) => {
          if (input !== '/api/v1/users/me/') {
            resolve({ ok: false, status: 404, json: async () => ({}) } as Response);
            return;
          }
          answers.push((body) => resolve({ ok: true, status: 200, json: async () => body } as Response));
        }),
    );
    const store = createAuthStore({
      local: () => new MemoryStorage() as unknown as Storage,
      session: () => new MemoryStorage() as unknown as Storage,
      channel: null,
      locks: null,
      fetch: fetchMock as unknown as AuthTabEnv['fetch'],
      reload: vi.fn(),
      goToLogin: vi.fn(),
    });

    store.getState().setTokens(jwt({ sub: 'user-a' }), jwt({ sub: 'user-a', type: 'refresh' }), false, 'a@x.io');
    store.getState().setTokens(jwt({ sub: 'user-b' }), jwt({ sub: 'user-b', type: 'refresh' }), false, 'b@x.io');
    expect(answers).toHaveLength(2);

    answers[1]!({ full_name: 'Bea Brown' });
    await vi.waitFor(() => expect(store.getState().userFullName).toBe('Bea Brown'));
    answers[0]!({ full_name: 'Adam Ash' });
    await new Promise((r) => setTimeout(r, 0));

    expect(store.getState().userFullName).toBe('Bea Brown');
  });

  it('keeps the known name when the profile cannot be read', async () => {
    const { store, fetchMock } = storeWithProfile({ full_name: 'Maria Schmidt' });
    store.getState().setTokens(jwt({ sub: 'u1' }), jwt({ sub: 'u1', type: 'refresh' }), false, 'm@x.io');
    await vi.waitFor(() => expect(store.getState().userFullName).toBe('Maria Schmidt'));

    fetchMock.mockRejectedValueOnce(new TypeError('network down'));
    await store.getState().syncRoleFromServer();

    expect(store.getState().userFullName).toBe('Maria Schmidt');
  });
});

function srcRoot(): string {
  const candidates = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')];
  const hit = candidates.find((c) => existsSync(join(c, 'features', 'dashboard', 'DashboardPage.tsx')));
  if (!hit) throw new Error(`no src root among ${candidates.join(', ')}`);
  return hit;
}

describe('the dashboard and the profile route', () => {
  const root = srcRoot();
  const dashboard = readFileSync(join(root, 'features', 'dashboard', 'DashboardPage.tsx'), 'utf8');
  const settings = readFileSync(join(root, 'features', 'settings', 'SettingsPage.tsx'), 'utf8');

  it('does not fetch the profile itself', () => {
    expect(dashboard).not.toMatch(/apiGet<[^(]*>\(\s*'\/v1\/users\/me\/'\s*\)/);
    expect(dashboard).not.toMatch(/queryKey:\s*\['me'\]/);
  });

  it('greets with the name the auth store holds', () => {
    expect(dashboard).toMatch(/useAuthStore\(\(s\) => s\.userFullName\)/);
  });

  it('is told about a rename by the Settings profile save', () => {
    // The mutation that PATCHes the profile name must refresh the store in its
    // onSuccess, or the greeting keeps the old name until the next reload.
    const mutation = settings.match(/const profileMutation = useMutation\(\{[\s\S]*?\n {2}\}\);/);
    expect(mutation, 'profileMutation not found in SettingsPage.tsx').not.toBeNull();
    expect(mutation![0]).toMatch(/onSuccess:[\s\S]*syncRoleFromServer\(\)/);
  });
});
