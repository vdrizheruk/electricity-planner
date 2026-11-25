import { useTranslation } from 'react-i18next';
import type { SimResult, SimSwitches } from '../../../api/endpoints';
import { SOURCE_COLOR } from './DiagramView';

interface Props {
  switches: SimSwitches;
  onChange: (s: SimSwitches) => void;
  result: SimResult | null;
  error: string;
  hasGenerator: boolean;
  hasInverter: boolean;
  hasPv: boolean;
}

const kw = (w: number) => `${(w / 1000).toFixed(1)} кВт`;

export function SimPanel({
  switches,
  onChange,
  result,
  error,
  hasGenerator,
  hasInverter,
  hasPv,
}: Props) {
  const { t } = useTranslation();
  const set = (patch: Partial<SimSwitches>) => onChange({ ...switches, ...patch });
  const toggle = (key: 'grid' | 'generator' | 'inverter' | 'pv', label: string, enabled = true) => (
    <label className={`flex items-center gap-1 ${enabled ? '' : 'opacity-40'}`}>
      <input
        type="checkbox"
        data-testid={`sim-${key}`}
        disabled={!enabled}
        checked={switches[key]}
        onChange={(e) => set({ [key]: e.target.checked })}
      />
      {label}
    </label>
  );
  return (
    <div data-testid="sim-panel" className="border-b bg-amber-50 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-4">
        <strong>{t('board.sim.title')}</strong>
        {toggle('grid', t('board.sim.grid'))}
        {toggle('generator', t('board.sim.generator'), hasGenerator)}
        {toggle('inverter', t('board.sim.inverter'), hasInverter)}
        {toggle('pv', t('board.sim.pv'), hasPv)}
        <label className="flex items-center gap-1">
          {t('board.sim.position')}
          <select
            data-testid="sim-position"
            className="input"
            value={switches.position}
            onChange={(e) => set({ position: e.target.value as SimSwitches['position'] })}
          >
            <option value="auto">{t('board.sim.auto')}</option>
            <option value="grid">I · {t('board.sim.grid')}</option>
            <option value="gen">II · {t('board.sim.generator')}</option>
            <option value="off">0</option>
          </select>
        </label>
        {switches.pv && (
          <label className="flex items-center gap-1">
            {t('board.sim.sun')} {switches.pv_pct}%
            <input
              type="range"
              min={0}
              max={100}
              value={switches.pv_pct}
              onChange={(e) => set({ pv_pct: Number(e.target.value) })}
            />
          </label>
        )}
        {result && (
          <span data-testid="sim-summary" className="ml-auto text-slate-700">
            {t('board.sim.powered')}: {kw(result.powered_w)} · {t('board.sim.dark')}:{' '}
            {kw(result.dark_w)}
            {result.interruption_s !== null && result.interruption_s !== undefined
              ? ` · ${t('board.sim.gap')} ${result.interruption_s} с`
              : ''}
            {result.autonomy_h != null
              ? ` · ${t('board.sim.autonomy')} ${result.autonomy_h.toFixed(1)} ч`
              : ''}
          </span>
        )}
      </div>
      {error && <div className="mt-1 text-red-600">{error}</div>}
      {result && (
        <>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            {result.sources.map((s) => (
              <span
                key={s.name}
                data-testid={`sim-source-${s.name}`}
                data-role={s.role}
                className="rounded border px-2 py-0.5"
                style={{
                  borderColor:
                    s.role === 'feeding' ? (SOURCE_COLOR[s.name] ?? '#16a34a') : '#cbd5e1',
                  opacity: s.role === 'off' ? 0.5 : 1,
                }}
              >
                {t(`board.sim.src.${s.name}`)}: {t(`board.sim.role.${s.role}`)}
                {s.role === 'feeding' || s.load_w > 0
                  ? ` · ${kw(s.load_w)} · ${s.current_a.toFixed(0)} А`
                  : ''}
                {s.utilization_pct != null ? ` · ${s.utilization_pct.toFixed(0)}%` : ''}
              </span>
            ))}
          </div>
          {result.findings.length > 0 && (
            <ul data-testid="sim-findings" className="mt-1 text-xs">
              {result.findings.map((f, i) => (
                <li
                  key={`${f.code}-${i}`}
                  className={
                    f.level === 'error'
                      ? 'text-red-700'
                      : f.level === 'warning'
                        ? 'text-amber-800'
                        : 'text-slate-600'
                  }
                >
                  {f.level === 'error' ? '⛔' : f.level === 'warning' ? '⚠' : 'ℹ'} {f.message}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
