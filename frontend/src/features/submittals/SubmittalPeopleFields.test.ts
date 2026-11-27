import { describe, expect, it } from 'vitest';
import { buildPeopleCreate, buildPeoplePatch } from './SubmittalPeopleFields';

const base = { ball_in_court: 'u1', distribution_list: ['u1', 'u2'] };

describe('the people of a submittal', () => {
  it('sends nothing when nothing changed', () => {
    expect(buildPeoplePatch(base, base)).toEqual({});
  });
  it('reassigns the ball, and hands it to nobody as null', () => {
    expect(buildPeoplePatch({ ...base, ball_in_court: 'u3' }, base)).toEqual({ ball_in_court: 'u3' });
    expect(buildPeoplePatch({ ...base, ball_in_court: '' }, base)).toEqual({ ball_in_court: null });
  });
  it('sends the whole list when it changes, an empty one included', () => {
    expect(buildPeoplePatch({ ...base, distribution_list: ['u2'] }, base)).toEqual({ distribution_list: ['u2'] });
    expect(buildPeoplePatch({ ...base, distribution_list: [] }, base)).toEqual({ distribution_list: [] });
  });
  it('a create leaves out an empty choice', () => {
    expect(buildPeopleCreate({ ball_in_court: '', distribution_list: [] })).toEqual({});
    expect(buildPeopleCreate(base)).toEqual(base);
  });
});
