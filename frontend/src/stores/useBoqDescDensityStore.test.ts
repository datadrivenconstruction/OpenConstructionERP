import { beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from './useAuthStore';
import { useBoqDescDensityStore } from './useBoqDescDensityStore';

describe('Langtext display mode', () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ userId: null });
    useBoqDescDensityStore.setState({ density: 'comfortable' });
  });

  it('defaults to the first two lines', () => {
    useAuthStore.setState({ userId: 'u-default' });
    expect(useBoqDescDensityStore.getState().density).toBe('comfortable');
  });

  it('remembers the choice per user', () => {
    useAuthStore.setState({ userId: 'u-a' });
    useBoqDescDensityStore.getState().setDensity('tall');
    useAuthStore.setState({ userId: 'u-b' });
    expect(useBoqDescDensityStore.getState().density).toBe('comfortable');
    useAuthStore.setState({ userId: 'u-a' });
    expect(useBoqDescDensityStore.getState().density).toBe('tall');
  });
});
