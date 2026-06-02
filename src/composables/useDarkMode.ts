export const useDarkMode = () => {
  const isDark = useState('darkMode', () => false)

  const toggleDark = () => {
    isDark.value = !isDark.value
    if (import.meta.client) {
      document.documentElement.classList.toggle('dark', isDark.value)
      localStorage.setItem('darkMode', String(isDark.value))
    }
  }

  const initDark = () => {
    if (import.meta.client) {
      const stored = localStorage.getItem('darkMode')
      if (stored) {
        isDark.value = stored === 'true'
      } else {
        isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
      }
      document.documentElement.classList.toggle('dark', isDark.value)
    }
  }

  return { isDark, toggleDark, initDark }
}
