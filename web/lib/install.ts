// Chrome-family browsers on Android fire `beforeinstallprompt` once the manifest
// makes the site installable; prompt() then shows the phone's own "add to home
// screen" dialog. Inline in <head>: the event can fire before React hydrates,
// and a listener added later would miss it.
export const installPromptScript = `addEventListener("beforeinstallprompt",function(e){e.preventDefault();window.__installPrompt=e;dispatchEvent(new Event("cvs-install-ready"))})`

export type InstallPlatform = 'installed' | 'ios' | 'other'

export function installPlatform(ua: string, standalone: boolean, touchPoints: number): InstallPlatform {
  if (standalone) return 'installed'
  // iPadOS reports itself as a Mac; touch support gives it away.
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && touchPoints > 1)) return 'ios'
  return 'other'
}
