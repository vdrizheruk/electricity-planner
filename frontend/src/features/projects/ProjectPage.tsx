import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import {
  groups as groupsApi,
  projects,
  type Calculation,
  type Group,
  type Project,
} from '../../api/endpoints';

export function ProjectPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [calc, setCalc] = useState<Calculation | null>(null);
  const [name, setName] = useState('');
  const [power, setPower] = useState('1000');

  const refresh = useCallback(async () => {
    const [p, g] = await Promise.all([projects.get(id), groupsApi.list(id)]);
    setProject(p);
    setGroups(g);
    setCalc(await projects.calc(id));
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function add(e: FormEvent) {
    e.preventDefault();
    await groupsApi.create(id, { name, power_w: Number(power) });
    setName('');
    await refresh();
  }

  if (!project) return <div className="p-4">{t('app.loading')}</div>;
  return (
    <div className="mx-auto max-w-5xl p-4">
      <div className="mb-3 flex items-center gap-3">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <button className="btn" onClick={() => void groupsApi.autoselect(id).then(refresh)}>
          {t('project.autoselect')}
        </button>
        <Link className="btn" data-testid="power-link" to={`/projects/${id}/power`}>
          {t('power.open')}
        </Link>
        <Link className="btn" data-testid="pv-link" to={`/projects/${id}/pv`}>
          {t('pv.open')}
        </Link>
        <Link className="btn btn-primary" to={`/projects/${id}/board`}>
          {t('project.editor')}
        </Link>
      </div>
      <form onSubmit={(e) => void add(e)} className="mb-3 flex gap-2">
        <input
          className="input flex-1"
          required
          placeholder={t('project.name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="input w-28"
          type="number"
          min={1}
          required
          value={power}
          onChange={(e) => setPower(e.target.value)}
        />
        <button className="btn" type="submit">
          {t('project.addGroup')}
        </button>
      </form>
      <table className="w-full rounded border bg-white text-sm">
        <thead className="bg-slate-50 text-left">
          <tr>
            <th className="p-2">{t('project.name')}</th>
            <th>{t('project.power')}</th>
            <th>{t('project.breaker')}</th>
            <th>{t('project.cable')}</th>
            <th>{t('project.rcd')}</th>
            <th>{t('project.phase')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.id} className="border-t">
              <td className="p-2">{g.name}</td>
              <td>{g.power_w}</td>
              <td>{g.breaker_a !== null ? `${g.curve}${g.breaker_a}` : '—'}</td>
              <td>{g.cable_mm2 ?? '—'}</td>
              <td>{g.rcd_ma ?? '—'}</td>
              <td>{g.assigned_phase || '—'}</td>
              <td>
                <button className="btn" onClick={() => void groupsApi.remove(g.id).then(refresh)}>
                  {t('project.remove')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {calc && calc.findings.length > 0 && (
        <div className="mt-4">
          <h2 className="font-medium">{t('project.findings')}</h2>
          <ul className="list-disc pl-5 text-sm text-amber-700">
            {calc.findings.map((f, i) => (
              <li key={i}>{(f as { message?: string }).message ?? JSON.stringify(f)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
