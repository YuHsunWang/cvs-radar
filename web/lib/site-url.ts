const localSiteUrl = 'http://localhost:3000'

export function getSiteUrl(): URL {
  const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL
  // VERCEL_URL is the per-deployment hostname (cvs-radar-<hash>-<org>.vercel.app).
  // Deployment protection answers those with a 302 to an auth page, so a link
  // scraper following og:image there gets a redirect instead of the PNG and
  // renders a broken preview card. VERCEL_PROJECT_PRODUCTION_URL is the stable
  // production domain and is publicly reachable, so it has to win.
  const productionUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL
  const vercelHost = productionUrl ?? process.env.VERCEL_URL
  const deployUrl = configuredUrl ?? (vercelHost ? `https://${vercelHost}` : localSiteUrl)
  return new URL(deployUrl.endsWith('/') ? deployUrl : `${deployUrl}/`)
}
