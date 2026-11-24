import { describe, expect, it } from 'vitest';
import {
  findFreeSpot,
  fitsOnMount,
  fitsOnRail,
  freeModules,
  freeRatio,
  requiredWidth,
  snapMm,
  snapStart,
  validatePanel,
} from './geometry';
import { device, panel, product } from './testkit';

const rail = { id: 1, rowIndex: 0, capacity: 12 };

describe('requiredWidth', () => {
  it('rounds fractional widths up and ignores float noise', () => {
    expect(requiredWidth(1)).toBe(1);
    expect(requiredWidth(0.5)).toBe(1);
    expect(requiredWidth(2.0000000001)).toBe(2);
    expect(requiredWidth(3.5)).toBe(4);
    expect(requiredWidth(0)).toBe(0);
  });
});

describe('fitsOnRail', () => {
  const devs = [device('a', { railId: 1, start: 2, width: 3 })];
  it('accepts free slots incl. exact edges', () => {
    expect(fitsOnRail(devs, rail, 0, 2)).toBe(true); // touches device start
    expect(fitsOnRail(devs, rail, 5, 7)).toBe(true); // exactly to the rail end
    expect(fitsOnRail(devs, rail, 11, 1)).toBe(true);
  });
  it('rejects overlap, overflow and invalid values', () => {
    expect(fitsOnRail(devs, rail, 1, 2)).toBe(false);
    expect(fitsOnRail(devs, rail, 4, 1)).toBe(false);
    expect(fitsOnRail(devs, rail, 5, 8)).toBe(false);
    expect(fitsOnRail(devs, rail, 12, 1)).toBe(false);
    expect(fitsOnRail(devs, rail, -1, 1)).toBe(false);
    expect(fitsOnRail(devs, rail, 0.5, 1)).toBe(false);
    expect(fitsOnRail(devs, rail, 0, 0)).toBe(false);
  });
  it('ignores the moved device itself', () => {
    expect(fitsOnRail(devs, rail, 3, 3, new Set(['a']))).toBe(true);
  });
  it('only considers the same rail', () => {
    const other = [device('b', { railId: 2, start: 0, width: 12 })];
    expect(fitsOnRail(other, rail, 0, 12)).toBe(true);
  });
});

describe('snapStart', () => {
  const devs = [device('a', { railId: 1, start: 4, width: 2 })];
  it('rounds to the nearest module and clamps into the rail', () => {
    expect(snapStart([], rail, 2.4, 1)).toBe(2);
    expect(snapStart([], rail, 2.6, 1)).toBe(3);
    expect(snapStart([], rail, -3, 2)).toBe(0);
    expect(snapStart([], rail, 99, 3)).toBe(9);
  });
  it('returns null when the snapped slot is occupied', () => {
    expect(snapStart(devs, rail, 4.2, 1)).toBeNull();
    expect(snapStart(devs, rail, 3.6, 2)).toBeNull();
    expect(snapStart(devs, rail, 6, 1)).toBe(6);
  });
});

describe('findFreeSpot / free space', () => {
  const p = panel({
    rails: [
      { id: 1, rowIndex: 0, capacity: 4 },
      { id: 2, rowIndex: 1, capacity: 4 },
    ],
    devices: [device('a', { railId: 1, start: 0, width: 3 })],
  });
  it('scans rails top to bottom', () => {
    expect(findFreeSpot(p, 1)).toEqual({ railId: 1, start: 3 });
    expect(findFreeSpot(p, 2)).toEqual({ railId: 2, start: 0 });
    expect(findFreeSpot(p, 5)).toBeNull();
  });
  it('computes free modules and ratio', () => {
    expect(freeModules(p)).toBe(5);
    expect(freeRatio(p)).toBeCloseTo(5 / 8);
    expect(freeRatio(panel({ rails: [] }))).toBe(1);
  });
});

describe('mounting panel', () => {
  const p = panel({
    area: { width: 200, height: 300 },
    devices: [device('c', { railId: null, start: null, x: 0, y: 0, w: 50, h: 80 })],
  });
  it('snaps to a 5 mm grid', () => {
    expect(snapMm(12.4)).toBe(10);
    expect(snapMm(12.5)).toBe(15);
  });
  it('allows adjacent and edge-touching rectangles, rejects overlap/outside', () => {
    expect(fitsOnMount(p, { x: 50, y: 0, w: 50, h: 80 })).toBe(true);
    expect(fitsOnMount(p, { x: 150, y: 220, w: 50, h: 80 })).toBe(true);
    expect(fitsOnMount(p, { x: 49, y: 79, w: 50, h: 80 })).toBe(false);
    expect(fitsOnMount(p, { x: 151, y: 0, w: 50, h: 80 })).toBe(false);
    expect(fitsOnMount(p, { x: 0, y: 0, w: 50, h: 80 }, new Set(['c']))).toBe(true);
    expect(
      fitsOnMount(panel({ area: { width: null, height: null } }), { x: 0, y: 0, w: 1, h: 1 }),
    ).toBe(false);
  });
});

describe('validatePanel (mirror of server rules)', () => {
  const products = new Map([
    [1, product({ id: 1, modules: '1.0' })],
    [3, product({ id: 3, modules: '3.0' })],
    [9, product({ id: 9, modules: '0.0', din_mountable: false })],
  ]);
  const codes = (devices: ReturnType<typeof device>[], area = { width: 200, height: 300 }) =>
    validatePanel(panel({ devices, area }), products).map((i) => i.code);

  it('accepts a valid layout', () => {
    expect(
      codes([
        device('a', { productId: 3, railId: 1, start: 0, width: 3 }),
        device('b', { productId: 1, railId: 1, start: 3, width: 1 }),
        device('m', {
          productId: 9,
          railId: null,
          start: null,
          width: 0,
          x: 10,
          y: 10,
          w: 50,
          h: 50,
        }),
      ]),
    ).toEqual([]);
  });
  it('flags collisions, bounds, width mismatch', () => {
    expect(
      codes([
        device('a', { productId: 3, railId: 1, start: 0, width: 3 }),
        device('b', { productId: 1, railId: 1, start: 2, width: 1 }),
      ]),
    ).toEqual(['collision']);
    expect(codes([device('a', { productId: 1, railId: 1, start: 12, width: 1 })])).toEqual([
      'out_of_bounds',
    ]);
    expect(codes([device('a', { productId: 3, railId: 1, start: 0, width: 2 })])).toEqual([
      'width_mismatch',
    ]);
  });
  it('flags DIN / non-DIN misuse and unknown rails', () => {
    expect(codes([device('a', { productId: 9, railId: 1, start: 0, width: 1 })])).toContain(
      'non_din_on_rail',
    );
    expect(
      codes([
        device('a', { productId: 1, railId: null, start: null, width: 0, x: 0, y: 0, w: 5, h: 5 }),
      ]),
    ).toEqual(['din_off_rail']);
    expect(codes([device('a', { productId: 1, railId: 99, start: 0, width: 1 })])).toEqual([
      'unknown_rail',
    ]);
  });
  it('flags mounting-panel problems', () => {
    const m = (x: number, y: number) =>
      device(`m${x}`, { productId: 9, railId: null, start: null, width: 0, x, y, w: 50, h: 50 });
    expect(codes([m(180, 0)])).toEqual(['out_of_bounds']);
    expect(codes([m(0, 0), m(10, 10)])).toEqual(['collision']);
    expect(
      codes([m(0, 0)], { width: null as unknown as number, height: null as unknown as number }),
    ).toEqual(['no_mounting_panel']);
    expect(codes([device('g', { productId: 9, railId: null, start: null, width: 0 })])).toEqual([
      'missing_geometry',
    ]);
  });
});
