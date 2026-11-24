import { describe, expect, it } from 'vitest';
import { buildDiagram, designations } from './diagram';
import { labelItems, labelsToSvg } from './labels';
import { createBoardStore } from './store';
import { device, panel, product } from './testkit';
import type { Group, PanelModel, Product } from './types';

const cat = (id: number, code: string, extra: Partial<Product> = {}) =>
  product({
    id,
    category: { id, code, name_ru: code, name_uk: code } as Product['category'],
    ...extra,
  });

const P = [
  cat(1, 'mcb'),
  cat(2, 'rcd', { leakage_ma: 30, poles: 2 }),
  cat(3, 'main_switch'),
  cat(4, 'spd'),
  cat(5, 'rcd', { leakage_ma: 300, poles: 4 }),
  cat(6, 'rcbo'),
  cat(7, 'contactor'),
];
const products = new Map(P.map((p) => [p.id, p]));
const groups = [
  { id: 10, name: 'Кухня', power_w: 3000, cable_mm2: '2.50' },
  { id: 11, name: 'Свет', power_w: 400, cable_mm2: '1.50' },
] as unknown as Group[];

function board(): PanelModel {
  return panel({
    devices: [
      device('main', { productId: 3, start: 0 }),
      device('spd', { productId: 4, start: 1 }),
      device('rcd1', { productId: 2, start: 2 }),
      device('q1', { productId: 1, start: 3, groupId: 10 }),
      device('q2', { productId: 1, start: 4, groupId: 11 }),
      device('rcd2', { productId: 2, start: 5 }),
      device('q3', { productId: 1, start: 6 }),
      device('fb', { productId: 6, start: 7 }),
    ],
  });
}

describe('designations', () => {
  it('numbers per prefix in reading order', () => {
    const t = designations(board(), products);
    expect(t.get('main')).toBe('QS1');
    expect(t.get('rcd1')).toBe('QD1');
    expect(t.get('rcd2')).toBe('QD2');
    expect(t.get('q1')).toBe('QF1');
    expect(t.get('q3')).toBe('QF3');
    expect(t.get('fb')).toBe('QFD1');
  });

  it('reads rails top to bottom regardless of array order', () => {
    const p = panel({
      rails: [
        { id: 1, rowIndex: 0, capacity: 12 },
        { id: 2, rowIndex: 1, capacity: 12 },
      ],
      devices: [
        device('b', { productId: 1, railId: 2, start: 0 }),
        device('a', { productId: 1, railId: 1, start: 5 }),
      ],
    });
    const t = designations(p, products);
    expect(t.get('a')).toBe('QF1');
    expect(t.get('b')).toBe('QF2');
  });

  it('treats a 300 mA RCD as QD too', () => {
    const p = panel({ devices: [device('f', { productId: 5 })] });
    expect(designations(p, products).get('f')).toBe('QD1');
  });
});

describe('main breaker', () => {
  it('an unbound 2P breaker at the head belongs to the input chain', () => {
    const main = cat(20, 'mcb', { poles: 2 });
    const pm = new Map([...products, [20, main]]);
    const p = panel({
      devices: [
        device('m', { productId: 20, start: 0, width: 2 }),
        device('r', { productId: 2, start: 2 }),
        device('q', { productId: 1, start: 3, groupId: 10 }),
      ],
    });
    const d = buildDiagram(p, pm, groups);
    expect(d.edges.some((e) => e.source === 'feeder' && e.target === 'm')).toBe(true);
    expect(d.edges.some((e) => e.source === 'm' && e.target === 'bus')).toBe(true);
    expect(d.edges.some((e) => e.source === 'bus' && e.target === 'r')).toBe(true);
  });
});

describe('buildDiagram', () => {
  const d = buildDiagram(board(), products, groups);
  const edge = (a: string, b: string) => d.edges.some((e) => e.source === a && e.target === b);

  it('chains feeder → main → spd → bus', () => {
    expect(edge('feeder', 'main')).toBe(true);
    expect(edge('main', 'spd')).toBe(true);
    expect(edge('spd', 'bus')).toBe(true);
  });

  it('hangs breakers under the RCD that precedes them', () => {
    expect(edge('bus', 'rcd1')).toBe(true);
    expect(edge('rcd1', 'q1')).toBe(true);
    expect(edge('rcd1', 'q2')).toBe(true);
    expect(edge('rcd2', 'q3')).toBe(true);
    expect(edge('bus', 'q1')).toBe(false);
  });

  it('puts an RCBO directly on the bus even after an RCD', () => {
    expect(edge('bus', 'fb')).toBe(true);
  });

  it('puts a breaker before any RCD on the bus', () => {
    const p = panel({
      devices: [device('a', { productId: 1, start: 0 }), device('r', { productId: 2, start: 1 })],
    });
    const dd = buildDiagram(p, products, groups);
    expect(dd.edges.some((e) => e.source === 'feeder' && e.target === 'bus')).toBe(true);
    expect(dd.edges.some((e) => e.source === 'bus' && e.target === 'a')).toBe(true);
  });

  it('shows group name and load on the node', () => {
    const n = d.nodes.find((x) => x.id === 'q1');
    expect(n?.title).toBe('Кухня');
    expect(n?.load).toBe('3000 Вт · 2.5 мм²');
    expect(n?.tag).toBe('QF1');
  });

  it('has one node per device plus feeder and bus and unique ids', () => {
    expect(d.nodes).toHaveLength(8 + 2);
    expect(new Set(d.nodes.map((n) => n.id)).size).toBe(d.nodes.length);
  });

  it('empty panel: feeder → bus only', () => {
    const e = buildDiagram(panel(), products, groups);
    expect(e.nodes.map((n) => n.id)).toEqual(['feeder', 'bus']);
    expect(e.edges).toHaveLength(1);
  });

  it('mounting-panel devices become "other" nodes on the bus', () => {
    const p = panel({
      devices: [
        device('k', {
          productId: 7,
          railId: null,
          start: null,
          width: 0,
          x: 0,
          y: 0,
          w: 50,
          h: 80,
        }),
      ],
    });
    const dd = buildDiagram(p, products, groups);
    expect(dd.nodes.find((n) => n.id === 'k')?.kind).toBe('other');
    expect(dd.edges.some((e) => e.source === 'bus' && e.target === 'k')).toBe(true);
  });
});

describe('two-way sync through the store', () => {
  function setup() {
    const s = createBoardStore();
    s.getState().load({ panels: [board()], products: P, groups });
    return s;
  }
  const diagramOf = (s: ReturnType<typeof setup>) => {
    const st = s.getState();
    return buildDiagram(st.panels[1] as PanelModel, st.products, st.groups);
  };

  it('removing a device on the board removes its node', () => {
    const s = setup();
    s.getState().removeDevices(['q2']);
    expect(diagramOf(s).nodes.some((n) => n.id === 'q2')).toBe(false);
  });

  it('binding a group on the diagram side updates the board model', () => {
    const s = setup();
    expect(s.getState().setGroup('q3', 10).ok).toBe(true);
    expect(s.getState().panels[1]?.devices.find((d) => d.id === 'q3')?.groupId).toBe(10);
    expect(diagramOf(s).nodes.find((n) => n.id === 'q3')?.title).toBe('Кухня');
  });

  it('moving a device on the board re-parents it in the diagram', () => {
    const s = setup();
    s.getState().removeDevices(['fb']);
    // move q1 (after rcd1) to start=7 -> now follows rcd2
    expect(
      s.getState().moveDevices('q1', { kind: 'rail', panelId: 1, railId: 1, start: 7 }).ok,
    ).toBe(true);
    const d = diagramOf(s);
    expect(d.edges.some((e) => e.source === 'rcd2' && e.target === 'q1')).toBe(true);
    expect(d.edges.some((e) => e.source === 'rcd1' && e.target === 'q1')).toBe(false);
  });

  it('undo restores the diagram', () => {
    const s = setup();
    const before = JSON.stringify(diagramOf(s));
    s.getState().removeDevices(['q1']);
    s.getState().undo();
    expect(JSON.stringify(diagramOf(s))).toBe(before);
  });
});

describe('labels', () => {
  it('one sticker per device with tag and group', () => {
    const items = labelItems(board(), products, groups);
    expect(items).toHaveLength(8);
    const q1 = items.find((i) => i.tag === 'QF1');
    expect(q1?.line2).toBe('Кухня · 3000 Вт · 2.5 мм²');
  });

  it('svg escapes text and contains every tag', () => {
    const { svg } = labelsToSvg([{ tag: 'QF1', line1: 'C16', line2: 'A<&>"B' }], 'Щит');
    expect(svg).toContain('A&lt;&amp;&gt;&quot;B');
    expect(svg).toContain('data-label="QF1"');
  });
});
