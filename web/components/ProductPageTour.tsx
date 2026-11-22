'use client'

import { driver } from 'driver.js'
import { useEffect } from 'react'

// Separate from the shelf's key: this one only explains the single page, so
// the shelf's own tour should still run when the visitor goes there.
const PRODUCT_TOUR_DONE_KEY = 'cvs-radar-product-tour-done'

/**
 * Two steps on a first visit from search: what the number means, then where
 * the rest of the shelf is. Kept to two so it explains rather than blocks.
 */
export default function ProductPageTour() {
  useEffect(() => {
    try {
      if (localStorage.getItem(PRODUCT_TOUR_DONE_KEY) !== null) return
    } catch {
      // Storage blocked: showing it on every visit would be worse than never.
      return
    }
    const tour = driver({
      steps: [
        { element: '.sl-label .sl-score', popover: { title: '這是 PTT 網友的評分', description: '0–100 分，越高代表越多人推。下面有網友怎麼說，還有 PTT 原文。' } },
        { element: '.pp-all', popover: { title: '還有更多商品', description: '點這裡回到超商雷達，看同一類的所有商品、搜尋和比較。' } },
      ],
      showProgress: true,
      progressText: '{{current}} / {{total}}',
      nextBtnText: '下一步',
      prevBtnText: '上一步',
      doneBtnText: '知道了',
      popoverClass: 'sl-tour',
      onDestroyed: () => {
        try {
          localStorage.setItem(PRODUCT_TOUR_DONE_KEY, '1')
        } catch {}
      },
    })
    tour.drive()
    return () => tour.destroy()
  }, [])
  return null
}
