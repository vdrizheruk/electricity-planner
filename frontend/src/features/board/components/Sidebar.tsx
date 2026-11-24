import { useTranslation } from 'react-i18next';
import { buildBom, formatUah, type BomExtra } from '../model/bom';
import { GROUP_BINDABLE, type BoardStore } from '../model/store';
import type { Group, Issue, PanelModel, Product } from '../model/types';
import { useBoard } from '../useStore';

export function BomView({
  panels,
  products,
  extra,
}: {
  panels: PanelModel[];
  products: Map<number, Product>;
  extra?: BomExtra;
}) {
  const { t } = useTranslation();
  const bom = buildBom(panels, products, extra);
  return (
    <div data-testid="bom">
      <h2 className="mb-1 font-semibold">{t('board.bom')}</h2>
      <table className="w-full text-xs">
        <tbody>
          {bom.lines.map((l) => (
            <tr key={l.productId} className="border-t">
              <td className="py-0.5">
                {l.brand} {l.sku}
              </td>
              <td className="text-right">×{l.qty}</td>
              <td className="text-right">{formatUah(l.totalCents)}</td>
            </tr>
          ))}
          <tr className="border-t">
            <td colSpan={2}>{t('board.boards')}</td>
            <td className="text-right">{formatUah(bom.boardsCents)}</td>
          </tr>
          <tr>
            <td colSpan={2}>{t('board.solar')}</td>
            <td className="text-right">{formatUah(bom.solarCents)}</td>
          </tr>
          {bom.backupCents > 0 && (
            <tr>
              <td colSpan={2}>{t('board.backup')}</td>
              <td className="text-right">{formatUah(bom.backupCents)}</td>
            </tr>
          )}
          <tr className="border-t font-semibold">
            <td colSpan={2}>{t('board.total')}</td>
            <td data-testid="bom-total" className="text-right">
              {formatUah(bom.totalCents)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function IssuesView({ issues }: { issues: Issue[] }) {
  const { t } = useTranslation();
  return (
    <div data-testid="issues">
      <h2 className="mb-1 font-semibold">{t('board.issues')}</h2>
      {issues.length === 0 ? (
        <p className="text-xs text-green-700">{t('board.noIssues')}</p>
      ) : (
        <ul className="list-disc pl-4 text-xs text-red-700">
          {issues.map((i, k) => (
            <li key={k}>
              {i.code} ({i.deviceId})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Properties({
  store,
  groups,
  products,
}: {
  store: BoardStore;
  groups: Group[];
  products: Map<number, Product>;
}) {
  const { t } = useTranslation();
  const sel = useBoard(store, (s) => s.selection);
  const panels = useBoard(store, (s) => s.panels);
  if (sel.length !== 1) return null;
  const id = sel[0] as string;
  const device = Object.values(panels)
    .flatMap((p) => p.devices)
    .find((d) => d.id === id);
  if (!device) return null;
  const product = products.get(device.productId);
  const bindable = product ? GROUP_BINDABLE.has(product.category.code) : false;
  return (
    <div className="flex flex-col gap-1 text-xs">
      <h2 className="font-semibold">{product?.sku}</h2>
      <label>
        {t('board.label')}
        <input
          className="input ml-1"
          value={device.label}
          onChange={(e) => store.getState().setLabel(id, e.target.value)}
        />
      </label>
      {bindable && (
        <label>
          {t('board.group')}
          <select
            className="input ml-1"
            value={device.groupId ?? ''}
            onChange={(e) =>
              store.getState().setGroup(id, e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">{t('board.noGroup')}</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}
