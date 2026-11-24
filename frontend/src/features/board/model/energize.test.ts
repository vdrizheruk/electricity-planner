import { describe, expect, it } from 'vitest';
import type { SimResult } from '../../../api/endpoints';
import { buildDiagram } from './diagram';
import { deviceStates, energize } from './energize';
import { device, panel, product } from './testkit';
import type { Group, Product } from './types';

const cat = (id: number, code: string, extra: Partial<Product> = {}) =>
  product({
    id,
    category: { id, code, name_ru: code, name_uk: code } as Product['category'],
    ...extra,
  });
const products = new Map(
  [cat(1, 'mcb'), cat(2, 'rcd', { leakage_ma: 30, poles: 2 }), cat(3, 'main_switch')].map((p) => [
    p.id,
    p,
  ]),
);
const groups = [
  { id: 10, name: 'Кухня', power_w: 3000, cable_mm2: '2.50' },
  { id: 11, name: 'Свет', power_w: 400, cable_mm2: '1.50' },
] as unknown as Group[];

const p = panel({
  devices: [
    device('main', { productId: 3, start: 0 }),
    device('rcd1', { productId: 2, start: 1 }),
    device('q1', { productId: 1, start: 2, groupId: 10 }),
    device('q2', { productId: 1, start: 3, groupId: 11 }),
  ],
});
const diagram = buildDiagram(p, products, groups);

function sim(over: Partial<SimResult> & { g10?: boolean; g11?: boolean }): SimResult {
  const { g10 = true, g11 = true, ...rest } = over;
  const g = (id: number, powered: boolean) => ({
    id,
    name: String(id),
    backed_up: false,
    powered,
    source: powered ? 'grid' : null,
    reason: powered ? '' : 'not_backed_up',
    phase: 'L1',
    power_w: 100,
  });
  return {
    backup_source: null,
    main_source: 'grid',
    ats_state: 'grid',
    groups: [g(10, g10), g(11, g11)],
    sources: [],
    findings: [],
    interruption_s: null,
    pv_w: 0,
    grid_import_w: 0,
    grid_export_w: 0,
    battery_net_w: 0,
    autonomy_h: null,
    powered_w: 0,
    dark_w: 0,
    ...rest,
  } as SimResult;
}

describe('energize', () => {
  it('is empty without a simulation', () => {
    expect(energize(p, diagram, null).size).toBe(0);
  });

  it('powers the whole chain when all groups are live', () => {
    const e = energize(p, diagram, sim({}));
    for (const n of diagram.nodes) expect(e.get(n.id)?.powered).toBe(true);
    expect(e.get('feeder')?.source).toBe('grid');
  });

  it('darkens only the dead group; RCD and bus stay live while one group lives', () => {
    const e = energize(p, diagram, sim({ g10: false }));
    expect(e.get('q1')).toMatchObject({ powered: false, reason: 'not_backed_up' });
    expect(e.get('q2')?.powered).toBe(true);
    expect(e.get('rcd1')?.powered).toBe(true);
    expect(e.get('feeder')?.powered).toBe(true);
  });

  it('darkens the chain when every group is dark', () => {
    const e = energize(p, diagram, sim({ g10: false, g11: false }));
    for (const n of diagram.nodes) expect(e.get(n.id)?.powered).toBe(false);
    expect(e.get('feeder')?.reason).toBe('not_backed_up');
  });

  it('maps devices only', () => {
    const d = deviceStates(p, diagram, sim({ g11: false }));
    expect([...d.keys()].sort()).toEqual(['main', 'q1', 'q2', 'rcd1']);
    expect(d.get('q2')?.powered).toBe(false);
  });

  it('follows the backup source on the backup panel without groups', () => {
    const bp = panel({ kind: 'backup', devices: [device('a', { productId: 3 })] });
    const d = buildDiagram(bp, products, []);
    expect(energize(bp, d, sim({ backup_source: 'generator' })).get('a')).toMatchObject({
      powered: true,
      source: 'generator',
    });
    expect(energize(bp, d, sim({ backup_source: null })).get('a')?.powered).toBe(false);
  });

  it('follows PV on the DC panel', () => {
    const dp = panel({ kind: 'dc', devices: [device('a', { productId: 3 })] });
    const d = buildDiagram(dp, products, []);
    expect(energize(dp, d, sim({ pv_w: 3000 })).get('a')?.source).toBe('pv');
    expect(energize(dp, d, sim({ pv_w: 0 })).get('a')?.powered).toBe(false);
  });
});
