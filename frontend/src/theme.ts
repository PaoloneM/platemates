import { createTheme } from '@mui/material/styles'

// The app's palette, shared with the Keycloak login theme
// (keycloak/themes/mymenu/login/resources/css/mymenu.css). Light and dark follow the system.
export const theme = createTheme({
  cssVariables: { colorSchemeSelector: 'media' },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: '#2e7d4f', dark: '#24643f', contrastText: '#fbfaf7' },
        secondary: { main: '#b5651d' },
        background: { default: '#fbfaf7', paper: '#ffffff' },
        text: { primary: '#1f2421', secondary: '#66706a' },
        divider: '#e4e1da',
      },
    },
    dark: {
      palette: {
        primary: { main: '#4fa874', dark: '#63b885', contrastText: '#0f1311' },
        secondary: { main: '#e0975a' },
        background: { default: '#161917', paper: '#1e2220' },
        text: { primary: '#e8ebe9', secondary: '#9aa49e' },
        divider: '#2c312e',
      },
    },
  },
  shape: { borderRadius: 10 },
  typography: {
    // System fonts: nothing to download, works offline, native look on every platform.
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    h1: { fontSize: '1.75rem', fontWeight: 600 },
    h2: { fontSize: '1.4rem', fontWeight: 600 },
    h3: { fontSize: '1.15rem', fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 500 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiCard: { defaultProps: { variant: 'outlined' } },
    MuiTextField: { defaultProps: { fullWidth: true } },
  },
})
