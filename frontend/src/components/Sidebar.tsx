/**
 * components/Sidebar.tsx — Painel lateral do Alfred Dashboard.
 *
 * Exibe:
 *  • Logo + ParticleOrb com status do agente
 *  • Status de todos os subsistemas
 *  • Session ID atual + botão de limpar sessão
 */
import { Brain, Database, Zap, Wifi, Hash, BotMessageSquare, Trash2 } from 'lucide-react'
import type { AgentStatus } from '../App'
import ParticleOrb from './ParticleOrb'
import WeatherCalendarWidget from './WeatherCalendarWidget'
import SystemHUD from './SystemHUD'

// -----------------------------------------------------------------
// Sub-componentes
// -----------------------------------------------------------------

interface StatusItemProps {
  icon: React.ReactNode
  label: string
  value: string
  dotColor: string
}

function StatusItem({ icon, label, value, dotColor }: StatusItemProps) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-xl shadow-nm-pressed bg-nm-base">
      <div className="w-8 h-8 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center flex-shrink-0">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-nm-text-dim text-[10px] tracking-wider uppercase truncate">
          {label}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor}`} />
          <p className="text-nm-text text-[11px] truncate">{value}</p>
        </div>
      </div>
    </div>
  )
}

// -----------------------------------------------------------------
// Sidebar
// -----------------------------------------------------------------

interface SidebarProps {
  agentStatus: AgentStatus
  sessionId: string
  onClearSession: () => void
  isResearching: boolean
}

const STATUS_LABEL: Record<AgentStatus, string> = {
  online: 'Online',
  processing: 'Processando...',
  offline: 'Offline',
}

const STATUS_DOT: Record<AgentStatus, string> = {
  online: 'bg-nm-success',
  processing: 'bg-nm-warning animate-ping-slow',
  offline: 'bg-nm-error',
}

const STATUS_TEXT: Record<AgentStatus, string> = {
  online: 'text-nm-success',
  processing: 'text-nm-warning',
  offline: 'text-nm-error',
}

export default function Sidebar({ agentStatus, sessionId, onClearSession, isResearching }: SidebarProps) {
  const shortSession = sessionId.slice(-10)

  return (
    <aside className="w-64 flex-shrink-0 flex flex-col gap-3 p-4 border-r border-nm-highlight/20 overflow-y-auto">

      {/* ── LOGO / ORB ──────────────────────────────────────────── */}
      <div className="flex flex-col items-center gap-3 p-5 rounded-2xl shadow-nm-flat bg-nm-base mt-1 animate-fade-in">
        <div className="animate-float">
          <ParticleOrb isLoading={agentStatus === 'processing'} isResearching={isResearching} size={88} />
        </div>

        <div className="text-center">
          <h1 className="text-nm-text-bright font-semibold text-base tracking-[0.3em]">
            ALFRED
          </h1>
          <p className="text-nm-text-dim text-[10px] tracking-widest mt-0.5">
            AI SYSTEM v0.1.0
          </p>
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full shadow-nm-pressed bg-nm-base">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[agentStatus]}`} />
          <span className={`text-[11px] font-medium ${STATUS_TEXT[agentStatus]}`}>
            {STATUS_LABEL[agentStatus]}
          </span>
        </div>
      </div>

      {/* ── SISTEMAS ────────────────────────────────────────────── */}
      <div>
        <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase px-1 mb-2">
          Sistemas
        </p>
        <div className="flex flex-col gap-2">
          <StatusItem
            icon={<Database className="w-4 h-4 text-nm-success" />}
            label="Memória Vetorial"
            value="ChromaDB · Ativa"
            dotColor="bg-nm-success"
          />
          <StatusItem
            icon={<Brain className="w-4 h-4 text-nm-accent" />}
            label="Agentes"
            value="GeneralAgent · Online"
            dotColor="bg-nm-accent"
          />
          <StatusItem
            icon={<Zap className="w-4 h-4 text-nm-cyan" />}
            label="Modelo LLM"
            value="Gemini 1.5 Flash"
            dotColor="bg-nm-cyan"
          />
          <StatusItem
            icon={<Wifi className="w-4 h-4 text-nm-warning" />}
            label="API FastAPI"
            value="localhost:8000"
            dotColor="bg-nm-warning"
          />
        </div>
      </div>

      {/* ── CONFIGURAÇÃO RAG ───────────────────────────── */}
      <div>
        <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase px-1 mb-2">
          Configuração RAG
        </p>
        <div className="flex flex-col gap-2">
          <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base">
            <div className="flex items-center gap-1.5 mb-1">
              <BotMessageSquare className="w-3 h-3 text-nm-text-dim" />
              <p className="text-nm-text-dim text-[10px] uppercase tracking-wider">Embedding</p>
            </div>
            <p className="text-nm-text text-[11px]">all-MiniLM-L6-v2</p>
            <p className="text-nm-text-dim text-[10px] mt-0.5">384 dim · Cosine</p>
          </div>
          <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base">
            <div className="flex items-center gap-1.5 mb-1">
              <Hash className="w-3 h-3 text-nm-text-dim" />
              <p className="text-nm-text-dim text-[10px] uppercase tracking-wider">Top-K</p>
            </div>
            <p className="text-nm-text text-[11px]">3 contextos / query</p>
          </div>
        </div>
      </div>

      {/* ── SESSÃO ──────────────────────────────────────────────── */}      <div>
        <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase px-1 mb-2">
          Clima &amp; Agenda
        </p>
        <WeatherCalendarWidget />
      </div>

      {/* ── HARDWARE HUD ────────────────────────────────────────── */}
      <div>
        <SystemHUD />
      </div>

      {/* ── SESSÃO ────────────────────────────────────── */}      <div className="mt-auto">
        <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase px-1 mb-2">
          Sessão
        </p>
        <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base">
          <p className="text-nm-text-dim text-[10px] mb-1">Session ID</p>
          <p className="text-nm-accent text-[11px] font-mono tracking-wider break-all">
            …{shortSession}
          </p>
        </div>

        <button
          onClick={onClearSession}
          className="
            mt-2 w-full flex items-center justify-center gap-2
            p-2.5 rounded-xl shadow-nm-sm bg-nm-base
            text-nm-error text-[11px] tracking-wider uppercase
            transition-all duration-200
            hover:shadow-nm-pressed active:shadow-nm-inner
          "
        >
          <Trash2 className="w-3.5 h-3.5" />
          Limpar Sessão
        </button>

      </div>
    </aside>
  )
}
