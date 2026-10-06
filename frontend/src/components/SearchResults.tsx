import DownloadIcon from '@mui/icons-material/Download'
import OpenIcon from '@mui/icons-material/OpenInNew'
import { Alert, Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import type { SearchResult } from '../api'
import { useLabels } from '../labels'

type Local = Extract<SearchResult, { kind: 'book' | 'shared' }>
type Web = Extract<SearchResult, { kind: 'web' }>

/**
 * Results of "help me search": the family's own recipes, shared ones from other families, and
 * recipe pages found on the web (each already checked to exist and hold one recipe).
 */
export function SearchResults({
  results,
  notice,
  onImport,
  disabled,
}: {
  results: SearchResult[]
  notice?: string
  onImport: (url: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const labels = useLabels()
  const book = results.filter((r): r is Local => r.kind === 'book')
  const shared = results.filter((r): r is Local => r.kind === 'shared')
  const web = results.filter((r): r is Web => r.kind === 'web')

  const local = (items: Local[], title: string) =>
    items.length > 0 && (
      <Box>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          {title}
        </Typography>
        <Stack spacing={1}>
          {items.map((r) => (
            <Card key={r.recipe}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 1.5, '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography noWrap sx={{ fontWeight: 600 }}>
                    {r.title}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {labels.course(r.course)}
                    {r.total_minutes ? ` · ${t('recipe.minutes', { count: r.total_minutes })}` : ''}
                  </Typography>
                </Box>
                <Button size="small" component={RouterLink} to={`/recipes/${r.recipe}`}>
                  {t('search.open')}
                </Button>
              </CardContent>
            </Card>
          ))}
        </Stack>
      </Box>
    )

  return (
    <Stack spacing={2}>
      {results.length === 0 && <Typography color="text.secondary">{t('search.nothing')}</Typography>}
      {local(book, t('search.inBook'))}
      {local(shared, t('search.fromFamilies'))}
      {web.length > 0 && (
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t('search.fromWeb')}
          </Typography>
          <Stack spacing={1}>
            {web.map((r) => (
              <Card key={r.url}>
                <CardContent
                  sx={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    gap: 1.5,
                    py: 1.5,
                    '&:last-child': { pb: 1.5 },
                  }}
                >
                  <Box sx={{ flex: 1, minWidth: 200 }}>
                    <Typography sx={{ fontWeight: 600 }}>{r.title}</Typography>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mt: 0.5 }}>
                      <Typography variant="body2" color="text.secondary">
                        {r.site}
                      </Typography>
                      <Chip size="small" variant="outlined" label={r.dish} />
                    </Stack>
                  </Box>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" href={r.url} target="_blank" rel="noopener noreferrer" endIcon={<OpenIcon />}>
                      {t('search.view')}
                    </Button>
                    <Button size="small" variant="contained" startIcon={<DownloadIcon />} disabled={disabled}
                      onClick={() => onImport(r.url)}>
                      {t('search.import')}
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        </Box>
      )}
      {notice && <Alert severity="info">{t(`search.notice.${notice}`, { defaultValue: '' })}</Alert>}
    </Stack>
  )
}
