import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TakeoffFlowSteps } from '../TakeoffFlowSteps';

describe('TakeoffFlowSteps', () => {
  it('explains the takeoff from the Revit parameter to the applied quantity, in order', () => {
    render(<TakeoffFlowSteps />);
    const steps = within(screen.getByTestId('bim-rules-flow-steps')).getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    expect(steps[0]).toHaveTextContent(/Revit/);
    expect(steps[1]).toHaveTextContent(/property filters/);
    expect(steps[2]).toHaveTextContent(/BOQ position/);
    expect(steps[3]).toHaveTextContent(/Apply/);
  });
});
