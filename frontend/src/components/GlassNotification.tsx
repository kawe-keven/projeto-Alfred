/**
 * components/GlassNotification.tsx — Toast glassmorphism para alertas.
 *
 * Tipos:
 *  • error   → borda vermelha, ícone X
 *  • warning → borda amarela, ícone TriangleAlert
 *  • info    → borda azul, ícone Info
 *
 * Posição: canto superior direto (fixed).
 * Auto-dismiss via barra de progresso animada (5 s).
 */
import { useEffect } from 'react'
import { X, AlertTriangle, Info, CheckCircle } from 'lucide-react'
import type { Notification } from '../App'

interface GlassNotificationProps {
  notification: Notification
  onClose: () => void
}

// -----------------------------------------------------------------
// Variantes visuais por tipo
// -----------------------------------------------------------------

const VARIANTS = {
  error: {
    border:     'border-nm-error/40',
    icon:       <AlertTriangle className="w-4 h-4" />,
    iconColor:  'text-nm-error',
    titleColor: 'text-nm-error',
    title:      'Erro',
    bar:        'bg-nm-error',
  },
  warning: {
    border:     'border-nm-warning/40',
    icon:       <AlertTriangle className="w-4 h-4" />,
    iconColor:  'text-nm-warning',
    titleColor: 'text-nm-warning',
    title:      'Atenção',
    bar:        'bg-nm-warning',
  },
  info: {
    border:     'border-nm-accent/40',
    icon:       <Info className="w-4 h-4" />,
    iconColor:  'text-nm-cyan',
    titleColor: 'text-nm-cyan',
    title:      'Info',
    bar:        'bg-nm-accent',
  },
  success: {
    border:     'border-nm-success/40',
    icon:       <CheckCircle className="w-4 h-4" />,
    iconColor:  'text-nm-success',
    titleColor: 'text-nm-success',
    title:      'Sucesso',
    bar:        'bg-nm-success',
  },
} as const

// -----------------------------------------------------------------
// Component
// -----------------------------------------------------------------

export default function GlassNotification({
  notification,
  onClose,
}: GlassNotificationProps) {
  // Auto-dismiss após 5 s
  useEffect(() => {
    const timer = setTimeout(onClose, 5_000)
    return () => clearTimeout(timer)
  }, [notification.id, onClose])

  const v = VARIANTS[notification.type]

  return (
    <div
      className={`
        fixed top-5 right-5 z-50 w-80 rounded-2xl overflow-hidden
        glass-notification shadow-glass
        border ${v.border}
        animate-slide-up
      `}
      role="alert"
    >
      {/* Progress bar */}
      <div className="h-0.5 w-full bg-nm-highlight/30">
        <div
          className={`h-full ${v.bar} opacity-70`}
          style={{ animation: 'progress 5s linear forwards' }}
        />
      </div>

      <div className="px-4 py-3 flex items-start gap-3">
        {/* Icon */}
        <div className={`flex-shrink-0 mt-0.5 ${v.iconColor}`}>
          {v.icon}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className={`text-xs font-semibold tracking-widest uppercase mb-1 ${v.titleColor}`}>
            {notification.title ?? v.title}
          </p>
          <p className="text-nm-text text-xs leading-relaxed break-words">
            {notification.message}
          </p>
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="
            flex-shrink-0 w-6 h-6 rounded-lg
            flex items-center justify-center
            text-nm-text-dim hover:text-nm-text
            shadow-nm-sm bg-nm-base hover:shadow-nm-pressed
            transition-all duration-150
          "
        >
          <X className="w-3 h-3" />
        </button>
      </div>
    </div>
  )
}
