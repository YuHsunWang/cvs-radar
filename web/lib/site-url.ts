const localSiteUrl = 'http://localhost:3000'

export function getSiteUrl(): URL {
  const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL
  const vercelUrl = process.env.VERCEL_URL
  const deployUrl = configuredUrl ?? (vercelUrl ? `https://${vercelUrl}` : localSiteUrl)
  return new URL(deployUrl.endsWith('/') ? deployUrl : `${deployUrl}/`)
}
