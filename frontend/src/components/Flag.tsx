import { Box } from '@mui/material'
import { useId } from 'react'

// A language's flag, drawn inline: emoji flags are not shown on Windows (it prints the
// letters). The colours are the flags' own, the one place where they do not come from the
// theme; a thin border keeps white stripes visible on light backgrounds.

function Italy() {
  return (
    <svg viewBox="0 0 3 2" width="100%" height="100%" preserveAspectRatio="none" aria-hidden>
      <rect width="1" height="2" fill="#009246" />
      <rect x="1" width="1" height="2" fill="#ffffff" />
      <rect x="2" width="1" height="2" fill="#ce2b37" />
    </svg>
  )
}

function UnitedKingdom() {
  const id = useId()
  return (
    <svg viewBox="0 0 60 30" width="100%" height="100%" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <clipPath id={`${id}-t`}>
        <path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z" />
      </clipPath>
      <rect width="60" height="30" fill="#012169" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#ffffff" strokeWidth="6" />
      <path d="M0,0 L60,30 M60,0 L0,30" clipPath={`url(#${id}-t)`} stroke="#c8102e" strokeWidth="4" />
      <path d="M30,0 v30 M0,15 h60" stroke="#ffffff" strokeWidth="10" />
      <path d="M30,0 v30 M0,15 h60" stroke="#c8102e" strokeWidth="6" />
    </svg>
  )
}

const FLAGS: Record<string, () => React.JSX.Element> = { it: Italy, en: UnitedKingdom }

export function Flag({ language, size = 20 }: { language: string; size?: number }) {
  const Drawing = FLAGS[language]
  if (!Drawing) return null
  return (
    <Box component="span" sx={{
      display: 'inline-flex', flex: 'none', width: size, height: (size * 2) / 3, borderRadius: '2px',
      overflow: 'hidden', border: 1, borderColor: 'divider', verticalAlign: 'middle',
    }}>
      <Drawing />
    </Box>
  )
}
