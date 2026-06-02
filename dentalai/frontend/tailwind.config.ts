import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Design system — dark slate palette with indigo accent
        surface: {
          base: '#0b0d14',   // page background
          card: '#13151f',   // card / panel background
          raised: '#1c1f2e', // inputs, hover states
          border: '#2a2d3e', // borders and dividers
        },
        accent: {
          DEFAULT: '#6366f1', // indigo-500
          hover: '#4f46e5',   // indigo-600
          muted: '#312e81',   // dark indigo for subtle fills
        },
        status: {
          completed: '#22c55e', // green-500
          confirmed: '#3b82f6', // blue-500
          pending: '#f59e0b',   // amber-500
          cancelled: '#6b7280', // gray-500
          no_show: '#ef4444',   // red-500
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      keyframes: {
        'slide-in-top': {
          from: { opacity: '0', transform: 'translateY(-10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      animation: {
        'slide-in-top': 'slide-in-top 0.25s ease-out',
        'fade-in': 'fade-in 0.2s ease-out',
      },
    },
  },
  plugins: [],
}

export default config
