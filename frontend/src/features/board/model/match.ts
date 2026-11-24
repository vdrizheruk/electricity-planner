import type { Group, Product } from './types';

const TIERS = ['eco', 'mid', 'premium'] as const;

export function tierOrder(tier: string): string[] {
  const base =
    Math.max(TIERS.indexOf(tier as (typeof TIERS)[number]), 0) || (tier === 'eco' ? 0 : 1);
  return [...TIERS].sort(
    (a, b) =>
      Math.abs(TIERS.indexOf(a) - base) - Math.abs(TIERS.indexOf(b) - base) ||
      TIERS.indexOf(a) - TIERS.indexOf(b),
  );
}

/** The breaker for a consumer group that the calculation selected (client-side lookup). */
export function breakerFor(group: Group, products: Product[], tier: string): Product | null {
  if (group.breaker_a === null) return null;
  const poles = group.assigned_phase === '3ph' ? 3 : 1;
  const base = products.filter(
    (p) => p.category.code === 'mcb' && Number(p.rated_a) === group.breaker_a && p.poles === poles,
  );
  const exact = base.filter((p) => p.curve === group.curve);
  const pool = exact.length > 0 ? exact : base;
  for (const t of tierOrder(tier)) {
    const found = pool
      .filter((p) => p.tier === t)
      .sort((a, b) => Number(a.price) - Number(b.price) || a.sku.localeCompare(b.sku))[0];
    if (found) return found;
  }
  return null;
}

/** Short caption printed on the device block. */
export function shortName(p: Product): string {
  const rated = p.rated_a !== null ? String(Number(p.rated_a)) : '';
  switch (p.category.code) {
    case 'mcb':
      return `${p.curve}${rated}`;
    case 'rcd':
      return `${rated}A ${p.leakage_ma ?? ''}`.trim() + 'мА';
    case 'rcbo':
      return `${p.curve}${rated} ${p.leakage_ma ?? ''}мА`;
    case 'main_switch':
      return `QS ${rated}A`;
    case 'spd':
      return 'УЗИП';
    case 'voltage_relay':
    case 'phase_relay':
      return 'Реле';
    case 'meter':
      return 'Счётч.';
    case 'contactor':
      return `KM ${rated}A`;
    default:
      return p.sku.length > 10 ? `${p.sku.slice(0, 9)}…` : p.sku;
  }
}

export const CATEGORY_COLOR: Record<string, string> = {
  mcb: '#dbeafe',
  rcd: '#fde68a',
  rcbo: '#fed7aa',
  spd: '#fecaca',
  main_switch: '#e9d5ff',
  voltage_relay: '#bbf7d0',
  phase_relay: '#bbf7d0',
  meter: '#e2e8f0',
  contactor: '#c7d2fe',
  ats: '#c7d2fe',
  timer: '#bbf7d0',
};

export function colorOf(p: Product | undefined): string {
  return (p && CATEGORY_COLOR[p.category.code]) ?? '#f1f5f9';
}
