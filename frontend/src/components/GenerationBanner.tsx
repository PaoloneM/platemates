import { Alert, AlertTitle, Button, CircularProgress, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { MenuGeneration } from '../api'
import { generationActive } from '../calendar'

/**
 * What the week's latest generation is doing: running, failed (with a retry), or done with
 * proposals waiting for review (the rationale, and accept or reject everything at once).
 */
export function GenerationBanner({ generation, pending, busy, onAcceptAll, onRejectAll, onRetry }: {
  generation: MenuGeneration | null
  // The week still has proposals to review.
  pending: boolean
  busy: boolean
  onAcceptAll: () => void
  onRejectAll: () => void
  onRetry: () => void
}) {
  const { t } = useTranslation()
  if (!generation) return null
  if (generationActive(generation)) {
    return (
      <Alert severity="info" icon={<CircularProgress size={20} />}>
        <AlertTitle>{t('generation.running')}</AlertTitle>
        {t('generation.runningHint')}
      </Alert>
    )
  }
  if (generation.status === 'failed') {
    return (
      <Alert severity="error" action={<Button color="inherit" size="small" onClick={onRetry} disabled={busy}>{t('generation.retry')}</Button>}>
        <AlertTitle>{t('generation.failed')}</AlertTitle>
        <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{generation.error}</Typography>
      </Alert>
    )
  }
  if (!pending) return null
  const unplanned = generation.result?.unplanned.length ?? 0
  return (
    <Alert severity="success" icon={false} sx={{ '& .MuiAlert-message': { width: '100%' } }}>
      <AlertTitle>{t('generation.done')}</AlertTitle>
      {generation.result?.rationale && <Typography variant="body2" sx={{ mb: 1 }}>{generation.result.rationale}</Typography>}
      {unplanned > 0 && (
        <Typography variant="body2" sx={{ mb: 1 }}>{t('generation.unplanned', { count: unplanned })}</Typography>
      )}
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t('generation.reviewHint')}</Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
        <Button variant="contained" size="small" onClick={onAcceptAll} disabled={busy}>{t('generation.acceptAll')}</Button>
        <Button color="inherit" size="small" onClick={onRejectAll} disabled={busy}>{t('generation.rejectAll')}</Button>
      </Stack>
    </Alert>
  )
}
