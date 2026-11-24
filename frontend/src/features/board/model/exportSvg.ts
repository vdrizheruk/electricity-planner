import { MM_PX, MODULE_PX, RAIL_HEIGHT_PX } from './geometry';
import { colorOf, shortName } from './match';
import { buildWires, WIRE_GAP, wiresToSvg } from './wires';
import type { Group, PanelModel, Product } from './types';

const PAD = 24;
const ROW_GAP = WIRE_GAP;

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export interface SvgSize {
  width: number;
  height: number;
}

/** Vector picture of one board: enclosure, rails, devices with group labels. */
export function boardToSvg(
  panel: PanelModel,
  products: Map<number, Product>,
  groups: Group[],
  threePhase = false,
): { svg: string } & SvgSize {
  const groupName = new Map(groups.map((g) => [g.id, g.name]));
  const rails = [...panel.rails].sort((a, b) => a.rowIndex - b.rowIndex);
  const railW = Math.max(...rails.map((r) => r.capacity), 0) * MODULE_PX;
  const mountW = (panel.area.width ?? 0) * MM_PX;
  const mountH = (panel.area.height ?? 0) * MM_PX;
  const railsH = (rails.length + 1) * (RAIL_HEIGHT_PX + ROW_GAP);
  const width = PAD * 2 + railW + (mountW > 0 ? mountW + PAD : 0);
  const height = PAD * 2 + 28 + Math.max(railsH, mountH);
  const out: string[] = [];
  out.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Arial, sans-serif">`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#ffffff"/>`,
    `<text x="${PAD}" y="${PAD}" font-size="16" font-weight="bold">${esc(panel.name)} (IP${panel.ip})</text>`,
  );
  const top = PAD + 12;
  rails.forEach((r, i) => {
    const y = top + (i + 1) * ROW_GAP + i * RAIL_HEIGHT_PX;
    out.push(
      `<rect x="${PAD}" y="${y}" width="${r.capacity * MODULE_PX}" height="${RAIL_HEIGHT_PX}" fill="#f8fafc" stroke="#94a3b8"/>`,
      `<rect x="${PAD}" y="${y + RAIL_HEIGHT_PX / 2 - 4}" width="${r.capacity * MODULE_PX}" height="8" fill="#cbd5e1"/>`,
    );
    for (const d of panel.devices.filter((x) => x.railId === r.id && x.start !== null)) {
      const p = products.get(d.productId);
      const x = PAD + (d.start as number) * MODULE_PX;
      const w = d.width * MODULE_PX;
      const label = (d.groupId !== null ? groupName.get(d.groupId) : undefined) ?? d.label;
      out.push(
        `<g data-device="${esc(d.id)}">`,
        `<rect x="${x + 1}" y="${y + 8}" width="${w - 2}" height="${RAIL_HEIGHT_PX - 16}" rx="3" fill="${colorOf(p)}" stroke="#334155"/>`,
        `<text x="${x + w / 2}" y="${y + 28}" font-size="11" text-anchor="middle">${esc(p ? shortName(p) : '?')}</text>`,
      );
      if (label) {
        const tx = x + w / 2;
        const ty = y + 40;
        out.push(
          d.width === 1
            ? `<text transform="rotate(90 ${tx} ${ty})" x="${tx}" y="${ty}" font-size="10">${esc(label)}</text>`
            : `<text x="${tx}" y="${ty + 12}" font-size="10" text-anchor="middle">${esc(label)}</text>`,
        );
      }
      out.push('</g>');
    }
  });
  const ws = buildWires(panel, products, groups, threePhase);
  out.push(`<g transform="translate(${PAD} ${top})">${wiresToSvg(ws)}</g>`);
  if (mountW > 0) {
    const ox = PAD * 2 + railW;
    out.push(
      `<rect x="${ox}" y="${top}" width="${mountW}" height="${mountH}" fill="#f8fafc" stroke="#94a3b8" stroke-dasharray="4"/>`,
    );
    for (const d of panel.devices.filter((x) => x.railId === null && x.x !== null)) {
      const p = products.get(d.productId);
      out.push(
        `<g data-device="${esc(d.id)}"><rect x="${ox + (d.x as number) * MM_PX}" y="${top + (d.y as number) * MM_PX}" width="${(d.w as number) * MM_PX}" height="${(d.h as number) * MM_PX}" fill="${colorOf(p)}" stroke="#334155"/><text x="${ox + (d.x as number) * MM_PX + 4}" y="${top + (d.y as number) * MM_PX + 14}" font-size="10">${esc(p?.sku ?? '?')}</text></g>`,
      );
    }
  }
  out.push('</svg>');
  return { svg: out.join(''), width, height };
}
