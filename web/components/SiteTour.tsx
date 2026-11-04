'use client'

import { driver, type DriveStep } from 'driver.js'
import 'driver.js/dist/driver.css'
import { CircleHelp } from 'lucide-react'

export const TOUR_DONE_KEY = 'cvs-radar-tour-done'

// Phones hide the inline filter bar and use the quick row + floating button
// instead (same 640px breakpoint as shelf.css), so the tour points at those.
function tourSteps(): DriveStep[] {
  const phone = matchMedia('(max-width: 640px)').matches
  const steps: DriveStep[] = [
    { element: '.sl-hero', popover: { title: '歡迎來到超商雷達！', description: '我們把 PTT 超商板的心得整理成分數，幫你挑超商新品。' } },
    { element: '.sl-searchwrap', popover: { title: '搜尋', description: '輸入商品名或品牌，例如「布丁」、「全家」。' } },
    ...(phone
      ? [
          { element: '.sl-quick', popover: { title: '快速篩選', description: '點一下，只看某個品牌或分類。' } },
          { element: '.sl-fab', popover: { title: '排序和更多篩選', description: '排序、日期、只看素食，都在這個按鈕裡。' } },
        ]
      : [{ element: '.sl-controls', popover: { title: '篩選和排序', description: '用分類、品牌、日期縮小範圍，再選排序方式。' } }]),
    { element: '.sl-label .sl-score', popover: { title: '分數', description: '0–100 分，越高代表越多人推。「—」是心得太少，先不給分。' } },
    { element: '.sl-label .sl-rowbtn', popover: { title: '點開看心得', description: '點卡片可以看網友怎麼說，還有 PTT 原文連結。' } },
    { element: '.sl-tour-btn', popover: { title: '想再看一次？', description: '隨時點這個問號，就能重看導覽。' } },
  ]
  // An empty search result has no card to point at; skip what isn't on the page.
  return steps.filter((step) => typeof step.element === 'string' && document.querySelector(step.element))
}

export function startTour() {
  const tour = driver({
    steps: tourSteps(),
    showProgress: true,
    progressText: '{{current}} / {{total}}',
    nextBtnText: '下一步',
    prevBtnText: '上一步',
    doneBtnText: '完成',
    popoverClass: 'sl-tour',
    // Closing early counts as seen too: a visitor who skipped doesn't want it back.
    onDestroyed: () => {
      try {
        localStorage.setItem(TOUR_DONE_KEY, '1')
      } catch {}
    },
  })
  tour.drive()
}

export function tourSeen(): boolean {
  try {
    return localStorage.getItem(TOUR_DONE_KEY) !== null
  } catch {
    // Storage blocked: showing it on every visit would be worse than never.
    return true
  }
}

export default function TourButton() {
  return (
    <button type="button" className="sl-theme-toggle sl-tour-btn" onClick={startTour} aria-label="網站導覽">
      <CircleHelp size={18} aria-hidden="true" />
    </button>
  )
}
