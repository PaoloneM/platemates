import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Health, type Paginated, type Recipe } from '../api'
import { useAuth } from '../auth/context'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { LogoutButton } from '../components/LogoutButton'
import { Logo } from '../components/Logo'

function HealthPanel() {
  const { t } = useTranslation()
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    api<Health>('/health/?deep=1')
      .then(setHealth)
      .catch(() => setHealth({ backend: { ok: false } }))
  }, [])

  if (!health) return null
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

  useEffect(() => {
    api<Paginated<Recipe>>('/recipes/').then((page) => setRecipes(page.results))
  }, [])

  if (!recipes) return <p className="muted">{t('recipes.loading')}</p>
  if (recipes.length === 0) return <p className="muted">{t('recipes.empty')}</p>
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

export function HomePage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  if (!me?.authenticated) return null
  const family = me.families[0]
  const name = me.user.first_name || me.user.email

  return (
    <>
      <header className="app-header">
        <div className="brand">
          <Logo size={32} />
          <span>{family.name}</span>
        </div>
        <div className="user-menu">
          <span className="muted">{name}</span>
          <LanguageSwitcher />
          <LogoutButton />
        </div>
      </header>
      <main className="page">
        <h2>{t('recipes.title')}</h2>
        <RecipeList />
        <HealthPanel />
      </main>
    </>
  )
}
