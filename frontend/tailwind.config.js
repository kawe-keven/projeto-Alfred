/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
      },
      colors: {
        nm: {
          base:          '#1a1d2e',
          'base-deep':   '#151724',
          shadow:        '#13151f',
          highlight:     '#21253d',
          accent:        '#4f6ef7',
          'accent-dim':  '#3a52c4',
          'accent-glow': 'rgba(79,110,247,0.4)',
          text:          '#8892b0',
          'text-bright': '#ccd6f6',
          'text-dim':    '#4a5270',
          success:       '#64ffda',
          warning:       '#ffd700',
          error:         '#ff6b6b',
          cyan:          '#00d4ff',
        },
      },
      boxShadow: {
        'nm-flat':    '6px 6px 12px #13151f, -6px -6px 12px #21253d',
        'nm-pressed': 'inset 4px 4px 8px #13151f, inset -4px -4px 8px #21253d',
        'nm-convex':  '6px 6px 12px #13151f, -6px -6px 12px #21253d, inset 1px 1px 1px #21253d, inset -1px -1px 1px #13151f',
        'nm-sm':      '3px 3px 6px #13151f, -3px -3px 6px #21253d',
        'nm-lg':      '10px 10px 20px #13151f, -10px -10px 20px #21253d',
        'nm-inner':   'inset 6px 6px 12px #13151f, inset -6px -6px 12px #21253d',
        'nm-accent':  '0 0 20px rgba(79,110,247,0.3), 6px 6px 12px #13151f, -6px -6px 12px #21253d',
        'nm-success': '0 0 16px rgba(100,255,218,0.2), 6px 6px 12px #13151f, -6px -6px 12px #21253d',
        'glass':      '0 8px 32px rgba(79,110,247,0.12), inset 0 1px 0 rgba(255,255,255,0.05)',
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        'float':        'float 6s ease-in-out infinite',
        'glow-pulse':   'glowPulse 2.5s ease-in-out infinite alternate',
        'spin-slow':    'spin 12s linear infinite',
        'fade-in':      'fadeIn 0.35s ease-out',
        'slide-up':     'slideUp 0.4s ease-out',
        'slide-right':  'slideRight 0.4s ease-out',
        'ping-slow':    'ping 2s cubic-bezier(0,0,0.2,1) infinite',
        'blink':        'blink 1.2s step-end infinite',
        'progress':     'progress 5s linear forwards',
        'voice-bar':    'voiceBar 0.5s ease-in-out infinite alternate',
        'voice-bar-lg': 'voiceBar 0.35s ease-in-out infinite alternate',
      },
      keyframes: {
        voiceBar: {
          '0%':   { transform: 'scaleY(0.15)', opacity: '0.5' },
          '100%': { transform: 'scaleY(1)',    opacity: '1'   },
        },
        float: {
          '0%,100%': { transform: 'translateY(0px)' },
          '50%':     { transform: 'translateY(-8px)' },
        },
        glowPulse: {
          '0%':   { boxShadow: '0 0 8px rgba(79,110,247,0.2), 0 0 16px rgba(79,110,247,0.1)' },
          '100%': { boxShadow: '0 0 24px rgba(79,110,247,0.6), 0 0 48px rgba(79,110,247,0.3), 0 0 72px rgba(79,110,247,0.1)' },
        },
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%':   { transform: 'translateY(16px)', opacity: '0' },
          '100%': { transform: 'translateY(0)',    opacity: '1' },
        },
        slideRight: {
          '0%':   { transform: 'translateX(-16px)', opacity: '0' },
          '100%': { transform: 'translateX(0)',      opacity: '1' },
        },
        blink: {
          '0%,100%': { opacity: '1' },
          '50%':     { opacity: '0' },
        },
        progress: {
          '0%':   { width: '100%' },
          '100%': { width: '0%' },
        },
      },
    },
  },
  plugins: [],
}
