import type { Device, PanelModel, Product } from './types';

export function device(id: string, over: Partial<Device> = {}): Device {
  return {
    id,
    serverId: null,
    productId: 1,
    railId: 1,
    start: 0,
    width: 1,
    x: null,
    y: null,
    w: null,
    h: null,
    groupId: null,
    label: '',
    ...over,
  };
}

export function panel(over: Partial<PanelModel> = {}): PanelModel {
  return {
    id: 1,
    name: 'ГРЩ',
    kind: 'main',
    enclosureId: null,
    ip: 40,
    rails: [{ id: 1, rowIndex: 0, capacity: 12 }],
    area: { width: 210, height: 300 },
    devices: [],
    ...over,
  };
}

export function product(over: Partial<Product> & { id: number }): Product {
  return {
    brand: { id: 1, name: 'ABB', slug: 'abb', tier: 'premium' },
    category: { id: 1, code: 'mcb', name_ru: 'Автомат', name_uk: 'Автомат' },
    sku: `SKU-${over.id}`,
    name: 'Product',
    series: '',
    tier: 'mid',
    rated_a: '16.00',
    poles: 1,
    curve: 'C',
    leakage_ma: null,
    rcd_type: '',
    modules: '1.0',
    width_mm: null,
    height_mm: null,
    depth_mm: null,
    din_mountable: true,
    electrical: {},
    price: '100.00',
    price_date: '2026-11-24',
    needs_verification: true,
    ...over,
  } as Product;
}
