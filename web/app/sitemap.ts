import type { MetadataRoute } from 'next'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseDataPayload } from '@/lib/data'
import { pageProducts, productPagePath } from '@/lib/product-page'
import { getSiteUrl } from '@/lib/site-url'

export const dynamic = 'force-static'

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = getSiteUrl()
  const { products } = parseDataPayload(readFileSync(join(process.cwd(), 'public', 'data.json'), 'utf8'))
  return [
    { url: siteUrl.href },
    ...pageProducts(products).map((product) => ({
      // The path is relative so it lands under the site URL's own path.
      url: new URL(productPagePath(product).slice(1), siteUrl).href,
      ...(product.latestDate ? { lastModified: product.latestDate } : {}),
    })),
  ]
}
