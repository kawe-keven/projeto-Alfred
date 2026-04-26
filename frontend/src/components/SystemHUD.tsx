/**
 * components/SystemHUD.tsx — HUD de telemetria de hardware em tempo real.
 *
 * Exibe CPU, RAM, Disco e temperatura via gauges circulares SVG animados
 * com framer-motion. LED vermelho pulsante quando CPU > 90%.
 */
import { motion, useSpring, useTransform } from 'framer-motion'
import { useHardwareSocket } from '../hooks/useHardwareSocket'

// ---------------------------------------------------------------------------
// Constantes do gauge SVG
// ---------------------------------------------------------------------------
const RADIUS = 26
const STROKE = 5


// ---------------------------------------------------------------------------
// Cores por nível
// ---------------------------------------------------------------------------
function levelColor(pct: number, isTemp = false): string {
    const warn = isTemp ? 75 : 70
    const error = isTemp ? 90 : 90
    if (pct >= error) return '#ef4444'   // red-500
    if (pct >= warn) return '#f59e0b'   // amber-500
    return '#06b6d4'                      // cyan-500 (nm-accent)
}

// ---------------------------------------------------------------------------
// GaugeCircle — arco SVG animado com framer-motion
// ---------------------------------------------------------------------------
interface GaugeCircleProps {
    pct: number
    color: string
    size?: number
}

function GaugeCircle({ pct, color, size = 64 }: GaugeCircleProps) {
    const center = size / 2
    const r = RADIUS * (size / 64)
    const stroke = STROKE * (size / 64)
    const circ = 2 * Math.PI * r

    const springPct = useSpring(pct, { stiffness: 80, damping: 20 })
    const offset = useTransform(springPct, v => circ * (1 - Math.max(0, Math.min(100, v)) / 100))

    return (
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rotate-[-90deg]">
            {/* trilha */}
            <circle
                cx={center} cy={center} r={r}
                fill="none"
                stroke="rgba(255,255,255,0.05)"
                strokeWidth={stroke}
            />
            {/* arco de progresso */}
            <motion.circle
                cx={center} cy={center} r={r}
                fill="none"
                stroke={color}
                strokeWidth={stroke}
                strokeLinecap="round"
                strokeDasharray={circ}
                style={{ strokeDashoffset: offset }}
                filter="url(#glow)"
            />
            <defs>
                <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
                    <feMerge>
                        <feMergeNode in="blur" />
                        <feMergeNode in="SourceGraphic" />
                    </feMerge>
                </filter>
            </defs>
        </svg>
    )
}

// ---------------------------------------------------------------------------
// GaugeCard — card neumórfico com gauge + label
// ---------------------------------------------------------------------------
interface GaugeCardProps {
    label: string
    pct: number
    subLabel: string
    isTemp?: boolean
}

function GaugeCard({ label, pct, subLabel, isTemp = false }: GaugeCardProps) {
    const color = levelColor(pct, isTemp)
    const displayPct = isTemp ? Math.round(pct) : Math.round(pct)

    return (
        <div className="flex-1 flex flex-col items-center gap-1 p-2 rounded-xl shadow-nm-pressed bg-nm-base">
            <p className="text-nm-text-dim text-[9px] tracking-widest uppercase">{label}</p>

            <div className="relative flex items-center justify-center">
                <GaugeCircle pct={pct} color={color} size={56} />
                <div className="absolute flex flex-col items-center">
                    <span className="text-[11px] font-semibold leading-none" style={{ color }}>
                        {displayPct}{isTemp ? '°' : '%'}
                    </span>
                </div>
            </div>

            <p className="text-nm-text-dim text-[9px] text-center leading-tight">{subLabel}</p>
        </div>
    )
}

// ---------------------------------------------------------------------------
// SystemHUD — componente principal
// ---------------------------------------------------------------------------
export default function SystemHUD() {
    const m = useHardwareSocket()

    // LED pulsante (CPU > 90%)
    const cpuCritical = m ? m.cpu >= 90 : false

    if (!m) {
        return (
            <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base">
                <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase text-center animate-pulse">
                    Conectando HUD…
                </p>
            </div>
        )
    }

    return (
        <div className="rounded-xl shadow-nm-pressed bg-nm-base p-2.5 flex flex-col gap-2">

            {/* Cabeçalho */}
            <div className="flex items-center justify-between px-0.5">
                <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase">Hardware HUD</p>
                <div className="flex items-center gap-1.5">
                    {/* LED de status */}
                    {cpuCritical ? (
                        <motion.span
                            className="w-2 h-2 rounded-full bg-red-500"
                            animate={{ opacity: [1, 0.2, 1] }}
                            transition={{ repeat: Infinity, duration: 0.6 }}
                        />
                    ) : (
                        <span className="w-2 h-2 rounded-full bg-nm-success" />
                    )}
                    <span className={`text-[9px] font-medium ${cpuCritical ? 'text-red-400' : 'text-nm-success'}`}>
                        {cpuCritical ? 'CRÍTICO' : 'NORMAL'}
                    </span>
                </div>
            </div>

            {/* Gauges: CPU + RAM */}
            <div className="flex gap-2">
                <GaugeCard
                    label="CPU"
                    pct={m.cpu}
                    subLabel={`${m.cpu.toFixed(1)}%`}
                />
                <GaugeCard
                    label="RAM"
                    pct={m.ram}
                    subLabel={`${m.ram_used_gb}/${m.ram_total_gb} GB`}
                />
            </div>

            {/* Gauges: Disco + Temp */}
            <div className="flex gap-2">
                <GaugeCard
                    label="Disco"
                    pct={m.disk}
                    subLabel={`${m.disk_used_gb}/${m.disk_total_gb} GB`}
                />
                {m.cpu_temp !== null ? (
                    <GaugeCard
                        label="Temp"
                        pct={m.cpu_temp}           /* usa °C como escala 0-100 */
                        subLabel={`${m.cpu_temp}°C`}
                        isTemp
                    />
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center gap-1 p-2 rounded-xl shadow-nm-pressed bg-nm-base">
                        <p className="text-nm-text-dim text-[9px] tracking-widest uppercase">Temp</p>
                        <p className="text-nm-text-dim text-[10px]">N/D</p>
                    </div>
                )}
            </div>
        </div>
    )
}
