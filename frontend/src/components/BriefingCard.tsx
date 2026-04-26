/**
 * components/BriefingCard.tsx — Modal de Briefing Matinal Proativo.
 *
 * Fluxo:
 *   1. Aparece como modal central ao iniciar o Alfred.
 *   2. Exibe saudação, texto do briefing, CPU/RAM e tópicos recentes.
 *   3. Após 10 s (ou clique em fechar), colapsa para uma tira fina
 *      na borda inferior da tela (badge persistente).
 *   4. Clicar na tira reexpande o modal.
 */
import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Cpu, Search, ChevronUp, Sparkles } from 'lucide-react'
import type { BriefingResponse } from '../api/alfred'

// -----------------------------------------------------------------
// Props
// -----------------------------------------------------------------

interface BriefingCardProps {
    data: BriefingResponse
    onDismiss: () => void   // chamado quando o usuário fecha totalmente
}

// -----------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------

function CpuBar({ value, label }: { value: number; label: string }) {
    const color =
        value >= 85 ? 'bg-nm-error' : value >= 65 ? 'bg-nm-warning' : 'bg-nm-success'

    return (
        <div className="flex flex-col gap-1 flex-1">
            <div className="flex justify-between items-center">
                <span className="text-nm-text-dim text-[9px] tracking-widest uppercase">{label}</span>
                <span className="text-nm-text text-[10px] font-bold">{value.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-nm-base shadow-nm-inner overflow-hidden">
                <motion.div
                    className={`h-full rounded-full ${color}`}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(value, 100)}%` }}
                    transition={{ duration: 1, ease: 'easeOut' }}
                />
            </div>
        </div>
    )
}

// -----------------------------------------------------------------
// Component
// -----------------------------------------------------------------

export default function BriefingCard({ data, onDismiss }: BriefingCardProps) {
    const [collapsed, setCollapsed] = useState(false)
    const [dismissed, setDismissed] = useState(false)

    // Auto-colapsa após 10 segundos
    useEffect(() => {
        const timer = setTimeout(() => setCollapsed(true), 10_000)
        return () => clearTimeout(timer)
    }, [])

    const handleClose = () => {
        setDismissed(true)
        setTimeout(onDismiss, 350)
    }

    if (dismissed) return null

    return (
        <AnimatePresence mode="wait">
            {!collapsed ? (
                /* ─── Modal completo ─── */
                <motion.div
                    key="modal"
                    initial={{ opacity: 0, scale: 0.92, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.9, y: -20 }}
                    transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                    className="fixed inset-0 z-50 flex items-center justify-center px-4"
                    style={{ pointerEvents: 'none' }}
                >
                    {/* Backdrop blur */}
                    <motion.div
                        className="absolute inset-0 bg-nm-base/60 backdrop-blur-sm"
                        style={{ pointerEvents: 'all' }}
                        onClick={() => setCollapsed(true)}
                    />

                    {/* Card */}
                    <motion.div
                        className="relative z-10 w-full max-w-md rounded-3xl shadow-nm-flat bg-nm-base border border-white/5 overflow-hidden"
                        style={{ pointerEvents: 'all' }}
                    >
                        {/* Barra de progresso — 10s */}
                        <motion.div
                            className="absolute top-0 left-0 h-0.5 bg-nm-accent/70"
                            initial={{ width: '100%' }}
                            animate={{ width: '0%' }}
                            transition={{ duration: 10, ease: 'linear' }}
                        />

                        {/* Header */}
                        <div className="flex items-center gap-3 px-6 pt-6 pb-3">
                            <div className="w-9 h-9 rounded-xl shadow-nm-sm bg-nm-base flex items-center justify-center flex-shrink-0">
                                <Sparkles className="w-4.5 h-4.5 text-nm-accent animate-pulse-slow" />
                            </div>
                            <div className="flex-1">
                                <p className="text-nm-text-bright text-sm font-semibold tracking-wide">
                                    Briefing Matinal
                                </p>
                                <p className="text-nm-text-dim text-[10px] tracking-widest uppercase">
                                    Alfred · Prontidão
                                </p>
                            </div>
                            <button
                                onClick={handleClose}
                                className="w-7 h-7 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center
                           text-nm-text-dim hover:text-nm-text transition-colors"
                                title="Fechar briefing"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        </div>

                        {/* Texto do briefing */}
                        <div className="px-6 pb-4">
                            <p className="text-nm-text text-sm leading-relaxed">
                                {data.text}
                            </p>
                        </div>

                        {/* Hardware */}
                        <div className="mx-6 mb-4 px-4 py-3 rounded-2xl shadow-nm-inner bg-nm-base">
                            <div className="flex items-center gap-2 mb-2.5">
                                <Cpu className="w-3.5 h-3.5 text-nm-text-dim" />
                                <span className="text-nm-text-dim text-[9px] tracking-widest uppercase">Sistema</span>
                            </div>
                            <div className="flex gap-4">
                                <CpuBar value={data.cpu} label="CPU" />
                                <CpuBar value={data.ram} label="RAM" />
                            </div>
                        </div>

                        {/* Tópicos recentes */}
                        {data.topics.length > 0 && (
                            <div className="px-6 pb-5">
                                <div className="flex items-center gap-2 mb-2">
                                    <Search className="w-3 h-3 text-nm-text-dim" />
                                    <span className="text-nm-text-dim text-[9px] tracking-widest uppercase">
                                        Últimas pesquisas
                                    </span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {data.topics.map((topic, i) => (
                                        <span
                                            key={i}
                                            className="text-[10px] px-2.5 py-1 rounded-lg shadow-nm-flat bg-nm-base
                                 text-nm-text-dim border border-white/5"
                                        >
                                            {topic.length > 40 ? topic.slice(0, 38) + '…' : topic}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Rodapé */}
                        <div className="flex items-center justify-between px-6 py-3 border-t border-white/5">
                            <span className="text-nm-text-dim text-[9px] tracking-widest uppercase">
                                Fecha automaticamente em 10s
                            </span>
                            <button
                                onClick={() => setCollapsed(true)}
                                className="flex items-center gap-1 text-[10px] text-nm-accent hover:text-nm-accent/80
                           transition-colors"
                            >
                                <ChevronUp className="w-3 h-3" />
                                Minimizar
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            ) : (
                /* ─── Tira colapsada ─── */
                <motion.div
                    key="badge"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 20 }}
                    transition={{ duration: 0.3 }}
                    className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50"
                >
                    <button
                        onClick={() => setCollapsed(false)}
                        className="flex items-center gap-2.5 px-4 py-2 rounded-2xl shadow-nm-flat bg-nm-base
                       border border-white/5 hover:shadow-nm-sm transition-shadow"
                    >
                        <Sparkles className="w-3.5 h-3.5 text-nm-accent" />
                        <span className="text-nm-text-dim text-[10px] tracking-widest uppercase">
                            Briefing
                        </span>
                        {data.weather_city && (
                            <span className="text-nm-text text-[10px]">· {data.weather_city}</span>
                        )}
                        <span className="text-[10px] text-nm-text-dim">
                            CPU {data.cpu.toFixed(0)}%
                        </span>
                        <button
                            onClick={(e) => { e.stopPropagation(); handleClose() }}
                            className="ml-1 text-nm-text-dim hover:text-nm-text transition-colors"
                        >
                            <X className="w-3 h-3" />
                        </button>
                    </button>
                </motion.div>
            )}
        </AnimatePresence>
    )
}
