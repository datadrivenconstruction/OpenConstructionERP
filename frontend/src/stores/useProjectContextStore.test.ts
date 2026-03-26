import { describe, it, expect, beforeEach } from 'vitest';
import { useProjectContextStore } from './useProjectContextStore';

describe('useProjectContextStore', () => {
  beforeEach(() => {
    // Reset store between tests
    const { clearProject } = useProjectContextStore.getState();
    clearProject();
    // Clear pinned
    useProjectContextStore.setState({ pinnedProjectIds: [] });
    localStorage.clear();
  });

  it('should have null initial state', () => {
    const state = useProjectContextStore.getState();
    expect(state.activeProjectId).toBeNull();
    expect(state.activeProjectName).toBe('');
    expect(state.activeBOQId).toBeNull();
  });

  it('should set active project', () => {
    const { setActiveProject } = useProjectContextStore.getState();
    setActiveProject('proj-1', 'Hospital Munich');

    const state = useProjectContextStore.getState();
    expect(state.activeProjectId).toBe('proj-1');
    expect(state.activeProjectName).toBe('Hospital Munich');
  });

  it('should set active BOQ', () => {
    const { setActiveProject, setActiveBOQ } = useProjectContextStore.getState();
    setActiveProject('proj-1', 'Test');
    setActiveBOQ('boq-1');

    expect(useProjectContextStore.getState().activeBOQId).toBe('boq-1');
  });

  it('should clear BOQ when setting null', () => {
    const { setActiveProject, setActiveBOQ } = useProjectContextStore.getState();
    setActiveProject('proj-1', 'Test');
    setActiveBOQ('boq-1');
    setActiveBOQ(null);

    expect(useProjectContextStore.getState().activeBOQId).toBeNull();
  });

  it('should clear all state', () => {
    const { setActiveProject, setActiveBOQ, clearProject } = useProjectContextStore.getState();
    setActiveProject('proj-1', 'Test');
    setActiveBOQ('boq-1');
    clearProject();

    const state = useProjectContextStore.getState();
    expect(state.activeProjectId).toBeNull();
    expect(state.activeProjectName).toBe('');
    expect(state.activeBOQId).toBeNull();
  });

  it('should toggle pinned projects', () => {
    const store = useProjectContextStore.getState();
    store.togglePinned('proj-1');
    expect(useProjectContextStore.getState().pinnedProjectIds).toContain('proj-1');

    store.togglePinned('proj-1');
    expect(useProjectContextStore.getState().pinnedProjectIds).not.toContain('proj-1');
  });

  it('should report isPinned correctly', () => {
    const store = useProjectContextStore.getState();
    expect(store.isPinned('proj-1')).toBe(false);

    store.togglePinned('proj-1');
    expect(useProjectContextStore.getState().isPinned('proj-1')).toBe(true);
  });

  it('should handle multiple pinned projects', () => {
    const store = useProjectContextStore.getState();
    store.togglePinned('proj-1');
    store.togglePinned('proj-2');
    store.togglePinned('proj-3');

    const { pinnedProjectIds } = useProjectContextStore.getState();
    expect(pinnedProjectIds).toHaveLength(3);
    expect(pinnedProjectIds).toContain('proj-1');
    expect(pinnedProjectIds).toContain('proj-2');
    expect(pinnedProjectIds).toContain('proj-3');
  });
});
