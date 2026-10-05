import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Health, type Paginated, type Recipe } from './api'
import { supportedLanguages } from './i18n'

function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return (
    <label className="language">
      {t('app.language')}{' '}
      <select value={i18n.resolvedLanguage} onChange={(e) => i18n.changeLanguage(e.target.value)}>
        {Object.entries(supportedLanguages).map(([code, name]) => (
          <option key={code} value={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}

function HealthPanel() {
  const { t } = useTranslation()
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Health>('/health/?deep=1')
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="status bad">{t('health.unreachable', { error })}</p>
  if (!health) return <p className="status">{t('health.checking')}</p>
  return (
    <ul className="services">
      {Object.entries(health).map(([name, report]) => (
        <li key={name} className={report.ok ? 'ok' : 'bad'} title={report.error ?? ''}>
          {t(`health.service.${name}`, { defaultValue: name })}:{' '}
          {report.ok ? t('health.ok') : t('health.unavailable')}
        </li>
      ))}
    </ul>
  )
}

function RecipeList() {
  const { t } = useTranslation()
  const [recipes, setRecipes] = useState<Recipe[] | null>(null)
  const [needsLogin, setNeedsLogin] = useState(false)

  useEffect(() => {
    api<Paginated<Recipe>>('/recipes/')
      .then((page) => setRecipes(page.results))
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setNeedsLogin(true)
      })
  }, [])

  if (needsLogin) {
    return (
      <p>
        <a href="/api/auth/login/?next=/">{t('recipes.signIn')}</a> {t('recipes.signInToSee')}
      </p>
    )
  }
  if (!recipes) return <p>{t('recipes.loading')}</p>
  if (recipes.length === 0) return <p>{t('recipes.empty')}</p>
  return (
    <ul className="recipes">
      {recipes.map((r) => (
        <li key={r.id}>
          <strong>{r.title}</strong>
          <span>
            {t('recipes.servings', { count: r.servings })}
            {r.total_minutes ? ` · ${t('recipes.minutes', { count: r.total_minutes })}` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}

export default function App() {
  const { t } = useTranslation()
  return (
    <main>
      <header>
        <h1>{t('app.title')}</h1>
        <HealthPanel />
        <LanguageSwitcher />
      </header>
      <section>
        <h2>{t('recipes.title')}</h2>
        <RecipeList />
      </section>
    </main>
  )
}
