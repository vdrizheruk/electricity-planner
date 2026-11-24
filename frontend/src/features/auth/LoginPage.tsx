import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { auth, type User } from '../../api/endpoints';

export function LoginPage({ onUser }: { onUser: (u: User) => void }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    try {
      const u = await (mode === 'login' ? auth.login : auth.register)(email, password);
      onUser(u);
      nav('/');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="mx-auto mt-16 flex w-80 flex-col gap-3">
      <h1 className="text-xl font-semibold">
        {t(mode === 'login' ? 'auth.login' : 'auth.register')}
      </h1>
      <input
        className="input"
        type="email"
        required
        placeholder={t('auth.email')}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <input
        className="input"
        type="password"
        required
        placeholder={t('auth.password')}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button className="btn btn-primary justify-center" type="submit">
        {t(mode === 'login' ? 'auth.login' : 'auth.register')}
      </button>
      <button
        type="button"
        className="text-sm text-blue-700"
        onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
      >
        {t(mode === 'login' ? 'auth.noAccount' : 'auth.haveAccount')}
      </button>
    </form>
  );
}
