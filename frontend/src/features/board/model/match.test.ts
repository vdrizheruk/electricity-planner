import { describe, expect, it } from 'vitest';
import { boardToSvg } from './exportSvg';
import { breakerFor, shortName, tierOrder } from './match';
import { device, panel, product } from './testkit';
import type { Group, Product } from './types';

const g = (over: Partial<Group>): Group =>
  ({ id: 1, name: 'Розетки', breaker_a: 16, curve: 'C', assigned_phase: 'L1', ...over }) as Group;

describe('tierOrder', () => {
  it('orders tiers by distance from the wanted one', () => {
    expect(tierOrder('mid')).toEqual(['mid', 'eco', 'premium']);
    expect(tierOrder('eco')).toEqual(['eco', 'mid', 'premium']);
    expect(tierOrder('premium')).toEqual(['premium', 'mid', 'eco']);
  });
});

describe('breakerFor', () => {
  const list = [
    product({ id: 1, rated_a: '16.00', curve: 'C', tier: 'eco', price: '50' }),
    product({ id: 2, rated_a: '16.00', curve: 'C', tier: 'eco', price: '40' }),
    product({ id: 3, rated_a: '16.00', curve: 'C', tier: 'premium', price: '150' }),
    product({ id: 4, rated_a: '16.00', curve: 'B', tier: 'mid', price: '90' }),
    product({ id: 5, rated_a: '16.00', curve: 'C', poles: 3, tier: 'mid', price: '300' }),
    product({ id: 6, rated_a: '25.00', curve: 'C', tier: 'mid', price: '90' }),
  ];
  it('picks the cheapest exact match inside the closest tier', () => {
    expect(breakerFor(g({}), list, 'eco')?.id).toBe(2);
    expect(breakerFor(g({}), list, 'premium')?.id).toBe(3);
  });
  it('falls back to another tier, then to another curve', () => {
    expect(breakerFor(g({}), list, 'mid')?.id).toBe(2); // no mid/C -> eco first
    expect(breakerFor(g({ curve: 'B' }), list, 'eco')?.id).toBe(4);
    expect(breakerFor(g({ curve: 'D' }), list, 'eco')?.id).toBe(2); // any curve
  });
  it('uses 3 poles for 3-phase groups and returns null when nothing matches', () => {
    expect(breakerFor(g({ assigned_phase: '3ph' }), list, 'mid')?.id).toBe(5);
    expect(breakerFor(g({ breaker_a: 40 }), list, 'mid')).toBeNull();
    expect(breakerFor(g({ breaker_a: null }), list, 'mid')).toBeNull();
  });
});

describe('shortName', () => {
  const cat = (code: Product['category']['code']) => ({ id: 1, code, name_ru: '', name_uk: '' });
  it('builds compact captions', () => {
    expect(shortName(product({ id: 1, rated_a: '16.00', curve: 'C' }))).toBe('C16');
    expect(
      shortName(product({ id: 1, category: cat('rcd'), rated_a: '40.00', leakage_ma: 30 })),
    ).toBe('40A 30мА');
    expect(
      shortName(
        product({ id: 1, category: cat('rcbo'), rated_a: '32.00', leakage_ma: 30, curve: 'C' }),
      ),
    ).toBe('C32 30мА');
    expect(shortName(product({ id: 1, category: cat('spd') }))).toBe('УЗИП');
    expect(
      shortName(product({ id: 1, category: cat('enclosure'), sku: 'VERY-LONG-SKU-123' })),
    ).toBe('VERY-LONG…');
  });
});

describe('boardToSvg', () => {
  const p1 = product({ id: 1 });
  const m = product({ id: 9, din_mountable: false, sku: 'A&B<1>' });
  const pan = panel({
    devices: [
      device('a', { start: 0, width: 1, groupId: 7 }),
      device('b', { start: 2, width: 2, label: 'Свет "кухня"' }),
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
    ],
  });
  const out = boardToSvg(pan, new Map([p1, m].map((p) => [p.id, p])), [
    { id: 7, name: 'Розетки & свет' } as Group,
  ]);
  it('renders a well-formed, escaped svg with every device', () => {
    expect(out.svg.startsWith('<svg')).toBe(true);
    expect(out.svg.endsWith('</svg>')).toBe(true);
    expect((out.svg.match(/data-device=/g) ?? []).length).toBe(3);
    expect(out.svg).toContain('Розетки &amp; свет');
    expect(out.svg).toContain('Свет &quot;кухня&quot;');
    expect(out.svg).toContain('A&amp;B&lt;1&gt;');
    expect(out.svg).not.toContain('A&B<1>');
    expect(out.width).toBeGreaterThan(400);
    expect(out.height).toBeGreaterThan(100);
  });
  it('rotates labels of single-module devices', () => {
    expect(out.svg).toContain('rotate(90');
  });
});
