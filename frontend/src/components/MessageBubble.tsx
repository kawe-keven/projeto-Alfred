/**
 * components/MessageBubble.tsx — Card neumórfico de mensagem.
 *
 * User      → shadow-nm-pressed (afundado na tela, alinhado à direita)
 *             transmite a sensação de "já foi enviado"
 * Assistant → shadow-nm-flat   (elevado da tela, alinhado à esquerda)
 *             transmite a sensação de "surgindo em resposta"
 */
import { Bot, User, Monitor, BrainCircuit, Eye } from 'lucide-react'
import type { Message } from '../App'

interface MessageBubbleProps {
  message: Message
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

// Badge visual por tipo de agente
function AgentBadge({ agentUsed, action }: { agentUsed?: string; action?: string }) {
  if (!agentUsed) return null
  const isSystem = agentUsed?.toLowerCase().includes('system')
  const isVision = agentUsed?.toLowerCase().includes('vision')

  let icon = <BrainCircuit className="w-2.5 h-2.5" />
  let label = 'GeneralAgent'
  let colorClass = 'text-nm-success border-nm-success/20'
  if (isSystem) {
    icon = <Monitor className="w-2.5 h-2.5" />
    label = action ? `sys · ${action}` : 'SystemAgent'
    colorClass = 'text-nm-warning border-nm-warning/20'
  } else if (isVision) {
    icon = <Eye className="w-2.5 h-2.5" />
    label = action ? `vision · ${action}` : 'VisionAgent'
    colorClass = 'text-nm-accent border-nm-accent/20'
  }

  return (
    <span
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px]
        tracking-widest uppercase font-medium shadow-nm-sm
        ${colorClass} bg-nm-base border
      `}
    >
      {icon}
      {label}
    </span>
  )
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div
      className={`flex gap-3 animate-slide-up ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
    >
      {/* ── Avatar ─────────────────────────────────────────────── */}
      <div
        className={`
          w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center
          shadow-nm-sm bg-nm-base
          ${isUser ? 'mt-auto' : 'mt-1'}
        `}
      >
        {isUser
          ? <User className="w-4 h-4 text-nm-accent" />
          : <Bot className="w-4 h-4 text-nm-success" />
        }
      </div>

      {/* ── Bubble ─────────────────────────────────────────────── */}
      <div className={`flex flex-col gap-1 max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>

        {/* Rótulo + badge de agente */}
        <div className={`flex items-center gap-2 px-1 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
          <span className="text-nm-text-dim text-[10px] tracking-widest uppercase">
            {isUser ? 'Você' : 'Alfred'}
          </span>
          {!isUser && (
            <AgentBadge
              agentUsed={message.agentUsed}
              action={message.intent?.action}
            />
          )}
        </div>

        {/* Conteúdo */}
        <div
          className={`
            relative px-4 py-3 rounded-2xl
            ${isUser
              ? `shadow-nm-pressed bg-nm-base rounded-tr-sm
                 border-r-2 border-nm-accent/40`
              : `shadow-nm-flat bg-nm-base rounded-tl-sm
                 border-l-2 border-nm-success/30`
            }
          `}
        >
          {/* Borda luminosa decorativa */}
          {!isUser && (
            <div
              className="absolute top-0 left-0 w-px h-full rounded-l-xl"
              style={{
                background: 'linear-gradient(180deg, #64ffda55, #4f6ef755, transparent)',
              }}
            />
          )}

          <p
            className={`
              text-sm leading-relaxed whitespace-pre-wrap break-words
              ${isUser ? 'text-nm-text' : 'text-nm-text-bright'}
            `}
          >
            {message.content}
          </p>

          {/* Neumorphic image card (for image messages) */}
          {message.imageUrl && (
            <div className="mt-3 rounded-xl overflow-hidden shadow-nm-flat border border-nm-accent/20">
              <img
                src={message.imageUrl}
                alt="Imagem enviada"
                className="max-w-full max-h-64 object-contain w-full"
                style={{ display: 'block' }}
              />
            </div>
          )}
        </div>

        {/* Timestamp */}
        <span className="text-nm-text-dim text-[10px] px-1">
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  )
}
