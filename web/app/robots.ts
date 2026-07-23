import type { MetadataRoute } from 'next'
import { getSiteUrl } from '@/lib/site-url'

export const dynamic = 'force-static'

export default function robots(): MetadataRoute.Robots {
  const siteUrl = getSiteUrl()
  return {
    rules: { userAgent: '*', allow: '/' },
    sitemap: new URL('sitemap.xml', siteUrl).href,
  }
}
