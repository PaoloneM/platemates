import { Card, CardContent, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

/** A card with a title, an optional hint and an optional action, for settings pages. */
export function Section({ id, title, hint, action, children }: {
  id?: string
  title: string
  hint?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <Card id={id} sx={{ scrollMarginTop: 80 }}>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: hint ? 0.5 : 2 }}>
          <Typography variant="h2">{title}</Typography>
          {action}
        </Stack>
        {hint && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {hint}
          </Typography>
        )}
        {children}
      </CardContent>
    </Card>
  )
}
