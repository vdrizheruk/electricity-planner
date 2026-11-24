import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { auth, type User } from './api/endpoints';
import { setLanguage } from './i18n';
import { LoginPage } from './features/auth/LoginPage';
import { ProjectsPage } from './features/projects/ProjectsPage';
import { ProjectPage } from './features/projects/ProjectPage';
import { BoardPage } from './features/board/BoardPage';

export function App() {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) return <div className="p-6">{t('app.loading')}</div>;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b bg-white px-4 py-2">
        <Link to="/" className="font-semibold">
          ⚡ {t('app.name')}
        </Link>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <select
            aria-label={t('app.lang')}
            className="input"
            value={i18n.language}
            onChange={(e) => setLanguage(e.target.value as 'ru' | 'uk')}
          >
            <option value="ru">RU</option>
            <option value="uk">UK</option>
          </select>
          {user && (
            <>
              <span className="hidden sm:inline text-slate-500">{user.email}</span>
              <button
                className="btn"
                onClick={() =>
                  void auth.logout().then(() => {
                    setUser(null);
                    nav('/login');
                  })
                }
              >
                {t('app.logout')}
              </button>
            </>
          )}
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Routes>
          <Route path="/login" element={<LoginPage onUser={setUser} />} />
          {user ? (
            <>
              <Route path="/" element={<ProjectsPage />} />
              <Route path="/projects/:id" element={<ProjectPage />} />
              <Route path="/projects/:id/board" element={<BoardPage />} />
            </>
          ) : (
            <Route path="*" element={<Navigate to="/login" replace />} />
          )}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
