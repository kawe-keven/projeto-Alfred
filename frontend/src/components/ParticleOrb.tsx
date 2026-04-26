/**
 * components/ParticleOrb.tsx — Orbe de partículas animado no canvas.
 *
 * Estado normal      → partículas em órbita lenta, núcleo suave (azul).
 * Estado loading     → órbita acelerada, pulsos de expansão, núcleo brilhante (azul).
 * Estado researching → órbita média, núcleo roxo, partículas violêceas pulsantes.
 */
import { useEffect, useRef } from 'react'

interface Particle {
  angle: number
  radius: number
  speed: number
  size: number
  opacity: number
  color: string
  orbitTilt: number
  twinkle: number    // phase offset para variação de brilho
}

interface ParticleOrbProps {
  isLoading: boolean
  isResearching?: boolean
  size?: number
}

const COLORS_NORMAL = ['#4f6ef7', '#4f6ef7', '#4f6ef7', '#00d4ff', '#64ffda', '#8892b0']
const COLORS_RESEARCH = ['#8b5cf6', '#a78bfa', '#c4b5fd', '#7c3aed', '#ddd6fe', '#a78bfa']

export default function ParticleOrb({ isLoading, isResearching = false, size = 80 }: ParticleOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const loadingRef = useRef(isLoading)
  const researchingRef = useRef(isResearching)
  const particlesRef = useRef<Particle[]>([])

  // Sincroniza refs sem reinicializar o canvas
  useEffect(() => { loadingRef.current = isLoading }, [isLoading])
  useEffect(() => { researchingRef.current = isResearching }, [isResearching])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const cx = size / 2
    const cy = size / 2

    // Gera partículas em distribuição uniforme
    particlesRef.current = Array.from({ length: 28 }, (_, i) => ({
      angle: (i / 28) * Math.PI * 2,
      radius: 12 + Math.random() * 20,
      speed: 0.003 + Math.random() * 0.007,
      size: 1.0 + Math.random() * 2.4,
      opacity: 0.35 + Math.random() * 0.65,
      color: COLORS_NORMAL[Math.floor(Math.random() * COLORS_NORMAL.length)],
      orbitTilt: Math.random() * 0.6 - 0.3,
      twinkle: Math.random() * Math.PI * 2,
    }))

    let t = 0

    const render = () => {
      const loading = loadingRef.current
      const researching = researchingRef.current
      const speed = loading ? 4.5 : researching ? 2.2 : 1

      ctx.clearRect(0, 0, size, size)
      t += 0.016

      // ── Ambient glow ──────────────────────────────────────────
      const glowR = loading ? 34 : 28
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR)
      if (researching) {
        glow.addColorStop(0, 'rgba(139,92,246,0.55)')
        glow.addColorStop(0.5, 'rgba(139,92,246,0.15)')
        glow.addColorStop(1, 'rgba(139,92,246,0)')
      } else {
        glow.addColorStop(0, loading ? 'rgba(79,110,247,0.60)' : 'rgba(79,110,247,0.22)')
        glow.addColorStop(0.5, loading ? 'rgba(79,110,247,0.18)' : 'rgba(79,110,247,0.07)')
        glow.addColorStop(1, 'rgba(79,110,247,0)')
      }
      ctx.beginPath()
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2)
      ctx.fillStyle = glow
      ctx.fill()

      // ── Core ──────────────────────────────────────────────────
      const coreR = loading ? 9 + Math.sin(t * 7) * 1.8 : researching ? 8 + Math.sin(t * 3) * 1.2 : 7
      const core = ctx.createRadialGradient(cx - 1.5, cy - 1.5, 0, cx, cy, coreR)
      if (researching) {
        core.addColorStop(0, '#ffffff')
        core.addColorStop(0.2, '#e9d5ff')
        core.addColorStop(0.6, '#8b5cf6')
        core.addColorStop(1, '#1a1d2e')
      } else {
        core.addColorStop(0, '#ffffff')
        core.addColorStop(0.2, loading ? '#c0cfff' : '#8fa8ff')
        core.addColorStop(0.6, loading ? '#4f6ef7' : '#3a52c4')
        core.addColorStop(1, '#1a1d2e')
      }
      ctx.beginPath()
      ctx.arc(cx, cy, coreR, 0, Math.PI * 2)
      ctx.fillStyle = core
      ctx.fill()

      // ── Partículas ────────────────────────────────────────────
      const palette = researching ? COLORS_RESEARCH : COLORS_NORMAL
      for (const p of particlesRef.current) {
        const displayColor = researching
          ? palette[Math.floor((p.twinkle * 10) % palette.length)]
          : p.color
        p.angle += p.speed * speed

        const px = cx + Math.cos(p.angle) * p.radius
        const py = cy + Math.sin(p.angle + p.orbitTilt) * p.radius * 0.55

        // Brilho pulsante individual
        const tw = Math.abs(Math.sin(t * 1.5 + p.twinkle))
        const alpha = Math.min(1, (loading ? p.opacity * 1.4 : p.opacity) * (0.6 + tw * 0.4))
        const alphaH = Math.floor(alpha * 255).toString(16).padStart(2, '0')

        // Halo difuso
        const haloR = p.size * 3.5
        const halo = ctx.createRadialGradient(px, py, 0, px, py, haloR)
        halo.addColorStop(0, displayColor + '55')
        halo.addColorStop(1, displayColor + '00')
        ctx.beginPath()
        ctx.arc(px, py, haloR, 0, Math.PI * 2)
        ctx.fillStyle = halo
        ctx.fill()

        // Ponto central
        ctx.beginPath()
        ctx.arc(px, py, p.size, 0, Math.PI * 2)
        ctx.fillStyle = displayColor + alphaH
        ctx.fill()
      }

      // ── Anéis de pulso (loading = azul / researching = roxo) ──
      if (loading || researching) {
        const [rc1, rc2] = researching
          ? ['rgba(139,92,246,', 'rgba(196,181,253,']
          : ['rgba(79,110,247,', 'rgba(0,212,255,']

        const r1 = 20 + Math.sin(t * 5) * 5
        ctx.beginPath()
        ctx.arc(cx, cy, r1, 0, Math.PI * 2)
        ctx.strokeStyle = `${rc1}${0.28 + Math.sin(t * 4) * 0.12})`
        ctx.lineWidth = 0.8
        ctx.stroke()

        const r2 = 30 + Math.sin(t * 3 + 1.2) * 6
        ctx.beginPath()
        ctx.arc(cx, cy, r2, 0, Math.PI * 2)
        ctx.strokeStyle = `${rc2}${0.15 + Math.sin(t * 3.5) * 0.08})`
        ctx.lineWidth = 0.5
        ctx.stroke()
      }

      animRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      cancelAnimationFrame(animRef.current)
    }
  }, [size])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size }}
      className="rounded-full"
    />
  )
}
