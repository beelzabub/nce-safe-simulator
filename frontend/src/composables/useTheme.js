import { ref, watch } from 'vue'

const STORAGE_KEY = 'nce-theme'
const theme = ref(localStorage.getItem(STORAGE_KEY) ?? 'dark')

// Apply before first render to avoid flash of unstyled content.
document.documentElement.setAttribute('data-theme', theme.value)

watch(theme, val => {
  document.documentElement.setAttribute('data-theme', val)
  localStorage.setItem(STORAGE_KEY, val)
})

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }
  return { theme, toggle }
}
