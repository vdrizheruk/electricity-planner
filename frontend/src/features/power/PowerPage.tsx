import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import {
  catalog,
  groups as groupsApi,
  power,
  projects,
  type Group,
  type PowerCheck,
  type PowerSystem,
  type Product,
  type Project,
} from '../../api/endpoints';

const SCENARIOS = [
  'grid_gen_ats',
  'grid_inverter',
  'grid_inverter_gen',
  'manual_i0ii',
  'grid3_gen1_phase',
  'grid3_gen1_combine',
  'grid1_gen1',
] as const;
const GEN_SCENARIOS = new Set<string>([
  'grid_gen_ats',
  'manual_i0ii',
  'grid3_gen1_phase',
  'grid3_gen1_combine',
  'grid1_gen1',
  'grid_inverter_gen',
]);
const INV_SCENARIOS = new Set<string>(['grid_inverter', 'grid_inverter_gen']);

const LEVEL_STYLE: Record<string, string> = {
  error: 'border-red-300 bg-red-50 text-red-800',
  warning: 'border-amber-300 bg-amber-50 text-amber-800',
  info: 'border-sky-300 bg-sky-50 text-sky-800',
};

function productLabel(p: Product): string {
  return `${p.brand.name} ${p.sku} — ${p.name}`;
}

function num(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits);
}

export function PowerPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [cfg, setCfg] = useState<PowerSystem | null>(null);
  const [check, setCheck] = useState<PowerCheck | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [error, setError] = useState('');
  const [applied, setApplied] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const recheck = useCallback(async () => {
    try {
      setCheck(await power.check(id));
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    // StrictMode runs effects twice: a late first response must not overwrite user edits.
    let cancelled = false;
    void Promise.all([
      projects.get(id),
      power.get(id),
      catalog.products(),
      groupsApi.list(id),
    ]).then(([p, c, prods, g]) => {
      if (cancelled) return;
      setProject(p);
      setCfg(c);
      setProducts(prods);
      setGroups(g);
      void recheck();
    });
    return () => {
      cancelled = true;
    };
  }, [id, recheck]);

  const byCategory = useMemo(() => {
    const m = new Map<string, Product[]>();
    for (const p of products) {
      const list = m.get(p.category.code) ?? [];
      list.push(p);
      m.set(p.category.code, list);
    }
    return m;
  }, [products]);

  /** Changes made within the debounce window are merged into one PATCH. */
  const pending = useRef<Partial<PowerSystem>>({});
  function patch(change: Partial<PowerSystem>) {
    if (!cfg) return;
    setCfg({ ...cfg, ...change });
    setApplied(null);
    pending.current = { ...pending.current, ...change };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      void power
        .update(id, body)
        .then(recheck)
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
    }, 300);
  }

  async function toggleBackup(g: Group) {
    const next = !g.backed_up;
    setGroups((list) => list.map((x) => (x.id === g.id ? { ...x, backed_up: next } : x)));
    try {
      await groupsApi.update(g.id, { backed_up: next });
      await recheck();
    } catch (e) {
      setGroups((list) => list.map((x) => (x.id === g.id ? { ...x, backed_up: !next } : x)));
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function apply() {
    try {
      const r = await power.apply(id);
      setApplied(r.panel.id);
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (!cfg || !project) return <div className="p-4">{t('app.loading')}</div>;
  const three = project.grid === '3ph';
  const scenario: string = cfg.scenario ?? 'grid_gen_ats';
  const gens = byCategory.get('generator') ?? [];
  const invs = byCategory.get('inverter') ?? [];
  const bats = byCategory.get('battery') ?? [];
  const m = check?.metrics;

  const field = 'flex flex-col gap-1 text-sm';
  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-2" data-testid="power-page">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{t('power.title')}</h1>
          <Link className="btn" to={`/projects/${id}`}>
            {project.name}
          </Link>
        </div>

        <label className={field}>
          {t('power.scenario')}
          <select
            className="input"
            data-testid="scenario"
            value={scenario}
            onChange={(e) => patch({ scenario: e.target.value as PowerSystem['scenario'] })}
          >
            {SCENARIOS.filter((s) => three || !s.startsWith('grid3')).map((s) => (
              <option key={s} value={s}>
                {t(`power.scenarios.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {check && <p className="text-sm text-slate-600">{check.description}</p>}

        {GEN_SCENARIOS.has(scenario) && (
          <label className={field}>
            {t('power.generator')}
            <select
              className="input"
              data-testid="generator"
              value={cfg.generator ?? ''}
              onChange={(e) => patch({ generator: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">—</option>
              {gens.map((p) => (
                <option key={p.id} value={p.id}>
                  {productLabel(p)}
                </option>
              ))}
            </select>
          </label>
        )}

        {INV_SCENARIOS.has(scenario) && (
          <>
            <label className={field}>
              {t('power.inverter')}
              <select
                className="input"
                data-testid="inverter"
                value={cfg.inverter ?? ''}
                onChange={(e) =>
                  patch({ inverter: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">—</option>
                {invs.map((p) => (
                  <option key={p.id} value={p.id}>
                    {productLabel(p)}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className={field}>
                {t('power.inverterCount')}
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={9}
                  value={cfg.inverter_count ?? 1}
                  onChange={(e) => patch({ inverter_count: Number(e.target.value) })}
                />
              </label>
              <label className={field}>
                {t('power.inverterMode')}
                <select
                  className="input"
                  value={cfg.inverter_mode ?? 'single'}
                  onChange={(e) =>
                    patch({ inverter_mode: e.target.value as PowerSystem['inverter_mode'] })
                  }
                >
                  {(['single', 'parallel', 'phase_set'] as const).map((x) => (
                    <option key={x} value={x}>
                      {t(`power.modes.${x}`)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className={field}>
              {t('power.battery')}
              <select
                className="input"
                data-testid="battery"
                value={cfg.battery ?? ''}
                onChange={(e) => patch({ battery: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">—</option>
                {bats.map((p) => (
                  <option key={p.id} value={p.id}>
                    {productLabel(p)}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className={field}>
                {t('power.batteryCount')}
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={64}
                  value={cfg.battery_count ?? 1}
                  onChange={(e) => patch({ battery_count: Number(e.target.value) })}
                />
              </label>
              <label className={field}>
                {t('power.autonomyTarget')}
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={0.5}
                  value={cfg.autonomy_target_h ?? 4}
                  onChange={(e) => patch({ autonomy_target_h: Number(e.target.value) })}
                />
              </label>
            </div>
          </>
        )}

        {GEN_SCENARIOS.has(scenario) && (
          <fieldset className="rounded border bg-white p-3">
            <legend className="px-1 text-sm font-medium">{t('power.ats')}</legend>
            <div className="grid grid-cols-3 gap-2">
              <label className={field}>
                {t('power.atsKind')}
                <select
                  className="input"
                  data-testid="ats-kind"
                  value={cfg.ats_kind ?? 'none'}
                  onChange={(e) => patch({ ats_kind: e.target.value as PowerSystem['ats_kind'] })}
                >
                  {(['none', 'contactor', 'modular', 'manual'] as const).map((k) => (
                    <option key={k} value={k}>
                      {t(`power.atsKinds.${k}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className={field}>
                {t('power.atsPoles')}
                <input
                  className="input"
                  data-testid="ats-poles"
                  type="number"
                  min={1}
                  max={4}
                  value={cfg.ats_poles ?? 2}
                  onChange={(e) => patch({ ats_poles: Number(e.target.value) })}
                />
              </label>
              <label className={field}>
                {t('power.atsRated')}
                <input
                  className="input"
                  data-testid="ats-rated"
                  type="number"
                  min={0}
                  value={cfg.ats_rated_a ?? 0}
                  onChange={(e) => patch({ ats_rated_a: Number(e.target.value) })}
                />
              </label>
            </div>
            <div className="mt-2 flex gap-4 text-sm">
              <label>
                <input
                  type="checkbox"
                  data-testid="mech-interlock"
                  checked={cfg.mechanical_interlock ?? false}
                  onChange={(e) => patch({ mechanical_interlock: e.target.checked })}
                />{' '}
                {t('power.mechInterlock')}
              </label>
              <label>
                <input
                  type="checkbox"
                  data-testid="elec-interlock"
                  checked={cfg.electrical_interlock ?? false}
                  onChange={(e) => patch({ electrical_interlock: e.target.checked })}
                />{' '}
                {t('power.elecInterlock')}
              </label>
            </div>
            {scenario === 'grid3_gen1_phase' && (
              <label className={`${field} mt-2`}>
                {t('power.backupPhase')}
                <select
                  className="input w-24"
                  value={cfg.backup_phase ?? 'L1'}
                  onChange={(e) =>
                    patch({ backup_phase: e.target.value as PowerSystem['backup_phase'] })
                  }
                >
                  {['L1', 'L2', 'L3'].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
            )}
          </fieldset>
        )}

        <div>
          <h2 className="mb-1 font-medium">{t('power.loads')}</h2>
          <ul className="divide-y rounded border bg-white text-sm">
            {groups.map((g) => (
              <li key={g.id} className="flex items-center gap-2 px-3 py-1">
                <input
                  type="checkbox"
                  data-testid="backup-toggle"
                  aria-label={g.name}
                  checked={g.backed_up ?? false}
                  onChange={() => void toggleBackup(g)}
                />
                <span className="flex-1">{g.name}</span>
                <span className="text-slate-500">{g.power_w} Вт</span>
                {three && <span className="w-10 text-slate-500">{g.assigned_phase}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex flex-col gap-3" data-testid="power-result">
        {error && (
          <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
            {error}
          </p>
        )}
        {check && (
          <>
            <div
              data-testid="power-status"
              data-ok={check.ok}
              className={`rounded px-3 py-2 font-medium ${check.ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}
            >
              {check.ok ? t('power.ok') : t('power.notOk')}
            </div>

            {m && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border bg-white p-3 text-sm">
                <dt>{t('power.pBackup')}</dt>
                <dd data-testid="p-backup">{num(m.p_backup_w, 0)} Вт</dd>
                <dt>{t('power.sBackup')}</dt>
                <dd>{num(m.s_backup_va, 0)} ВА</dd>
                <dt>{t('power.pStart')}</dt>
                <dd>{num(m.p_start_w, 0)} Вт</dd>
                <dt>{t('power.iBackup')}</dt>
                <dd>{num(m.i_backup_a)} А</dd>
                {m.gen_required_kva != null && (
                  <>
                    <dt>{t('power.genRequired')}</dt>
                    <dd>
                      {num(m.gen_required_kva)} кВА / {num(m.gen_required_kw)} кВт
                    </dd>
                  </>
                )}
                {m.inverter_capacity_w != null && (
                  <>
                    <dt>{t('power.inverterPower')}</dt>
                    <dd>{num(m.inverter_capacity_w, 0)} Вт</dd>
                  </>
                )}
                {m.autonomy_h != null && (
                  <>
                    <dt>{t('power.autonomy')}</dt>
                    <dd data-testid="autonomy">{num(m.autonomy_h)} ч</dd>
                    <dt>{t('power.dcCurrent')}</dt>
                    <dd>{num(m.battery_dc_a, 0)} А</dd>
                  </>
                )}
              </dl>
            )}

            <ul className="flex flex-col gap-1" data-testid="findings">
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

            <h2 className="font-medium">{t('power.components')}</h2>
            <table className="w-full rounded border bg-white text-sm" data-testid="components">
              <tbody>
                {check.components.map((c, i) => (
                  <tr key={i} className="border-t align-top">
                    <td className="p-1 text-slate-500">{c.note}</td>
                    <td className="p-1">
                      {c.product ? (
                        <>
                          {c.product.brand.name} {c.product.sku}
                        </>
                      ) : (
                        <span className="text-red-700">{t('power.noProduct')}</span>
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
                  <td className="p-1 text-right" data-testid="power-total">
                    {check.total_price} ₴
                  </td>
                </tr>
              </tbody>
            </table>

            <div className="flex items-center gap-3">
              <button
                className="btn btn-primary"
                data-testid="apply"
                disabled={!check.ok || check.components.length === 0}
                onClick={() => void apply()}
              >
                {t('power.apply')}
              </button>
              {applied !== null && (
                <Link
                  className="text-blue-700"
                  data-testid="applied-link"
                  to={`/projects/${id}/board`}
                >
                  {t('power.openBoard')}
                </Link>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
