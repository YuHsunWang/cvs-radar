'use client'

import { useEffect, useRef, useState } from 'react'
import { SquarePlus, X } from 'lucide-react'
import { trackInstallChoice, trackInstallPrompt } from '@/lib/analytics'
import { installPlatform, type InstallPlatform } from '@/lib/install'

// Android: the captured prompt (lib/install.ts). iPhone has no such event, so
// there the button explains the Share-sheet steps instead.
type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }

declare global {
  interface Window {
    __installPrompt?: InstallPromptEvent | null
  }
}

function currentPlatform(): InstallPlatform {
  const standalone =
    matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
  return installPlatform(navigator.userAgent, standalone, navigator.maxTouchPoints)
}

export default function InstallButton() {
  const [platform, setPlatform] = useState<InstallPlatform>('installed')
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    setPlatform(currentPlatform())
    const installed = () => setPlatform('installed')
    addEventListener('appinstalled', installed)
    return () => removeEventListener('appinstalled', installed)
  }, [])

  if (platform === 'installed') return null

  async function onClick() {
    const prompt = window.__installPrompt
    if (prompt) {
      trackInstallPrompt('android')
      await prompt.prompt()
      const { outcome } = await prompt.userChoice
      trackInstallChoice(outcome)
      window.__installPrompt = null // a prompt can only be shown once
      return
    }
    trackInstallPrompt(platform)
    dialog.current?.showModal()
  }

  return (
    <>
      <button type="button" className="sl-theme-toggle sl-a2hs-btn" onClick={onClick} aria-label="加到手機桌面">
        <SquarePlus size={18} aria-hidden="true" />
      </button>
      <dialog ref={dialog} className="sl-a2hs-dialog" aria-labelledby="sl-a2hs-title" onClick={(e) => e.target === e.currentTarget && dialog.current?.close()}>
        <div className="sl-a2hs-body">
          <button type="button" className="sl-a2hs-close" onClick={() => dialog.current?.close()} aria-label="關閉">
            <X size={18} aria-hidden="true" />
          </button>
          <h2 id="sl-a2hs-title">加到手機桌面</h2>
          {platform === 'ios' ? (
            <>
              {/* Recorded in iPhone Chrome; contacts and home screen left out. Loads only once the dialog opens. */}
              <img
                className="sl-a2hs-demo"
                src={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/a2hs-ios.gif`}
                alt="示範：點分享、點加入主畫面、點加入，桌面就多了超商雷達"
                width={300}
                height={652}
                loading="lazy"
              />
            <ol>
              <li>點瀏覽器的「分享」按鈕（方框加向上箭頭；Safari 在畫面下方，Chrome 在網址列右邊）</li>
              <li>往下滑，點「加入主畫面」</li>
              <li>按右上角「加入」</li>
            </ol>
            </>
          ) : (
            <ol>
              <li>點瀏覽器右上角的「⋮」選單</li>
              <li>點「加到主畫面」或「安裝應用程式」</li>
              <li>按「新增」</li>
            </ol>
          )}
          <p>之後從桌面點「超商雷達」，就像 App 一樣直接打開。</p>
        </div>
      </dialog>
    </>
  )
}
