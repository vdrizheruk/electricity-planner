import { buildDiagram } from './diagram';
import { MODULE_PX, RAIL_HEIGHT_PX } from './geometry';
import type { Device, Group, PanelModel, Product } from './types';

/** Vertical space between rails: wiring channel + N and PE busbars. */
export const WIRE_GAP = 44;
export const ROW_PITCH = RAIL_HEIGHT_PX + WIRE_GAP;

export type WireKind = 'L' | 'N' | 'PE';

export const WIRE_COLOR: Record<WireKind, string> = {
  L: '#dc2626',
  N: '#2563eb',
  PE: '#eab308',
};
export const PE_STRIPE = '#16a34a';

export interface Pt {
  x: number;
  y: number;
}
export interface Wire {
  id: string;
  kind: WireKind;
  points: Pt[];
}
export interface Bar {
  id: string;
  kind: 'N' | 'PE';
  x: number;
  y: number;
  w: number;
}
export interface WireSet {
  wires: Wire[];
  bars: Bar[];
  width: number;
  height: number;
}

const BAR_H = 6;
const N_BAR_DY = 14;
const PE_BAR_DY = 26;
const TERM_MARGIN = 4;
const TRACKS = 3;

export function railTop(row: number): number {
  return WIRE_GAP + row * ROW_PITCH;
}

function hasN(p: Product | undefined): boolean {
  if (!p) return false;
  const c = p.category.code;
  return c === 'rcd' || c === 'rcbo' || c === 'voltage_relay' || (p.poles ?? 1) >= 2;
}

/**
 * Wiring of a board in the coordinate system of the rails column (first rail at y = WIRE_GAP).
 * L (phase, red) follows the single-line topology: feeder → input chain → busbar → RCD →
 * breakers. N (blue) goes from the N busbar to every device with a neutral terminal; every
 * outgoing group gets an L/N/PE core fan-out (red/blue/yellow-green). N and PE busbars run
 * under each rail.
 */
export function buildWires(
  panel: PanelModel,
  products: Map<number, Product>,
  groups: Group[],
): WireSet {
  const rails = [...panel.rails].sort((a, b) => a.rowIndex - b.rowIndex);
  const rowOf = new Map(rails.map((r, i) => [r.id, i]));
  const wires: Wire[] = [];
  const bars: Bar[] = [];
  const byId = new Map(panel.devices.map((d) => [d.id, d]));

  const onRail = (d: Device): boolean =>
    d.railId !== null && d.start !== null && rowOf.has(d.railId);
  const left = (d: Device): number => (d.start as number) * MODULE_PX;
  const top = (d: Device): number => railTop(rowOf.get(d.railId as number) as number);
  const inPt = (d: Device): Pt => ({ x: left(d) + TERM_MARGIN, y: top(d) + TERM_MARGIN });
  const outPt = (d: Device): Pt => ({
    x: left(d) + TERM_MARGIN,
    y: top(d) + RAIL_HEIGHT_PX - TERM_MARGIN,
  });

  rails.forEach((r, i) => {
    const y = railTop(i) + RAIL_HEIGHT_PX;
    const w = r.capacity * MODULE_PX;
    bars.push(
      { id: `N${r.id}`, kind: 'N', x: 0, y: y + N_BAR_DY, w },
      { id: `PE${r.id}`, kind: 'PE', x: 0, y: y + PE_BAR_DY, w },
    );
  });
  const nBarY = (d: Device) => top(d) + RAIL_HEIGHT_PX + N_BAR_DY + BAR_H / 2;
  const peBarY = (d: Device) => top(d) + RAIL_HEIGHT_PX + PE_BAR_DY + BAR_H / 2;

  const diagram = buildDiagram(panel, products, groups);
  const trackUse = new Map<number, number>();
  const nextTrack = (row: number): number => {
    const n = trackUse.get(row) ?? 0;
    trackUse.set(row, n + 1);
    return 4 + (n % TRACKS) * 3;
  };

  // The device that feeds the busbar (end of the input chain), if any.
  const busFeed = diagram.edges.find((e) => e.target === 'bus')?.source ?? 'feeder';
  const firstChain = diagram.edges.find((e) => e.source === 'feeder' && e.target !== 'bus')?.target;
  const resolve = (id: string): Device | null => {
    const key = id === 'bus' ? busFeed : id;
    return key === 'feeder' ? null : (byId.get(key) ?? null);
  };

  for (const e of diagram.edges) {
    const b = byId.get(e.target);
    if (!b || !onRail(b)) continue;
    const a = resolve(e.source);
    if (!a) continue; // from feeder: handled below
    if (!onRail(a)) continue;
    const row = rowOf.get(a.railId as number) as number;
    const chY = railTop(row) + RAIL_HEIGHT_PX + nextTrack(row);
    const p = outPt(a);
    const q = inPt(b);
    wires.push({
      id: `L:${e.id}`,
      kind: 'L',
      points: [p, { x: p.x, y: chY }, { x: q.x, y: chY }, q],
    });
  }

  // Feeder entering the first device of the input chain from above.
  const entry = firstChain ? byId.get(firstChain) : undefined;
  const head =
    entry && onRail(entry)
      ? entry
      : (diagram.edges.map((e) => byId.get(e.target)).find((d) => d && onRail(d)) ?? undefined);
  if (head && onRail(head)) {
    const q = inPt(head);
    wires.push({ id: 'in:L', kind: 'L', points: [{ x: q.x, y: 4 }, q] });
    wires.push({
      id: 'in:N',
      kind: 'N',
      points: [
        { x: q.x + 7, y: 4 },
        { x: q.x + 7, y: q.y },
      ],
    });
    wires.push({
      id: 'in:PE',
      kind: 'PE',
      points: [
        { x: q.x + 14, y: 4 },
        { x: q.x + 14, y: q.y },
      ],
    });
  }

  for (const d of panel.devices) {
    if (!onRail(d)) continue;
    const p = products.get(d.productId);
    if (hasN(p)) {
      const x = left(d) + d.width * MODULE_PX - TERM_MARGIN;
      wires.push({
        id: `N:${d.id}`,
        kind: 'N',
        points: [
          { x, y: nBarY(d) },
          { x, y: outPt(d).y },
        ],
      });
    }
    const code = p?.category.code;
    if (d.groupId !== null && (code === 'mcb' || code === 'rcbo')) {
      const exit = top(d) + ROW_PITCH - 3;
      const x0 = left(d) + TERM_MARGIN;
      wires.push(
        { id: `out:L:${d.id}`, kind: 'L', points: [outPt(d), { x: x0, y: exit }] },
        {
          id: `out:N:${d.id}`,
          kind: 'N',
          points: [
            { x: x0 + 6, y: nBarY(d) },
            { x: x0 + 6, y: exit },
          ],
        },
        {
          id: `out:PE:${d.id}`,
          kind: 'PE',
          points: [
            { x: x0 + 12, y: peBarY(d) },
            { x: x0 + 12, y: exit },
          ],
        },
      );
    }
  }

  const width = Math.max(...rails.map((r) => r.capacity), 0) * MODULE_PX;
  const height = WIRE_GAP + rails.length * ROW_PITCH;
  return { wires, bars, width, height };
}

const path = (pts: Pt[]): string =>
  pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x} ${p.y}`).join(' ');

/** SVG fragment for the wires and busbars; contains only numbers and constants. */
export function wiresToSvg(ws: WireSet): string {
  const out: string[] = [];
  for (const b of ws.bars) {
    const fill = b.kind === 'N' ? WIRE_COLOR.N : WIRE_COLOR.PE;
    out.push(
      `<g data-bar="${b.kind}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="6" rx="2" fill="${fill}"/>`,
    );
    if (b.kind === 'PE') {
      out.push(
        `<line x1="${b.x}" y1="${b.y + 3}" x2="${b.x + b.w}" y2="${b.y + 3}" stroke="${PE_STRIPE}" stroke-width="3" stroke-dasharray="6 6"/>`,
      );
    }
    out.push(
      `<text x="${b.x + 3}" y="${b.y - 1}" font-size="8" fill="#334155">${b.kind}</text></g>`,
    );
  }
  for (const w of ws.wires) {
    const d = path(w.points);
    out.push(
      `<g data-wire="${w.kind}" data-wire-id="${w.id}">`,
      `<path d="${d}" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round" opacity="0.85"/>`,
      `<path d="${d}" fill="none" stroke="${WIRE_COLOR[w.kind]}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`,
    );
    if (w.kind === 'PE') {
      out.push(
        `<path d="${d}" fill="none" stroke="${PE_STRIPE}" stroke-width="2.5" stroke-dasharray="5 5" stroke-linecap="butt"/>`,
      );
    }
    out.push('</g>');
  }
  return out.join('');
}
