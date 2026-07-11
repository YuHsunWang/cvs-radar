/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''

const nextConfig = {
  output: 'export',
  outputFileTracingRoot: __dirname,
  basePath,
  trailingSlash: true,
}

module.exports = nextConfig
