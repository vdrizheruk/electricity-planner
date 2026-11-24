import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { ru } from './locales/ru';
import { uk } from './locales/uk';

function initial(): string {
  try {
    const saved = localStorage.getItem('lang');
    if (saved === 'ru' || saved === 'uk') return saved;
  } catch {
    /* storage unavailable */
  }
  return 'ru';
}

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, uk: { translation: uk } },
  lng: initial(),
  fallbackLng: 'ru',
  interpolation: { escapeValue: false },
});

export function setLanguage(lng: 'ru' | 'uk'): void {
  try {
    localStorage.setItem('lang', lng);
  } catch {
    /* ignore */
  }
  document.documentElement.lang = lng;
  void i18n.changeLanguage(lng);
}

export default i18n;
