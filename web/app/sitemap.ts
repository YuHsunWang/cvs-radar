import type { MetadataRoute } from 'next'
import { getSiteUrl } from '@/lib/site-url'

export const dynamic = 'force-static'

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = getSiteUrl()
  return [{ url: siteUrl.href }, { url: new URL('soft-serve/', siteUrl).href }]
}
