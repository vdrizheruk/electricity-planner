import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { bomApi, projects, type Bom, type Project } from '../../api/endpoints';
import { saveBlob } from '../../shared/saveBlob';

const NBSP = ' ';

/** "1234.5" -> "1 234,50" (string math only: the server already rounded to kopecks). */
function uah(value: string): string {
  const [whole = '0', frac = '00'] = value.split('.');
  const sign = whole.startsWith('-') ? '-' : '';
  const digits = whole.replace('-', '').replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${sign}${digits},${(frac + '00').slice(0, 2)}`;
}

export function BomPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [bom, setBom] = useState<Bom | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'' | 'xlsx' | 'pdf'>('');

  const load = useCallback(async () => {
    try {
      const [p, b] = await Promise.all([projects.get(id), bomApi.get(id)]);
      setProject(p);
      setBom(b);
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function exportAs(kind: 'xlsx' | 'pdf') {
    setBusy(kind);
    try {
      const blob = kind === 'xlsx' ? await bomApi.xlsx(id) : await bomApi.pdf(id);
      saveBlob(`specification-${id}.${kind}`, blob);
      setError('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy('');
    }
  }

  if (!bom || !project) {
    return (
      <div className="p-4">
        {error ? <p className="text-red-700">{error}</p> : t('app.loading')}
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4" data-testid="bom-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t('bomPage.title')}</h1>
        <Link className="btn" to={`/projects/${id}`}>
          {project.name}
        </Link>
        <button
          className="btn btn-primary"
          data-testid="export-xlsx"
          disabled={busy !== ''}
          onClick={() => void exportAs('xlsx')}
        >
          {t('bomPage.xlsx')}
        </button>
        <button
          className="btn btn-primary"
          data-testid="export-pdf"
          disabled={busy !== ''}
          onClick={() => void exportAs('pdf')}
        >
          {t('bomPage.pdf')}
        </button>
        <Link className="btn" to={`/projects/${id}/board`}>
          {t('bomPage.pdfWithDrawings')}
        </Link>
      </div>
      {error && (
        <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">{error}</p>
      )}

      {bom.sections.map((section) => (
        <section key={section.key} data-testid={`section-${section.key}`}>
          <h2 className="mb-1 flex justify-between rounded bg-blue-100 px-2 py-1 font-semibold">
            <span>{section.title}</span>
            <span data-testid={`total-${section.key}`}>{uah(section.total)} ₴</span>
          </h2>
          {section.blocks.map((block) => (
            <div key={block.key} className="mb-3">
              <h3 className="mb-1 text-sm font-medium">
                {block.title}
                {block.estimated && (
                  <span className="ml-2 text-xs font-normal text-amber-700">
                    {t('bomPage.estimated')}
                  </span>
                )}
              </h3>
              <table className="w-full rounded border bg-white text-sm">
                <thead className="bg-slate-100 text-left text-xs text-slate-600">
                  <tr>
                    <th className="p-1">№</th>
                    <th className="p-1">{t('bomPage.brand')}</th>
                    <th className="p-1">{t('bomPage.sku')}</th>
                    <th className="p-1">{t('bomPage.name')}</th>
                    <th className="p-1 text-right">{t('board.qty')}</th>
                    <th className="p-1 text-right">{t('bomPage.price')}</th>
                    <th className="p-1 text-right">{t('board.sum')}</th>
                  </tr>
                </thead>
                <tbody>
                  {block.lines.map((l, i) => (
                    <tr key={l.product_id} className="border-t" data-sku={l.sku}>
                      <td className="p-1">{i + 1}</td>
                      <td className="p-1">{l.brand}</td>
                      <td className="p-1">
                        {l.sku}
                        {l.needs_verification && <span title={t('bomPage.verify')}> *</span>}
                      </td>
                      <td className="p-1">{l.name}</td>
                      <td className="p-1 text-right">
                        {l.qty} {l.unit}
                      </td>
                      <td className="p-1 text-right">{uah(l.unit_price)}</td>
                      <td className="p-1 text-right">{uah(l.total)}</td>
                    </tr>
                  ))}
                  <tr className="border-t font-semibold">
                    <td className="p-1" colSpan={6}>
                      {t('board.total')}: {block.title}
                    </td>
                    <td className="p-1 text-right">{uah(block.total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ))}
        </section>
      ))}

      <table className="ml-auto w-80 text-base" data-testid="bom-summary">
        <tbody>
          {bom.sections.map((s) => (
            <tr key={s.key}>
              <td className="py-0.5">{s.title}</td>
              <td className="text-right">{uah(s.total)} ₴</td>
            </tr>
          ))}
          <tr className="border-t font-bold">
            <td className="py-1">{t('bomPage.grand')}</td>
            <td className="text-right" data-testid="bom-grand">
              {uah(bom.total)} ₴
            </td>
          </tr>
        </tbody>
      </table>

      <p className="text-xs text-slate-500">
        {t('bomPage.disclaimer')}
        {bom.unverified > 0 && ` ${t('bomPage.unverified', { count: bom.unverified })}`}
      </p>
      {bom.missing.map((m) => (
        <p key={m} className="text-sm text-red-700">
          {t('bomPage.missing')}: {m}
        </p>
      ))}
    </div>
  );
}
