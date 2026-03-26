import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { OnboardingTour, ONBOARDING_STORAGE_KEY, DEFAULT_TOUR_STEPS } from './OnboardingTour';
import type { TourStep } from './OnboardingTour';

/* ── Helpers ─────────────────────────────────────────────────────────────── */

/** Minimal tour steps — two steps so we can test prev/next clearly */
const TWO_STEPS: TourStep[] = [
  {
    target: '[data-tour="sidebar"]',
    title: 'Step One',
    description: 'Description one',
    position: 'right',
  },
  {
    target: '[data-tour="boq"]',
    title: 'Step Two',
    description: 'Description two',
    position: 'right',
  },
];

/** Three steps — useful for testing that middle step shows Prev */
const THREE_STEPS: TourStep[] = [
  ...TWO_STEPS,
  {
    target: '[data-tour="costs"]',
    title: 'Step Three',
    description: 'Description three',
    position: 'right',
  },
];

function renderTour(
  props: Partial<React.ComponentProps<typeof OnboardingTour>> = {},
) {
  return render(<OnboardingTour {...props} />);
}

/* ── Setup ───────────────────────────────────────────────────────────────── */

beforeEach(() => {
  // Start each test with a fresh localStorage (no completed key)
  localStorage.clear();

  // Stub scrollIntoView — not available in jsdom
  window.HTMLElement.prototype.scrollIntoView = vi.fn();

  // Stub getBoundingClientRect to return a plausible rect for target elements
  vi.spyOn(document, 'querySelector').mockImplementation((selector: string) => {
    // Return a mock element for tour targets; return null for anything else
    if (
      selector === '[data-tour="sidebar"]' ||
      selector === '[data-tour="projects"]' ||
      selector === '[data-tour="boq"]' ||
      selector === '[data-tour="costs"]' ||
      selector === '[data-tour="mode-toggle"]'
    ) {
      const el = document.createElement('div');
      el.getBoundingClientRect = () => ({
        top: 100,
        left: 50,
        width: 200,
        height: 48,
        right: 250,
        bottom: 148,
        x: 50,
        y: 100,
        toJSON: () => ({}),
      });
      el.scrollIntoView = vi.fn();
      return el;
    }
    return null;
  });

  // Use fake timers to control setTimeout used in positionForStep
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  localStorage.clear();
});

/* ── Tests ───────────────────────────────────────────────────────────────── */

describe('OnboardingTour', () => {
  /**
   * 1. Renders the first step correctly when localStorage key is absent
   */
  it('renders first step when onboarding not yet completed', () => {
    renderTour({ steps: TWO_STEPS });

    // Tooltip is visible
    expect(screen.getByTestId('onboarding-tooltip')).toBeInTheDocument();

    // First step title shown (i18n mock returns defaultValue; here key = title string)
    expect(screen.getByText('Step One')).toBeInTheDocument();
    expect(screen.getByText('Description one')).toBeInTheDocument();
  });

  /**
   * 2. Next button advances to step 2
   */
  it('advances to step 2 when Next is clicked', () => {
    renderTour({ steps: TWO_STEPS });

    // Step 1 is visible
    expect(screen.getByText('Step One')).toBeInTheDocument();

    // Click Next
    fireEvent.click(screen.getByTestId('onboarding-next'));

    // Flush the 150 ms setTimeout so spotlight repositions
    act(() => { vi.advanceTimersByTime(200); });

    // Step 2 is now visible
    expect(screen.getByText('Step Two')).toBeInTheDocument();
    expect(screen.queryByText('Step One')).not.toBeInTheDocument();
  });

  /**
   * 3. Previous button navigates back
   */
  it('goes back to step 1 when Previous is clicked on step 2', () => {
    renderTour({ steps: TWO_STEPS });

    // Go to step 2
    fireEvent.click(screen.getByTestId('onboarding-next'));
    act(() => { vi.advanceTimersByTime(200); });
    expect(screen.getByText('Step Two')).toBeInTheDocument();

    // Now click Prev
    fireEvent.click(screen.getByTestId('onboarding-prev'));
    act(() => { vi.advanceTimersByTime(200); });

    // Back to step 1
    expect(screen.getByText('Step One')).toBeInTheDocument();
  });

  /**
   * 4. Previous button is absent on the first step
   */
  it('does not show Previous button on the first step', () => {
    renderTour({ steps: TWO_STEPS });

    expect(screen.queryByTestId('onboarding-prev')).not.toBeInTheDocument();
  });

  /**
   * 5. Skip button closes the tour and writes localStorage key
   */
  it('skip button closes tour and marks onboarding complete', () => {
    renderTour({ steps: TWO_STEPS });
    expect(screen.getByTestId('onboarding-tooltip')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('onboarding-skip'));

    // Tour should be gone
    expect(screen.queryByTestId('onboarding-tooltip')).not.toBeInTheDocument();

    // localStorage key written
    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('true');
  });

  /**
   * 6. Finish button on the last step marks complete and closes tour
   */
  it('clicking Finish on the last step marks complete and closes tour', () => {
    renderTour({ steps: TWO_STEPS });

    // Advance to last step
    fireEvent.click(screen.getByTestId('onboarding-next'));
    act(() => { vi.advanceTimersByTime(200); });

    // Next button now says "Finish"
    const finishBtn = screen.getByTestId('onboarding-next');
    expect(finishBtn).toHaveAttribute('aria-label', 'Finish tour');

    fireEvent.click(finishBtn);

    // Tour gone
    expect(screen.queryByTestId('onboarding-tooltip')).not.toBeInTheDocument();

    // Marked complete
    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('true');
  });

  /**
   * 7. Does not render when localStorage key is already set
   */
  it('does not render when onboarding already completed', () => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true');

    renderTour({ steps: TWO_STEPS });

    expect(screen.queryByTestId('onboarding-tooltip')).not.toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-overlay')).not.toBeInTheDocument();
  });

  /**
   * 8. forceShow overrides the localStorage guard
   */
  it('renders even when completed if forceShow=true', () => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true');

    renderTour({ steps: TWO_STEPS, forceShow: true });

    expect(screen.getByTestId('onboarding-tooltip')).toBeInTheDocument();
  });

  /**
   * 9. Escape key closes the tour
   */
  it('closes tour and marks complete when Escape is pressed', () => {
    renderTour({ steps: TWO_STEPS });
    expect(screen.getByTestId('onboarding-tooltip')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByTestId('onboarding-tooltip')).not.toBeInTheDocument();
    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('true');
  });

  /**
   * 10. Step counter shows correct "Step X of Y" text
   */
  it('shows correct step counter on each step', () => {
    renderTour({ steps: THREE_STEPS });

    // Step 1 of 3
    expect(screen.getByTestId('onboarding-step-counter').textContent).toMatch(/1.*3/);

    // Advance to step 2
    fireEvent.click(screen.getByTestId('onboarding-next'));
    act(() => { vi.advanceTimersByTime(200); });
    expect(screen.getByTestId('onboarding-step-counter').textContent).toMatch(/2.*3/);

    // Advance to step 3
    fireEvent.click(screen.getByTestId('onboarding-next'));
    act(() => { vi.advanceTimersByTime(200); });
    expect(screen.getByTestId('onboarding-step-counter').textContent).toMatch(/3.*3/);
  });

  /**
   * 11. Previous button appears on step 2 (middle step)
   */
  it('shows Previous button when not on the first step', () => {
    renderTour({ steps: THREE_STEPS });

    // On step 1 — no Prev button
    expect(screen.queryByTestId('onboarding-prev')).not.toBeInTheDocument();

    // Move to step 2
    fireEvent.click(screen.getByTestId('onboarding-next'));
    act(() => { vi.advanceTimersByTime(200); });

    // Prev button now visible
    expect(screen.getByTestId('onboarding-prev')).toBeInTheDocument();
  });

  /**
   * 12. Default steps export includes 5 entries
   */
  it('DEFAULT_TOUR_STEPS has 5 steps covering sidebar/projects/boq/costs/mode-toggle', () => {
    expect(DEFAULT_TOUR_STEPS).toHaveLength(5);
    const targets = DEFAULT_TOUR_STEPS.map((s) => s.target);
    expect(targets).toContain('[data-tour="sidebar"]');
    expect(targets).toContain('[data-tour="projects"]');
    expect(targets).toContain('[data-tour="boq"]');
    expect(targets).toContain('[data-tour="costs"]');
    expect(targets).toContain('[data-tour="mode-toggle"]');
  });
});
