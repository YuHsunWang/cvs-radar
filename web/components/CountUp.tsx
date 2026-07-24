'use client'

import { useEffect, useRef, useState } from 'react'

type CountUpProps = {
  /** Final value to count up to. */
  end: number
  /** Value shown before the animation starts. */
  from?: number
  /** Animation duration in milliseconds. */
  durationMs?: number
}

/**
 * react-bits-style CountUp — animates a number from `from` to `end` the first
 * time it scrolls into view. Zero dependencies; respects prefers-reduced-motion
 * (jumps straight to the final value for users who opt out of animation).
 */
export default function CountUp({ end, from = 0, durationMs = 900 }: CountUpProps) {
  const [value, setValue] = useState(from)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(end)
      return
    }

    const run = () => {
      if (started.current) return
      started.current = true
      const start = performance.now()
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / durationMs)
        const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
        setValue(Math.round(from + (end - from) * eased))
        if (t < 1) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            run()
            observer.disconnect()
          }
        }
      },
      { threshold: 0.4 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [end, from, durationMs])

  return <span ref={ref}>{value}</span>
}
