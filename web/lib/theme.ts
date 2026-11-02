export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'cvs-radar-theme'

// Runs inline before first paint, so a dark-mode visitor never sees a white flash.
// The saved choice wins; with none, the device setting decides. Storage can throw
// in private windows, which must fall back to the device setting, not to no theme.
export const themeInitScript = `(function(){var t=null;try{t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})}catch(e){}if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t})()`
