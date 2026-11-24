import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { projects, type Project } from '../../api/endpoints';

export function ProjectsPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<Project[]>([]);
  const [name, setName] = useState('');

  useEffect(() => {
    void projects.list().then(setItems);
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    const p = await projects.create({ name });
    setItems((x) => [p, ...x]);
    setName('');
  }

  return (
    <div className="mx-auto max-w-3xl p-4">
      <h1 className="mb-3 text-xl font-semibold">{t('projects.title')}</h1>
      <form onSubmit={(e) => void create(e)} className="mb-4 flex gap-2">
        <input
          className="input flex-1"
          required
          placeholder={t('projects.name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">
          {t('projects.create')}
        </button>
      </form>
      {items.length === 0 && <p className="text-slate-500">{t('projects.empty')}</p>}
      <ul className="divide-y rounded border bg-white">
        {items.map((p) => (
          <li key={p.id} className="flex items-center gap-3 px-3 py-2">
            <Link className="flex-1 text-blue-700" to={`/projects/${p.id}`}>
              {p.name}
            </Link>
            <button
              className="btn"
              onClick={() => {
                if (confirm(t('projects.confirmRemove')))
                  void projects
                    .remove(p.id)
                    .then(() => setItems((x) => x.filter((i) => i.id !== p.id)));
              }}
            >
              {t('projects.remove')}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
