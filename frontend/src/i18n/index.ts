// Interface translations. Italian is the default; English is available. The language is taken
// from the user's last choice (localStorage), then the browser, then falls back to Italian.
// Add a language by adding a locale file here and to `supportedLanguages`.

import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import it from './locales/it.json'

export const supportedLanguages = { it: 'Italiano', en: 'English' } as const

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { it: { translation: it }, en: { translation: en } },
    fallbackLng: 'it',
    supportedLngs: Object.keys(supportedLanguages),
    nonExplicitSupportedLngs: true,
    detection: { order: ['localStorage', 'navigator'], caches: ['localStorage'] },
    interpolation: { escapeValue: false },
  })

// Keep <html lang> and the backend's Accept-Language in step with the chosen language.
i18n.on('languageChanged', (lng) => document.documentElement.setAttribute('lang', lng))
document.documentElement.setAttribute('lang', i18n.resolvedLanguage ?? 'it')

export default i18n
