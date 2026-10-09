import CommunityIcon from '@mui/icons-material/PublicOutlined'
import SystemIcon from '@mui/icons-material/VerifiedOutlined'
import { Chip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { RecipeAuthor } from '../api'

/** Where a recipe comes from: nothing for the team's own, a chip for everything else. */
export function AuthorChip({ author, size = 'small' }: { author: RecipeAuthor; size?: 'small' | 'medium' }) {
  const { t } = useTranslation()
  if (author.kind === 'mine') return null
  if (author.kind === 'system') {
    return <Chip size={size} color="primary" variant="outlined" icon={<SystemIcon />} label={t('community.system')} />
  }
  return (
    <Chip size={size} variant="outlined" icon={<CommunityIcon />}
      label={author.kind === 'team' ? t('community.byTeam', { name: author.name }) : t('community.anonymous')} />
  )
}
