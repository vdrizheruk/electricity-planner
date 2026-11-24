import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/client';
import {
  panels as panelsApi,
  type AutolayoutOptions,
  type LayoutVersion,
} from '../../../api/endpoints';

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-label={title}
    >
      <div className="w-96 max-w-full rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-3 flex items-center">
          <h2 className="flex-1 font-semibold">{title}</h2>
          <button className="btn" onClick={onClose}>
            {t('board.close')}
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function AutolayoutDialog({
  panelId,
  onClose,
  onDone,
}: {
  panelId: number;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [opts, setOpts] = useState<AutolayoutOptions>({
    voltage_relay: true,
    spd: '2',
    fire_rcd: false,
    reserve_pct: 20,
    pick_enclosure: true,
  });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError('');
    try {
      await panelsApi.autolayout(panelId, opts);
      await onDone();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t('board.autolayout')} onClose={onClose}>
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-amber-700">{t('board.autolayoutWarn')}</p>
        <label>
          <input
            type="checkbox"
            checked={opts.voltage_relay}
            onChange={(e) => setOpts({ ...opts, voltage_relay: e.target.checked })}
          />{' '}
          {t('board.voltageRelay')}
        </label>
        <label>
          {t('board.spd')}{' '}
          <select
            className="input"
            value={opts.spd}
            onChange={(e) => setOpts({ ...opts, spd: e.target.value as AutolayoutOptions['spd'] })}
          >
            <option value="none">{t('board.spdNone')}</option>
            <option value="1+2">{t('board.spd1')}</option>
            <option value="2">{t('board.spd2')}</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={opts.fire_rcd}
            onChange={(e) => setOpts({ ...opts, fire_rcd: e.target.checked })}
          />{' '}
          {t('board.fireRcd')}
        </label>
        <label>
          {t('board.reserve')}{' '}
          <input
            className="input w-20"
            type="number"
            min={0}
            max={100}
            value={opts.reserve_pct}
            onChange={(e) => setOpts({ ...opts, reserve_pct: Number(e.target.value) })}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={opts.pick_enclosure}
            onChange={(e) => setOpts({ ...opts, pick_enclosure: e.target.checked })}
          />{' '}
          {t('board.pickEnclosure')}
        </label>
        {error && <p className="text-red-600">{error}</p>}
        <button
          className="btn btn-primary justify-center"
          disabled={busy}
          onClick={() => void run()}
        >
          {t('board.run')}
        </button>
      </div>
    </Modal>
  );
}

export function VersionsDialog({
  panelId,
  onClose,
  flush,
  onDone,
}: {
  panelId: number;
  onClose: () => void;
  flush: () => Promise<void>;
  onDone: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<LayoutVersion[]>([]);
  const [note, setNote] = useState('');

  useEffect(() => {
    void panelsApi.versions(panelId).then(setItems);
  }, [panelId]);

  return (
    <Modal title={t('board.versions')} onClose={onClose}>
      <div className="mb-3 flex gap-2">
        <input
          className="input flex-1"
          placeholder={t('board.note')}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          className="btn btn-primary"
          onClick={() =>
            void flush()
              .then(() => panelsApi.createVersion(panelId, note))
              .then((v) => {
                setItems((x) => [v, ...x]);
                setNote('');
              })
          }
        >
          {t('board.snapshot')}
        </button>
      </div>
      <ul className="max-h-64 divide-y overflow-y-auto text-sm">
        {items.map((v) => (
          <li key={v.id} className="flex items-center gap-2 py-1">
            <span className="flex-1">
              #{v.number} {v.note}{' '}
              <span className="text-xs text-slate-500">
                {new Date(v.created_at).toLocaleString()}
              </span>
            </span>
            <button
              className="btn"
              onClick={() => void panelsApi.restoreVersion(v.id).then(onDone).then(onClose)}
            >
              {t('board.restore')}
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
