import { describe, expect, it, vi } from 'vitest';
import { buildDiagram } from './diagram';
import { createPositionsSaver } from './positionsSaver';
import { createBoardStore } from './store';
import { device, panel, product } from './testkit';
import type { Group, PanelModel, Product } from './types';
import { buildWires, PHASE_COLOR, railTop, ROW_PITCH, WIRE_COLOR, wiresToSvg } from './wires';

const cat = (id: number, code: string, extra: Partial<Product> = {}) =>
  product({
    id,
    category: { id, code, name_ru: code, name_uk: code } as Product['category'],
    ...extra,
  });
const P = [
  cat(1, 'mcb'),
  cat(2, 'rcd', { leakage_ma: 30, poles: 2 }),
  cat(3, 'main_switch', { poles: 2 }),
  cat(6, 'rcbo', { poles: 2 }),
];
const products = new Map(P.map((p) => [p.id, p]));
const groups = [{ id: 10, name: 'Кухня', power_w: 3000, cable_mm2: '2.50' }] as unknown as Group[];

const two = (): PanelModel =>
  panel({
    rails: [
      { id: 1, rowIndex: 0, capacity: 12 },
      { id: 2, rowIndex: 1, capacity: 12 },
    ],
    devices: [
      device('main', { productId: 3, start: 0, width: 2 }),
      device('rcd', { productId: 2, start: 2, width: 2 }),
      device('q1', { productId: 1, start: 4, groupId: 10 }),
      device('q2', { productId: 1, railId: 2, start: 0, groupId: 10 }),
    ],
  });

describe('buildWires', () => {
  const ws = buildWires(two(), products, groups);
  const kinds = (k: string) => ws.wires.filter((w) => w.kind === k);

  it('uses the standard colours: phase red, neutral blue, earth yellow', () => {
    expect(WIRE_COLOR).toEqual({ L: '#dc2626', N: '#2563eb', PE: '#eab308' });
  });

  it('has an L wire for every device-to-device link of the diagram', () => {
    const d = buildDiagram(two(), products, groups);
    const links = d.edges.filter((e) => e.source !== 'feeder' && e.target !== 'bus');
    for (const e of links) expect(ws.wires.some((w) => w.id === `L:${e.id}`)).toBe(true);
  });

  it('wires start/end exactly at device terminals (no free-floating ends)', () => {
    const l =
      ws.wires.find((w) => w.id === 'L:main>bus') ?? ws.wires.find((w) => w.id.startsWith('L:'));
    expect(l).toBeTruthy();
    for (const w of ws.wires.filter((x) => x.id.startsWith('L:'))) {
      const first = w.points[0]!;
      const last = w.points[w.points.length - 1]!;
      expect(first.x).toBeGreaterThanOrEqual(0);
      expect(last.y).toBeGreaterThanOrEqual(railTop(0));
    }
  });

  it('gives neutral to RCD, RCBO and 2P devices only', () => {
    const ids = kinds('N').map((w) => w.id);
    expect(ids).toContain('N:main');
    expect(ids).toContain('N:rcd');
    expect(ids).not.toContain('N:q1');
  });

  it('fans out L/N/PE for every bound breaker', () => {
    for (const id of ['q1', 'q2']) {
      for (const k of ['L', 'N', 'PE']) {
        expect(ws.wires.some((w) => w.id === `out:${k}:${id}`)).toBe(true);
      }
    }
    expect(ws.wires.some((w) => w.id === 'out:L:rcd')).toBe(false);
  });

  it('has N and PE busbars under every rail', () => {
    expect(ws.bars.filter((b) => b.kind === 'N')).toHaveLength(2);
    expect(ws.bars.filter((b) => b.kind === 'PE')).toHaveLength(2);
  });

  it('feeder wires of all three colours enter from above', () => {
    for (const k of ['L', 'N', 'PE']) {
      const w = ws.wires.find((x) => x.id === `in:${k}`);
      expect(w?.points[0]?.y).toBe(4);
    }
  });

  it('second rail wires sit one row pitch lower', () => {
    const q1 = ws.wires.find((w) => w.id === 'out:L:q1')!;
    const q2 = ws.wires.find((w) => w.id === 'out:L:q2')!;
    expect(q2.points[0]!.y - q1.points[0]!.y).toBe(ROW_PITCH);
  });

  it('empty panel has no wires and no bars', () => {
    const e = buildWires(panel({ rails: [] }), products, groups);
    expect(e.wires).toHaveLength(0);
    expect(e.bars).toHaveLength(0);
  });

  it('svg output contains each wire kind and contains no user text', () => {
    const svg = wiresToSvg(ws);
    expect(svg).toContain('data-wire="L"');
    expect(svg).toContain('data-wire="N"');
    expect(svg).toContain('data-wire="PE"');
    expect(svg).not.toContain('Кухня');
  });
});

describe('diagram positions', () => {
  it('manual positions override the automatic layout', () => {
    const p = { ...two(), diagramPositions: { q1: { x: 500, y: 400 } } };
    const n = buildDiagram(p, products, groups).nodes.find((x) => x.id === 'q1');
    expect(n).toMatchObject({ x: 500, y: 400 });
  });

  it('store keeps positions out of undo history and resets them', () => {
    const s = createBoardStore();
    s.getState().load({ panels: [two()], products: P, groups });
    s.getState().setNodePosition(1, 'q1', { x: 1, y: 2 });
    expect(s.getState().panels[1]?.diagramPositions.q1).toEqual({ x: 1, y: 2 });
    expect(s.getState().past).toHaveLength(0);
    s.getState().resetNodePositions(1);
    expect(s.getState().panels[1]?.diagramPositions).toEqual({});
  });
});

describe('positions saver', () => {
  it('debounces, uses server ids and drops deleted devices', async () => {
    vi.useFakeTimers();
    const s = createBoardStore();
    const pm = two();
    pm.devices = pm.devices.map((d) => (d.id === 'q1' ? { ...d, serverId: 77 } : d));
    s.getState().load({ panels: [pm], products: P, groups });
    const save = vi.fn(async () => undefined);
    const saver = createPositionsSaver(s, save, 100);
    s.getState().setNodePosition(1, 'q1', { x: 1, y: 1 });
    s.getState().setNodePosition(1, 'q1', { x: 2, y: 2 });
    s.getState().setNodePosition(1, 'bus', { x: 3, y: 3 });
    s.getState().setNodePosition(1, 'q2', { x: 4, y: 4 }); // unsaved device: not persisted yet
    s.getState().setNodePosition(1, 'ghost', { x: 5, y: 5 }); // no such device
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(150);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith(1, { s77: { x: 2, y: 2 }, bus: { x: 3, y: 3 } });
    saver.stop();
    vi.useRealTimers();
  });
});

describe('3-phase colours', () => {
  const g3 = [
    { id: 10, name: 'A', power_w: 2000, cable_mm2: '2.50', assigned_phase: 'L2' },
    { id: 11, name: 'B', power_w: 2000, cable_mm2: '2.50', assigned_phase: 'L3' },
    { id: 12, name: 'Плита', power_w: 9000, cable_mm2: '6.00', assigned_phase: '3ph' },
  ] as unknown as Group[];
  const p3 = cat(9, 'mcb', { poles: 3 });
  const pm = new Map([...products, [9, p3]]);
  const board3 = (): PanelModel =>
    panel({
      devices: [
        device('main', { productId: 3, start: 0, width: 2 }),
        device('qa', { productId: 1, start: 2, groupId: 10 }),
        device('qb', { productId: 1, start: 3, groupId: 11 }),
        device('qc', { productId: 9, start: 4, width: 3, groupId: 12 }),
      ],
    });
  const ws = buildWires(board3(), pm, g3, true);
  const out = (id: string) => ws.wires.filter((w) => w.id.startsWith(`out:L:${id}`));

  it('uses IEC 60445 colours: L1 brown, L2 black, L3 grey', () => {
    expect(PHASE_COLOR).toEqual({ L1: '#92400e', L2: '#111827', L3: '#9ca3af' });
  });

  it('single-phase group is drawn in its phase colour', () => {
    expect(out('qa').map((w) => w.phase)).toEqual(['L2']);
    expect(out('qa')[0]?.color).toBe(PHASE_COLOR.L2);
    expect(out('qb')[0]?.color).toBe(PHASE_COLOR.L3);
  });

  it('three-phase group gets three parallel wires in three colours', () => {
    const w = out('qc');
    expect(w.map((x) => x.phase)).toEqual(['L1', 'L2', 'L3']);
    const xs = w.map((x) => x.points[1]!.x);
    expect(new Set(xs).size).toBe(3);
  });

  it('feeder brings all three phases', () => {
    expect(ws.wires.filter((w) => w.id.startsWith('in:L')).map((w) => w.phase)).toEqual([
      'L1',
      'L2',
      'L3',
    ]);
  });

  it('single-phase project keeps red and ignores group phases', () => {
    const w = buildWires(board3(), pm, g3, false);
    expect(w.wires.every((x) => x.kind !== 'L' || x.color === WIRE_COLOR.L)).toBe(true);
    expect(w.wires.some((x) => x.phase)).toBe(false);
  });

  it('svg carries the phase colours', () => {
    const svg = wiresToSvg(ws);
    expect(svg).toContain(PHASE_COLOR.L1);
    expect(svg).toContain('data-phase="L3"');
  });
});
