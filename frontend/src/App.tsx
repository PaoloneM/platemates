import { useTranslation } from 'react-i18next'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { useAuth } from './auth/context'
import { HomePage } from './pages/HomePage'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { NoFamilyPage } from './pages/NoFamilyPage'

/** Everything except invitations requires a signed-in user who belongs to a family. */
function Protected({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const { me, error } = useAuth()
  const location = useLocation()

  if (error) return <p className="notice bad page">{t('health.unreachable', { error })}</p>
  if (!me) return <p className="muted page">{t('common.loading')}</p>
  if (!me.authenticated) return <LoginPage next={location.pathname + location.search} />
  if (me.families.length === 0) return <NoFamilyPage />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route
            path="*"
            element={
              <Protected>
                <HomePage />
              </Protected>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
