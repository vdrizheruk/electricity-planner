import { NODE_W, type Diagram } from './diagram';

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const NODE_H = 72;
const PAD = 24;
const FILL: Record<string, string> = {
  feeder: '#e2e8f0',
  bus: '#cbd5e1',
  chain: '#e9d5ff',
  rcd: '#fde68a',
  breaker: '#dbeafe',
  other: '#f1f5f9',
};

/** Vector export of the single-line diagram (same data as the React Flow view). */
export function diagramToSvg(
  d: Diagram,
  title: string,
): { svg: string; width: number; height: number } {
  const maxX = Math.max(...d.nodes.map((n) => n.x), 0) + NODE_W;
  const maxY = Math.max(...d.nodes.map((n) => n.y), 0) + NODE_H;
  const width = maxX + PAD * 2;
  const height = maxY + PAD * 2 + 20;
  const byId = new Map(d.nodes.map((n) => [n.id, n]));
  const out = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Arial, sans-serif">`,
    `<rect width="${width}" height="${height}" fill="#fff"/>`,
    `<text x="${PAD}" y="${PAD}" font-size="14" font-weight="bold">${esc(title)}</text>`,
  ];
  const oy = PAD + 12;
  for (const e of d.edges) {
    const a = byId.get(e.source);
    const b = byId.get(e.target);
    if (!a || !b) continue;
    const horizontal = a.y === b.y;
    const x1 = PAD + a.x + (horizontal ? NODE_W : NODE_W / 2);
    const y1 = oy + a.y + (horizontal ? NODE_H / 2 : NODE_H);
    const x2 = PAD + b.x + (horizontal ? 0 : NODE_W / 2);
    const y2 = oy + b.y + (horizontal ? NODE_H / 2 : 0);
    out.push(
      `<path data-edge="${esc(e.id)}" d="M${x1} ${y1} L${x2} ${y2}" stroke="#334155" fill="none"/>`,
    );
  }
  for (const n of d.nodes) {
    const x = PAD + n.x;
    const y = oy + n.y;
    out.push(
      `<g data-node="${esc(n.id)}">`,
      `<rect x="${x}" y="${y}" width="${NODE_W}" height="${NODE_H}" rx="4" fill="${FILL[n.kind] ?? '#fff'}" stroke="#334155"/>`,
      `<text x="${x + 6}" y="${y + 16}" font-size="12" font-weight="bold">${esc(n.tag ? `${n.tag} ` : '')}${esc(n.title.slice(0, 22))}</text>`,
      `<text x="${x + 6}" y="${y + 33}" font-size="10">${esc(n.subtitle.slice(0, 30))}</text>`,
      `<text x="${x + 6}" y="${y + 50}" font-size="10">${esc(n.load)}</text>`,
      `</g>`,
    );
  }
  out.push('</svg>');
  return { svg: out.join(''), width, height };
}
