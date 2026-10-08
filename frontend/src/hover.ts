import type { SxProps, Theme } from '@mui/material/styles'

// Secondary actions (configure, clear) that would clutter the screen when always visible. With a
// mouse or a trackpad they appear on hovering their area, or when focus reaches it from the
// keyboard; on touch screens, where nothing hovers, they are always shown. The media query asks
// the browser about the pointer itself, not about the kind of device.
//
// Each area names its own actions (`className`), so that nested areas stay independent: hovering
// a day reveals the day's actions, not those of the meal cards inside it.
export function revealOnHover(className: string): SxProps<Theme> {
  return {
    '@media (hover: hover) and (pointer: fine)': {
      [`& .${className}`]: { opacity: 0, transition: 'opacity 120ms' },
      [`&:hover .${className}, &:focus-within .${className}`]: { opacity: 1 },
    },
  }
}

export const DAY_ACTION = 'day-action'
export const MEAL_ACTION = 'meal-action'
