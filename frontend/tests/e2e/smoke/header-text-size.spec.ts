/**
 * Smoke - the top bar at a larger text size.
 *
 * With the browser or the operating system set to 125% or 150% text, every
 * rem in the header grows while the viewport does not, and the pack chip in
 * the middle column used to keep its full width and paint over the project
 * picker ("No regional pack" running into the project name). The chip now
 * truncates inside its column. jsdom does no layout, so this has to be a real
 * browser: the root font size is raised the way a text-size setting raises
 * it, and the two boxes must not overlap.
 */
import { test, expect } from '../fixtures';
import { gotoModule } from '../helpers';

const SCALES = [1.25, 1.5];
const WIDTHS = [1280, 1440];

for (const width of WIDTHS) {
  for (const scale of SCALES) {
    test(`@smoke top bar does not overlap at ${scale * 100}% text, ${width}px`, async ({ authedPage }) => {
      await authedPage.setViewportSize({ width, height: 800 });
      await gotoModule(authedPage, 'dashboard');
      await authedPage.evaluate((s) => {
        document.documentElement.style.fontSize = `${16 * s}px`;
      }, scale);

      const picker = authedPage.getByTestId('header-project-picker');
      const chip = authedPage.getByTestId('active-pack-chip');
      await expect(picker).toBeVisible();
      await expect(chip).toBeAttached();

      const boxes = await authedPage.evaluate(() => {
        const rect = (sel: string) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
        };
        // The picker's button can be wider than its shrinking wrapper, so its
        // painted right edge is the furthest right of the wrapper and all it holds.
        const pickerEl = document.querySelector('[data-testid="header-project-picker"]');
        const picker = pickerEl
          ? [pickerEl, ...Array.from(pickerEl.querySelectorAll('*'))]
              .map((el) => el.getBoundingClientRect())
              .filter((r) => r.width > 0)
              .reduce(
                (acc, r) => ({ ...acc, left: Math.min(acc.left, r.left), right: Math.max(acc.right, r.right) }),
                { left: Infinity, right: -Infinity, top: 0, bottom: 0 },
              )
          : null;
        return {
          picker,
          chip: rect('[data-testid="active-pack-chip"]'),
          column: rect('[data-testid="header-pack-column"]'),
        };
      });
      const { picker: p, chip: c, column: col } = boxes;
      expect(p && c && col).toBeTruthy();
      // The painted part of the chip is its box clipped to its column.
      const paintedLeft = Math.max(c!.left, col!.left);
      const paintedRight = Math.min(c!.right, col!.right);
      if (paintedRight > paintedLeft) {
        expect(
          paintedLeft,
          `chip starts at ${Math.round(paintedLeft)}px, inside the project picker that ends at ${Math.round(p!.right)}px`,
        ).toBeGreaterThanOrEqual(p!.right - 1);
      }
    });
  }
}
