import type { Config } from 'tailwindcss'

export default {
  content: [
    './src/**/*.{vue,js,ts}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: '#faf9f5',
        'surface-soft': '#f5f0e8',
        'surface-card': '#efe9de',
        'surface-dark': '#181715',
        'surface-dark-elevated': '#252320',
        primary: '#cc785c',
        'primary-hover': '#d4896a',
        'primary-active': '#a9583e',
        ink: '#141413',
        muted: '#6c6a64',
        'muted-soft': '#8e8b82',
        sage: '#7D9E7D',
        'dusty-blue': '#6B8BA4',
        amber: '#D4A84B',
        'clay-red': '#B85C4D',
      },
      fontFamily: {
        display: ['Outfit', 'sans-serif'],
        body: ['Source Sans 3', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      spacing: {
        '1': '4px',
        '2': '8px',
        '3': '12px',
        '4': '16px',
        '5': '20px',
        '6': '24px',
        '8': '32px',
        '10': '40px',
        '12': '48px',
      },
    },
  },
  plugins: [],
} satisfies Config
