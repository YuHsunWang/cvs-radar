import type { MetadataRoute } from 'next'

export const dynamic = 'force-static'

// Makes the site installable: Android browsers then offer their own
// "add to home screen" prompt, which InstallButton triggers. Paths are relative
// to this file so the GitHub Pages mirror (served under a base path) works too.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'CVS Radar 超商雷達',
    short_name: '超商雷達',
    description: '把 PTT 超商板的心得整理成分數，幫你挑超商新品。',
    start_url: '.',
    scope: '.',
    display: 'standalone',
    background_color: '#FCFAF5',
    theme_color: '#0F7C7C',
    lang: 'zh-Hant-TW',
    icons: [
      { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  }
}
