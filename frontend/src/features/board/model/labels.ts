import { designations, orderedDevices } from './diagram';
import { shortName } from './match';
import type { Group, PanelModel, Product } from './types';

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export interface LabelItem {
  tag: string;
  line1: string;
  line2: string;
}

/** Text of one sticker per device: «QF3 · C16», group name and load. */
export function labelItems(
  panel: PanelModel,
  products: Map<number, Product>,
  groups: Group[],
): LabelItem[] {
  const tags = designations(panel, products);
  const groupById = new Map(groups.map((g) => [g.id, g]));
  return orderedDevices(panel).map((d) => {
    const p = products.get(d.productId);
    const g = d.groupId !== null ? groupById.get(d.groupId) : undefined;
    const load = g ? `${g.power_w} Вт${g.cable_mm2 ? ` · ${Number(g.cable_mm2)} мм²` : ''}` : '';
    return {
      tag: tags.get(d.id) ?? '',
      line1: p ? shortName(p) : '?',
      line2: [g?.name ?? d.label, load].filter(Boolean).join(' · '),
    };
  });
}

const CELL_W = 180;
const CELL_H = 54;
const COLS = 4;

/** Printable sheet of marking stickers (SVG, 4 columns). */
export function labelsToSvg(
  items: LabelItem[],
  title: string,
): { svg: string; width: number; height: number } {
  const rows = Math.max(1, Math.ceil(items.length / COLS));
  const width = COLS * CELL_W + 20;
  const height = rows * CELL_H + 44;
  const out = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Arial, sans-serif">`,
    `<rect width="${width}" height="${height}" fill="#fff"/>`,
    `<text x="10" y="22" font-size="14" font-weight="bold">${esc(title)}</text>`,
  ];
  items.forEach((it, i) => {
    const x = 10 + (i % COLS) * CELL_W;
    const y = 34 + Math.floor(i / COLS) * CELL_H;
    out.push(
      `<g data-label="${esc(it.tag)}">`,
      `<rect x="${x}" y="${y}" width="${CELL_W - 6}" height="${CELL_H - 6}" fill="#fff" stroke="#000"/>`,
      `<text x="${x + 6}" y="${y + 18}" font-size="14" font-weight="bold">${esc(it.tag)} · ${esc(it.line1)}</text>`,
      `<text x="${x + 6}" y="${y + 36}" font-size="11">${esc(it.line2.slice(0, 34))}</text>`,
      `</g>`,
    );
  });
  out.push('</svg>');
  return { svg: out.join(''), width, height };
}
