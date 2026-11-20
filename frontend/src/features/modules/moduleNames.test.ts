import { describe, it, expect } from 'vitest';
import { moduleNames } from './moduleNames';

const t = (key: string, o: { defaultValue: string }) => (key === 'design.title' ? 'Design' : o.defaultValue);

describe('module ids in the "required by" text', () => {
  it('shows the manifest name, and the id only for an unknown module', () => {
    expect(moduleNames(t, ['design', 'no_such_module'])).toEqual(['Design', 'no_such_module']);
  });
});
