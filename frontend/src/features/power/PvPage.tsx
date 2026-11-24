import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import {
  catalog,
  projects,
  pv,
  type Product,
  type Project,
  type PvArrayDto,
  type PvCheck,
  type PvSystem,
} from '../../api/endpoints';

const LEVEL_STYLE: Record<string, string> = {
  error: 'border-red-300 bg-red-50 text-red-800',
  warning: 'border-amber-300 bg-amber-50 text-amber-800',
  info: 'border-sky-300 bg-sky-50 text-sky-800',
};

const NEW_ARRAY = { series: 10, strings: 1, azimuth_deg: 0, tilt_deg: 35, cable_m: 20 };

function label(p: Product): string {
  return `${p.brand.name} ${p.sku} — ${p.name}`;
}

function n(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits);
}

function mpptCount(p: Product): number {
  return Number((p.electrical as Record<string, unknown> | undefined)?.mppt_count ?? 0);
}

export function PvPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [cfg, setCfg] = useState<PvSystem | null>(null);
  const [check, setCheck] = useState<PvCheck | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState('');
  const [applied, setApplied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<Partial<PvSystem>>({});

  const recheck = useCallback(async () => {
    try {
      setCheck(await pv.check(id));
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false; // StrictMode runs effects twice
    void Promise.all([projects.get(id), pv.get(id), catalog.products()]).then(([p, c, prods]) => {
      if (cancelled) return;
      setProject(p);
      setCfg(c);
      setProducts(prods);
      void recheck();
    });
    return () => {
      cancelled = true;
    };
  }, [id, recheck]);

  const modules = useMemo(
    () => products.filter((p) => p.category.code === 'pv_module'),
    [products],
  );
  const inverters = useMemo(
    () => products.filter((p) => p.category.code === 'inverter' && mpptCount(p) > 0),
    [products],
  );

  /** Changes made within the debounce window are merged into one PATCH. */
  function patch(change: Partial<PvSystem>) {
    if (!cfg) return;
    setCfg({ ...cfg, ...change });
    setApplied(false);
    pending.current = { ...pending.current, ...change };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      void pv
        .update(id, body)
        .then(recheck)
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
    }, 300);
  }

  function setArray(i: number, change: Partial<PvArrayDto>) {
    const arrays = (cfg?.arrays ?? []).map((a, k) => (k === i ? { ...a, ...change } : a));
    patch({ arrays });
  }

  function addArray() {
    const arrays = cfg?.arrays ?? [];
    const free = Math.max(0, ...arrays.map((a) => a.mppt)) + 1;
    patch({ arrays: [...arrays, { ...NEW_ARRAY, mppt: free } as PvArrayDto] });
  }

  async function apply() {
    try {
      await pv.apply(id);
      setApplied(true);
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (!cfg || !project) return <div className="p-4">{t('app.loading')}</div>;
  const field = 'flex flex-col gap-1 text-sm';
  const num = (v: number | undefined, def: number) => v ?? def;
  const m = check?.metrics;

  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-2" data-testid="pv-page">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{t('pv.title')}</h1>
          <Link className="btn" to={`/projects/${id}`}>
            {project.name}
          </Link>
        </div>

        <label className={field}>
          {t('pv.module')}
          <select
            className="input"
            data-testid="pv-module"
            value={cfg.module ?? ''}
            onChange={(e) => patch({ module: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">—</option>
            {modules.map((p) => (
              <option key={p.id} value={p.id}>
                {label(p)}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-[1fr_8rem] gap-2">
          <label className={field}>
            {t('pv.inverter')}
            <select
              className="input"
              data-testid="pv-inverter"
              value={cfg.inverter ?? ''}
              onChange={(e) => patch({ inverter: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">—</option>
              {inverters.map((p) => (
                <option key={p.id} value={p.id}>
                  {label(p)}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t('pv.inverterCount')}
            <input
              className="input"
              type="number"
              min={1}
              max={9}
              value={num(cfg.inverter_count, 1)}
              onChange={(e) => patch({ inverter_count: Number(e.target.value) })}
            />
          </label>
        </div>

        <fieldset className="rounded border bg-white p-3">
          <legend className="px-1 text-sm font-medium">{t('pv.arrays')}</legend>
          <div className="flex flex-col gap-2" data-testid="arrays">
            {(cfg.arrays ?? []).map((a, i) => (
              <div key={i} className="grid grid-cols-6 items-end gap-2" data-testid="array-row">
                <label className={field}>
                  {t('pv.mppt')}
                  <input
                    className="input"
                    type="number"
                    min={1}
                    data-testid="a-mppt"
                    value={a.mppt}
                    onChange={(e) => setArray(i, { mppt: Number(e.target.value) })}
                  />
                </label>
                <label className={field}>
                  {t('pv.series')}
                  <input
                    className="input"
                    type="number"
                    min={1}
                    data-testid="a-series"
                    value={num(a.series, 10)}
                    onChange={(e) => setArray(i, { series: Number(e.target.value) })}
                  />
                </label>
                <label className={field}>
                  {t('pv.strings')}
                  <input
                    className="input"
                    type="number"
                    min={1}
                    data-testid="a-strings"
                    value={num(a.strings, 1)}
                    onChange={(e) => setArray(i, { strings: Number(e.target.value) })}
                  />
                </label>
                <label className={field}>
                  {t('pv.azimuth')}
                  <input
                    className="input"
                    type="number"
                    min={-180}
                    max={180}
                    value={num(a.azimuth_deg, 0)}
                    onChange={(e) => setArray(i, { azimuth_deg: Number(e.target.value) })}
                  />
                </label>
                <label className={field}>
                  {t('pv.tilt')}
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={90}
                    value={num(a.tilt_deg, 35)}
                    onChange={(e) => setArray(i, { tilt_deg: Number(e.target.value) })}
                  />
                </label>
                <label className={field}>
                  {t('pv.cable')}
                  <input
                    className="input"
                    type="number"
                    min={1}
                    data-testid="a-cable"
                    value={num(a.cable_m, 20)}
                    onChange={(e) => setArray(i, { cable_m: Number(e.target.value) })}
                  />
                </label>
                <button
                  className="btn col-span-6 justify-self-end"
                  data-testid="a-remove"
                  onClick={() => patch({ arrays: (cfg.arrays ?? []).filter((_, k) => k !== i) })}
                >
                  {t('pv.remove')}
                </button>
              </div>
            ))}
          </div>
          <button className="btn mt-2" data-testid="add-array" onClick={addArray}>
            {t('pv.addArray')}
          </button>
        </fieldset>

        <div className="grid grid-cols-3 gap-2">
          <label className={field}>
            {t('pv.tMin')}
            <input
              className="input"
              type="number"
              min={-50}
              max={10}
              value={num(cfg.t_min_c, -20)}
              onChange={(e) => patch({ t_min_c: Number(e.target.value) })}
            />
          </label>
          <label className={field}>
            {t('pv.tCellMax')}
            <input
              className="input"
              type="number"
              min={40}
              max={95}
              value={num(cfg.t_cell_max_c, 70)}
              onChange={(e) => patch({ t_cell_max_c: Number(e.target.value) })}
            />
          </label>
          <label className={field}>
            {t('pv.pr')}
            <input
              className="input"
              type="number"
              min={0.5}
              max={0.95}
              step={0.01}
              value={num(cfg.performance_ratio, 0.8)}
              onChange={(e) => patch({ performance_ratio: Number(e.target.value) })}
            />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className={field}>
            {t('pv.region')}
            <select
              className="input"
              data-testid="pv-region"
              value={cfg.region ?? 'center'}
              onChange={(e) => patch({ region: e.target.value as PvSystem['region'] })}
            >
              {(['north', 'center', 'south'] as const).map((r) => (
                <option key={r} value={r}>
                  {t(`pv.regions.${r}`)}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t('pv.exportLimit')}
            <input
              className="input"
              type="number"
              min={0}
              value={num(cfg.export_limit_w, 0)}
              onChange={(e) => patch({ export_limit_w: Number(e.target.value) })}
            />
          </label>
        </div>
        <label className="text-sm">
          <input
            type="checkbox"
            data-testid="green-tariff"
            checked={cfg.green_tariff ?? false}
            onChange={(e) => patch({ green_tariff: e.target.checked })}
          />{' '}
          {t('pv.greenTariff')}
        </label>
      </div>

      <div className="flex flex-col gap-3" data-testid="pv-result">
        {error && (
          <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
            {error}
          </p>
        )}
        {check && !check.configured && (
          <p className="rounded border bg-white p-3 text-sm text-slate-600">
            {t('pv.notConfigured')}
          </p>
        )}
        {check?.configured && (
          <>
            <div
              data-testid="pv-status"
              data-ok={check.ok}
              className={`rounded px-3 py-2 font-medium ${check.ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}
            >
              {check.ok ? t('pv.ok') : t('pv.notOk')}
            </div>

            {m && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border bg-white p-3 text-sm">
                <dt>{t('pv.modules')}</dt>
                <dd data-testid="pv-modules">{m.modules}</dd>
                <dt>{t('pv.kwp')}</dt>
                <dd data-testid="pv-kwp">{n(m.kwp, 2)} кВт</dd>
                <dt>{t('pv.dcAc')}</dt>
                <dd data-testid="pv-dcac">{n(m.dc_ac_ratio, 2)}</dd>
                <dt>{t('pv.yield')}</dt>
                <dd data-testid="pv-yield">
                  {n(m.yield_kwh_year, 0)} {t('pv.yieldUnit')}
                </dd>
              </dl>
            )}

            {check.arrays.length > 0 && (
              <>
                <h2 className="font-medium">{t('pv.arrayTitle')}</h2>
                <table
                  className="w-full rounded border bg-white text-xs"
                  data-testid="array-results"
                >
                  <thead className="text-left text-slate-500">
                    <tr>
                      <th className="p-1">{t('pv.mppt')}</th>
                      <th className="p-1">{t('pv.vocCold')}</th>
                      <th className="p-1">{t('pv.vmp')}</th>
                      <th className="p-1">{t('pv.isc')}</th>
                      <th className="p-1">{t('pv.fuse')}</th>
                      <th className="p-1">{t('pv.cableMm2')}</th>
                      <th className="p-1">{t('pv.drop')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {check.arrays.map((a) => (
                      <tr key={a.mppt} className="border-t">
                        <td className="p-1">{a.mppt}</td>
                        <td className="p-1">{n(a.voc_cold_v, 0)}</td>
                        <td className="p-1">{n(a.vmp_stc_v, 0)}</td>
                        <td className="p-1">{n(a.isc_a)}</td>
                        <td className="p-1">{a.fuse_a ?? '—'}</td>
                        <td className="p-1">{a.cable_mm2}</td>
                        <td className="p-1">{n(a.drop_pct, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            <ul className="flex flex-col gap-1" data-testid="pv-findings">
              {check.findings.map((f, i) => (
                <li
                  key={i}
                  data-code={f.code}
                  data-level={f.level}
                  className={`rounded border px-2 py-1 text-sm ${LEVEL_STYLE[f.level]}`}
                >
                  {f.message}
                </li>
              ))}
            </ul>

            <h2 className="font-medium">{t('pv.components')}</h2>
            <table className="w-full rounded border bg-white text-sm" data-testid="pv-components">
              <tbody>
                {check.components.map((c, i) => (
                  <tr key={i} className="border-t align-top" data-role={c.role}>
                    <td className="p-1 text-slate-500">{c.note}</td>
                    <td className="p-1">
                      {c.product ? (
                        <>
                          {c.product.brand.name} {c.product.sku}
                        </>
                      ) : (
                        <span className="text-red-700">{t('pv.noProduct')}</span>
                      )}
                    </td>
                    <td className="p-1 text-right">×{c.qty}</td>
                    <td className="p-1 text-right">{c.price_total ?? '—'}</td>
                  </tr>
                ))}
                <tr className="border-t font-semibold">
                  <td className="p-1" colSpan={3}>
                    {t('board.total')}
                  </td>
                  <td className="p-1 text-right" data-testid="pv-total">
                    {check.total_price} ₴
                  </td>
                </tr>
              </tbody>
            </table>

            <div className="flex items-center gap-3">
              <button
                className="btn btn-primary"
                data-testid="pv-apply"
                disabled={!check.ok}
                onClick={() => void apply()}
              >
                {t('pv.apply')}
              </button>
              {applied && (
                <Link
                  className="text-blue-700"
                  data-testid="pv-applied-link"
                  to={`/projects/${id}/board`}
                >
                  {t('pv.openBoard')}
                </Link>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
