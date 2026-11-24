import { useDraggable } from '@dnd-kit/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { colorOf } from '../model/match';
import type { Product } from '../model/types';

function Item({
  product,
  onAdd,
  readOnly,
}: {
  product: Product;
  onAdd: (p: Product) => void;
  readOnly: boolean;
}) {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: `palette-${product.id}`,
    data: { type: 'palette', product },
    disabled: readOnly,
  });
  return (
    <li
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      data-testid="palette-item"
      data-sku={product.sku}
      onClick={() => !readOnly && onAdd(product)}
      className="flex cursor-grab items-center gap-2 rounded border px-2 py-1 text-xs hover:bg-slate-50"
      style={{ borderLeft: `6px solid ${colorOf(product)}`, touchAction: 'none' }}
    >
      <span className="flex-1">
        <span className="font-medium">{product.brand.name}</span> {product.sku}
        <span className="block text-slate-500">{product.name}</span>
      </span>
      <span className="whitespace-nowrap text-slate-600">{Number(product.price).toFixed(0)} ₴</span>
    </li>
  );
}

export function Palette({
  products,
  onAdd,
  readOnly,
}: {
  products: Product[];
  onAdd: (p: Product) => void;
  readOnly: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [brand, setBrand] = useState('');
  const [poles, setPoles] = useState('');
  const [rated, setRated] = useState('');

  const categories = useMemo(
    () => [...new Map(products.map((p) => [p.category.code, p.category])).values()],
    [products],
  );
  const brands = useMemo(() => [...new Set(products.map((p) => p.brand.name))].sort(), [products]);
  const ratings = useMemo(
    () =>
      [...new Set(products.filter((p) => p.rated_a !== null).map((p) => Number(p.rated_a)))].sort(
        (a, b) => a - b,
      ),
    [products],
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return products
      .filter(
        (p) =>
          (!cat || p.category.code === cat) &&
          (!brand || p.brand.name === brand) &&
          (!poles || p.poles === Number(poles)) &&
          (!rated || Number(p.rated_a) === Number(rated)) &&
          (!needle || `${p.sku} ${p.name}`.toLowerCase().includes(needle)),
      )
      .slice(0, 200);
  }, [products, q, cat, brand, poles, rated]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <h2 className="font-semibold">{t('board.palette')}</h2>
      <input
        className="input"
        placeholder={t('board.search')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="grid grid-cols-2 gap-1">
        <select
          aria-label="category"
          className="input"
          value={cat}
          onChange={(e) => setCat(e.target.value)}
        >
          <option value="">{t('board.allCategories')}</option>
          {categories.map((c) => (
            <option key={c.code} value={c.code}>
              {i18n.language === 'uk' ? c.name_uk : c.name_ru}
            </option>
          ))}
        </select>
        <select
          aria-label="brand"
          className="input"
          value={brand}
          onChange={(e) => setBrand(e.target.value)}
        >
          <option value="">{t('board.allBrands')}</option>
          {brands.map((b) => (
            <option key={b}>{b}</option>
          ))}
        </select>
        <select
          aria-label="poles"
          className="input"
          value={poles}
          onChange={(e) => setPoles(e.target.value)}
        >
          <option value="">{t('board.allPoles')}</option>
          {[1, 2, 3, 4].map((n) => (
            <option key={n} value={n}>
              {n}P
            </option>
          ))}
        </select>
        <select
          aria-label="rated"
          className="input"
          value={rated}
          onChange={(e) => setRated(e.target.value)}
        >
          <option value="">A</option>
          {ratings.map((n) => (
            <option key={n} value={n}>
              {n} A
            </option>
          ))}
        </select>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        {shown.map((p) => (
          <Item key={p.id} product={p} onAdd={onAdd} readOnly={readOnly} />
        ))}
      </ul>
    </div>
  );
}
