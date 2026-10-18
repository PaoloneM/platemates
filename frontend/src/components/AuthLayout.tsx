import { Box, Card, CardContent, Stack } from '@mui/material'
import type { ReactNode } from 'react'
import { LanguageSwitcher } from './LanguageSwitcher'
import { Logo } from './Logo'

/** Centered card used by sign-in, invitation and "waiting for an invitation" screens. */
export function AuthLayout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <Stack sx={{ alignItems: 'center', minHeight: '100vh', p: 2 }}>
      <Box sx={{ alignSelf: 'stretch', display: 'flex', justifyContent: 'flex-end' }}>
        <LanguageSwitcher />
      </Box>
      <Card sx={{ width: '100%', maxWidth: wide ? 560 : 420, my: 'auto', borderRadius: 4 }}>
        <CardContent sx={{ p: { xs: 3, sm: 4 }, textAlign: 'center' }}>
          <Stack spacing={2} sx={{ alignItems: 'center' }}>
            <Logo />
            {children}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  )
}
