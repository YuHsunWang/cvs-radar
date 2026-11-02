'use client'

import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { THEME_STORAGE_KEY, type Theme } from '@/lib/theme'

export default function ThemeToggle() {
  // Null until mounted: the server cannot know the theme, so it renders no icon.
  const [theme, setTheme] = useState<Theme | null>(null)

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
    const media = matchMedia('(prefers-color-scheme: dark)')
    const onDeviceChange = (event: MediaQueryListEvent) => {
      try {
        if (localStorage.getItem(THEME_STORAGE_KEY)) return
      } catch {}
      const next = event.matches ? 'dark' : 'light'
      document.documentElement.dataset.theme = next
      setTheme(next)
    }
    media.addEventListener('change', onDeviceChange)
    return () => media.removeEventListener('change', onDeviceChange)
  }, [])

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {}
    setTheme(next)
  }

  return (
    <button
      type="button"
      className="sl-theme-toggle"
      onClick={toggle}
      aria-label={theme === 'dark' ? '切換成亮色主題' : '切換成暗色主題'}
    >
      {theme === 'dark' ? <Sun size={18} aria-hidden="true" /> : theme === 'light' ? <Moon size={18} aria-hidden="true" /> : null}
    </button>
  )
}
