import type { Device, PanelModel, Product } from './types';

const NBSP = '\u00a0';

export interface BomLine {
  productId: number;
  brand: string;
  sku: string;
  name: string;
  qty: number;
  unitCents: number;
  totalCents: number;
}

export interface PanelBom {
  panelId: number;
  name: string;
  lines: BomLine[];
  totalCents: number;
}

export interface Bom {
  panels: PanelBom[];
  lines: BomLine[];
  /** «Щиты» */
  boardsCents: number;
  /** «Солнечная система» — filled by the PV stage. */
  solarCents: number;
  totalCents: number;
}

/** "1234.50" -> 123450 without float arithmetic. */
export function toCents(price: string): number {
  const m = /^(-?)(\d+)(?:\.(\d{1,}))?$/.exec(price.trim());
  if (!m) throw new Error(`Bad price: ${price}`);
  const frac = ((m[3] ?? '') + '00').slice(0, 2);
  const cents = Number(m[2]) * 100 + Number(frac);
  return m[1] ? -cents : cents;
}

export function formatUah(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${sign}${whole},${String(abs % 100).padStart(2, '0')}${NBSP}₴`;
}

function line(p: Product, qty: number): BomLine {
  const unit = toCents(p.price);
  return {
    productId: p.id,
    brand: p.brand.name,
    sku: p.sku,
    name: p.name,
    qty,
    unitCents: unit,
    totalCents: unit * qty,
  };
}

function aggregate(items: { product: Product; qty: number }[]): BomLine[] {
  const byId = new Map<number, { product: Product; qty: number }>();
  for (const it of items) {
    const cur = byId.get(it.product.id);
    if (cur) cur.qty += it.qty;
    else byId.set(it.product.id, { ...it });
  }
  return [...byId.values()]
    .map((x) => line(x.product, x.qty))
    .sort((a, b) => a.brand.localeCompare(b.brand) || a.sku.localeCompare(b.sku));
}

function panelItems(panel: PanelModel, products: Map<number, Product>) {
  const items: { product: Product; qty: number }[] = [];
  const enc = panel.enclosureId !== null ? products.get(panel.enclosureId) : undefined;
  if (enc) items.push({ product: enc, qty: 1 });
  for (const d of panel.devices as Device[]) {
    const p = products.get(d.productId);
    if (p) items.push({ product: p, qty: 1 });
  }
  return items;
}

export function buildBom(panels: PanelModel[], products: Map<number, Product>): Bom {
  const perPanel: PanelBom[] = panels.map((panel) => {
    const lines = aggregate(panelItems(panel, products));
    return {
      panelId: panel.id,
      name: panel.name,
      lines,
      totalCents: lines.reduce((n, l) => n + l.totalCents, 0),
    };
  });
  const lines = aggregate(panels.flatMap((p) => panelItems(p, products)));
  const boards = lines.reduce((n, l) => n + l.totalCents, 0);
  return { panels: perPanel, lines, boardsCents: boards, solarCents: 0, totalCents: boards };
}
