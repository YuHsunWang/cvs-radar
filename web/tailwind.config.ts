import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        teal: {
          radar: '#0F7C7C',
        },
        consensus: {
          green: '#2E9E5B',
          amber: '#E0A417',
          red: '#B91C1C',
        },
      },
      boxShadow: {
        card: '0 3px 12px rgba(15, 36, 52, 0.10)',
      },
    },
  },
  plugins: [],
}

export default config
