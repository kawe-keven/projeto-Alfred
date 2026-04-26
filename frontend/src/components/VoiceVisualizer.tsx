/**
 * components/VoiceVisualizer.tsx — Visualizador de áudio neumórfico.
 *
 * • isListening (verde): Alfred está ouvindo — barras pulsam em nm-success
 * • isSpeaking  (azul):  Alfred está falando — barras pulsam em nm-accent
 * • idle:                barras em altura mínima, cor discreta
 *
 * Barras com alturas e delays determinísticos (sem Math.random) para
 * evitar re-render inconsistente no SSR/StrictMode.
 */

interface VoiceVisualizerProps {
  isListening: boolean
  isSpeaking: boolean
  barCount?: number
}

// Alturas máximas normalizadas (0–100) para cada barra — determinísticas
const BAR_HEIGHTS = [
  45, 72, 55, 88, 40, 78, 62, 95, 50, 70,
  38, 82, 58, 75, 48, 90, 42, 68, 80, 52,
]

// Delays em ms para cada barra
const BAR_DELAYS = BAR_HEIGHTS.map((_, i) => i * 55)

// Durações em ms (alternadas suavemente)
const BAR_DURATIONS = BAR_HEIGHTS.map((h) => 350 + Math.round((h / 100) * 250))

export default function VoiceVisualizer({
  isListening,
  isSpeaking,
  barCount = 20,
}: VoiceVisualizerProps) {
  const bars = BAR_HEIGHTS.slice(0, barCount)
  const isActive = isListening || isSpeaking

  const barColor = isListening
    ? 'bg-nm-success shadow-[0_0_6px_rgba(100,255,218,0.5)]'
    : isSpeaking
      ? 'bg-nm-accent shadow-[0_0_6px_rgba(79,110,247,0.5)]'
      : 'bg-nm-text-dim'

  return (
    <div
      className={`
        flex items-end gap-[3px] h-8
        transition-opacity duration-300
        ${isActive ? 'opacity-100' : 'opacity-30'}
      `}
      aria-hidden="true"
    >
      {bars.map((maxH, i) => (
        <div
          key={i}
          className={`w-[3px] rounded-full origin-bottom flex-shrink-0 ${barColor}`}
          style={{
            height: isActive ? `${maxH * 0.32}px` : '3px',
            animation: isActive
              ? `voiceBar ${BAR_DURATIONS[i]}ms ease-in-out ${BAR_DELAYS[i]}ms infinite alternate`
              : 'none',
            // Tailwind doesn't support arbitrary keyframe names in purge,
            // so the animation uses the global @keyframes voiceBar from tailwind.config
            transformOrigin: 'bottom',
          }}
        />
      ))}
    </div>
  )
}
