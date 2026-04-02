// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  pixelDistance,
  toRealDistance,
  polygonAreaPixels,
  toRealArea,
  polygonPerimeterPixels,
  formatMeasurement,
  deriveScale,
  COMMON_SCALES,
} from './data/scale-helpers';

describe('scale-helpers', () => {
  describe('pixelDistance', () => {
    it('should calculate distance between two points', () => {
      expect(pixelDistance(0, 0, 3, 4)).toBe(5);
    });

    it('should return 0 for same point', () => {
      expect(pixelDistance(5, 5, 5, 5)).toBe(0);
    });

    it('should handle negative coordinates', () => {
      expect(pixelDistance(-3, 0, 0, 4)).toBe(5);
    });
  });

  describe('toRealDistance', () => {
    it('should convert pixel distance using scale', () => {
      const scale = { pixelsPerUnit: 100, unitLabel: 'm' };
      expect(toRealDistance(500, scale)).toBe(5);
    });

    it('should return 0 for zero scale', () => {
      const scale = { pixelsPerUnit: 0, unitLabel: 'm' };
      expect(toRealDistance(500, scale)).toBe(0);
    });
  });

  describe('polygonAreaPixels', () => {
    it('should calculate area of a square', () => {
      const points = [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ];
      expect(polygonAreaPixels(points)).toBe(10000);
    });

    it('should calculate area of a triangle', () => {
      const points = [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 50, y: 100 },
      ];
      expect(polygonAreaPixels(points)).toBe(5000);
    });

    it('should return 0 for less than 3 points', () => {
      expect(polygonAreaPixels([{ x: 0, y: 0 }])).toBe(0);
      expect(polygonAreaPixels([])).toBe(0);
    });
  });

  describe('toRealArea', () => {
    it('should convert pixel area using scale squared', () => {
      const scale = { pixelsPerUnit: 10, unitLabel: 'm' };
      // 10000 px² / (10 px/m)² = 100 m²
      expect(toRealArea(10000, scale)).toBe(100);
    });
  });

  describe('polygonPerimeterPixels', () => {
    it('should calculate perimeter of a square', () => {
      const points = [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ];
      expect(polygonPerimeterPixels(points)).toBe(400);
    });

    it('should return 0 for less than 2 points', () => {
      expect(polygonPerimeterPixels([{ x: 0, y: 0 }])).toBe(0);
    });
  });

  describe('formatMeasurement', () => {
    it('should format small values with 3 decimals', () => {
      expect(formatMeasurement(0.123, 'm')).toBe('0.123 m');
    });

    it('should format medium values with 2 decimals', () => {
      expect(formatMeasurement(12.345, 'm')).toBe('12.35 m');
    });

    it('should format large values with 1 decimal', () => {
      expect(formatMeasurement(1234.5, 'm')).toBe('1234.5 m');
    });

    it('should format zero', () => {
      expect(formatMeasurement(0, 'm')).toBe('0 m');
    });
  });

  describe('deriveScale', () => {
    it('should derive scale from known dimension', () => {
      const scale = deriveScale(200, 2); // 200 pixels = 2 meters
      expect(scale.pixelsPerUnit).toBe(100);
      expect(scale.unitLabel).toBe('m');
    });

    it('should handle zero inputs gracefully', () => {
      const scale = deriveScale(0, 2);
      expect(scale.pixelsPerUnit).toBe(1);
    });
  });

  describe('COMMON_SCALES', () => {
    it('should have standard architectural scales', () => {
      expect(COMMON_SCALES.length).toBeGreaterThan(5);
      expect(COMMON_SCALES.some((s) => s.label === '1:100')).toBe(true);
      expect(COMMON_SCALES.some((s) => s.label === '1:50')).toBe(true);
    });

    it('should have increasing ratios', () => {
      for (let i = 1; i < COMMON_SCALES.length; i++) {
        expect(COMMON_SCALES[i].ratio).toBeGreaterThan(COMMON_SCALES[i - 1].ratio);
      }
    });
  });
});

describe('TakeoffViewerModule', () => {
  // Lazy loaded component — test manifest registration
  it('should be registered in MODULE_REGISTRY', async () => {
    const { MODULE_REGISTRY } = await import('../_registry');
    const mod = MODULE_REGISTRY.find((m) => m.id === 'pdf-takeoff');
    expect(mod).toBeDefined();
    expect(mod!.name).toBe('PDF Takeoff Viewer');
    expect(mod!.routes[0].path).toBe('/takeoff-viewer');
  }, 15000);
});
