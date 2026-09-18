import { afterEach, describe, expect, it } from 'vitest'
import { getSiteUrl } from './site-url'

const KEYS = ['NEXT_PUBLIC_SITE_URL', 'VERCEL_PROJECT_PRODUCTION_URL', 'VERCEL_URL'] as const

afterEach(() => {
  for (const key of KEYS) delete process.env[key]
})

describe('getSiteUrl', () => {
  it('prefers the stable production domain over the per-deployment hostname', () => {
    // The whole point of the metadata base: og:image has to resolve to a URL a
    // link scraper can fetch anonymously. Per-deployment hostnames sit behind
    // deployment protection and answer with a 302, which renders as a broken
    // preview card. Flip these two and social previews break again.
    process.env.VERCEL_PROJECT_PRODUCTION_URL = 'cvs-radar.vercel.app'
    process.env.VERCEL_URL = 'cvs-radar-4uhegozzx-shane-s-projects7.vercel.app'

    expect(getSiteUrl().href).toBe('https://cvs-radar.vercel.app/')
  })

  it('falls back to the deployment hostname when no production domain is exposed', () => {
    process.env.VERCEL_URL = 'cvs-radar-4uhegozzx-shane-s-projects7.vercel.app'

    expect(getSiteUrl().href).toBe('https://cvs-radar-4uhegozzx-shane-s-projects7.vercel.app/')
  })

  it('lets an explicit site URL override both, so the Pages mirror keeps its own base', () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://yuhsunwang.github.io/cvs-radar'
    process.env.VERCEL_PROJECT_PRODUCTION_URL = 'cvs-radar.vercel.app'

    expect(getSiteUrl().href).toBe('https://yuhsunwang.github.io/cvs-radar/')
  })

  it('falls back to localhost when nothing is configured', () => {
    expect(getSiteUrl().href).toBe('http://localhost:3000/')
  })
})
