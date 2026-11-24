import { describe, expect, it } from 'vitest';
import { buildBom, formatUah, toCents } from './bom';
import { device, panel, product } from './testkit';

describe('toCents / formatUah', () => {
  it('parses decimal strings exactly', () => {
    expect(toCents('0')).toBe(0);
    expect(toCents('105.00')).toBe(10500);
    expect(toCents('12.5')).toBe(1250);
    expect(toCents('0.07')).toBe(7);
    expect(toCents('1234567.89')).toBe(123456789);
    expect(toCents('19.99')).toBe(1999); // 19.99 * 100 = 1998.9999999999998 in floats
    expect(toCents('-3.20')).toBe(-320);
  });
  it('rejects garbage', () => {
    expect(() => toCents('abc')).toThrow();
    expect(() => toCents('')).toThrow();
  });
  it('formats with thousands separators and comma', () => {
    expect(formatUah(123456789)).toBe('1 234 567,89 ₴');
    expect(formatUah(5)).toBe('0,05 ₴');
    expect(formatUah(-1050)).toBe('-10,50 ₴');
  });
});

describe('buildBom', () => {
  const a = product({ id: 1, price: '105.50', sku: 'A' });
  const b = product({
    id: 2,
    price: '19.99',
    sku: 'B',
    brand: { id: 2, name: 'IEK', slug: 'iek', tier: 'eco' },
  });
  const enc = product({ id: 3, price: '1000.00', sku: 'ENC' });
  const products = new Map([a, b, enc].map((p) => [p.id, p]));

  it('aggregates quantities per product and sums exactly', () => {
    const p1 = panel({
      id: 1,
      name: 'ГРЩ',
      enclosureId: 3,
      devices: [
        device('1', { productId: 1 }),
        device('2', { productId: 1, start: 1 }),
        device('3', { productId: 2, start: 2 }),
      ],
    });
    const p2 = panel({ id: 2, name: 'Этаж', devices: [device('4', { productId: 2 })] });
    const bom = buildBom([p1, p2], products);
    expect(bom.panels[0]!.lines.map((l) => [l.sku, l.qty])).toEqual([
      ['A', 2],
      ['ENC', 1],
      ['B', 1],
    ]);
    expect(bom.panels[0]!.totalCents).toBe(2 * 10550 + 100000 + 1999);
    expect(bom.panels[1]!.totalCents).toBe(1999);
    const lineB = bom.lines.find((l) => l.sku === 'B')!;
    expect(lineB).toMatchObject({ qty: 2, unitCents: 1999, totalCents: 3998 });
    expect(bom.boardsCents).toBe(2 * 10550 + 100000 + 3998);
    expect(bom.solarCents).toBe(0);
    expect(bom.totalCents).toBe(bom.boardsCents + bom.solarCents);
  });

  it('is empty for empty panels and ignores unknown products', () => {
    expect(buildBom([panel()], products).totalCents).toBe(0);
    const p = panel({ devices: [device('x', { productId: 999 })] });
    expect(buildBom([p], products).lines).toEqual([]);
  });
});
