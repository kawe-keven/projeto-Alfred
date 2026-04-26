/**
 * components/ContextPanel.tsx — Painel de Memórias Recuperadas (RAG).
 *
 * Exibe em tempo real os fragmentos mais relevantes da memória vetorial
 * que foram usados para enriquecer a resposta do Alfred.
 *
 * Cada cartão mostra separadamente a parte do Usuário e do Alfred,
 * parseando o formato produzido pelo VectorStore.add_interaction().
 */
import { BookOpen, Loader2, Brain, MessageSquare, BotMessageSquare } from 'lucide-react'

// -----------------------------------------------------------------
// Parser de fragmento
// -----------------------------------------------------------------

interface InteractionFragment {
  user: string
  alfred: string
}

function parseFragment(raw: string): InteractionFragment {
  const userMatch   = raw.match(/\[Usuário\]:\s*([\s\S]*?)(?:\[Alfred\]:|$)/)
  const alfredMatch = raw.match(/\[Alfred\]:\s*([\s\S]*)$/)

  return {
    user:   userMatch?.[1]?.trim()   ?? raw,
    alfred: alfredMatch?.[1]?.trim() ?? '',
  }
}

// -----------------------------------------------------------------
// Memory Card
// -----------------------------------------------------------------

interface MemoryCardProps {
  fragment: string
  index: number
}

function MemoryCard({ fragment, index }: MemoryCardProps) {
  const { user, alfred } = parseFragment(fragment)

  return (
    <div
      className="p-3 rounded-xl shadow-nm-sm bg-nm-base border border-nm-highlight/20
                 animate-slide-right"
      style={{ animationDelay: `${index * 80}ms`, animationFillMode: 'both' }}
    >
      {/* Badge de relevância */}
      <div className="flex items-center gap-2 mb-2.5">
        <div className="w-5 h-5 rounded-md shadow-nm-sm bg-nm-base flex items-center justify-center">
          <Brain className="w-3 h-3 text-nm-accent" />
        </div>
        <span className="text-nm-accent text-[10px] tracking-widest uppercase">
          Memória {index + 1}
        </span>
        <div className="ml-auto flex gap-0.5">
          {Array.from({ length: 3 - index }).map((_, i) => (
            <span key={i} className="w-1 h-1 rounded-full bg-nm-accent opacity-80" />
          ))}
          {Array.from({ length: index }).map((_, i) => (
            <span key={i} className="w-1 h-1 rounded-full bg-nm-text-dim opacity-40" />
          ))}
        </div>
      </div>

      {/* Pergunta do usuário */}
      <div className="mb-2">
        <div className="flex items-center gap-1.5 mb-1">
          <MessageSquare className="w-3 h-3 text-nm-text-dim flex-shrink-0" />
          <span className="text-nm-text-dim text-[10px] uppercase tracking-wider">Usuário</span>
        </div>
        <div className="pl-2 border-l border-nm-accent/30">
          <p className="text-nm-text text-[11px] leading-relaxed line-clamp-3">{user}</p>
        </div>
      </div>

      {/* Resposta do Alfred */}
      {alfred && (
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <BotMessageSquare className="w-3 h-3 text-nm-text-dim flex-shrink-0" />
            <span className="text-nm-text-dim text-[10px] uppercase tracking-wider">Alfred</span>
          </div>
          <div className="pl-2 border-l border-nm-success/30">
            <p className="text-nm-text-dim text-[11px] leading-relaxed line-clamp-3">{alfred}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// -----------------------------------------------------------------
// Empty / Loading states
// -----------------------------------------------------------------

function EmptyContexts() {
  return (
    <div className="flex flex-col items-center justify-center h-32 gap-3 px-4 mt-4">
      <div className="w-10 h-10 rounded-xl shadow-nm-sm bg-nm-base flex items-center justify-center">
        <BookOpen className="w-5 h-5 text-nm-text-dim" />
      </div>
      <p className="text-nm-text-dim text-[11px] text-center leading-relaxed">
        Nenhuma memória recuperada ainda.
        <br />
        As memórias RAG aparecerão aqui após a primeira troca.
      </p>
    </div>
  )
}

function LoadingContexts() {
  return (
    <div className="flex flex-col items-center justify-center h-32 gap-3">
      <Loader2 className="w-6 h-6 text-nm-accent animate-spin" />
      <p className="text-nm-text-dim text-[11px] tracking-wider">
        Buscando memórias…
      </p>
    </div>
  )
}

// -----------------------------------------------------------------
// ContextPanel
// -----------------------------------------------------------------

interface ContextPanelProps {
  contexts: string[]
  isLoading: boolean
}

export default function ContextPanel({ contexts, isLoading }: ContextPanelProps) {
  return (
    <aside className="w-72 flex-shrink-0 flex flex-col border-l border-nm-highlight/20 overflow-hidden">

      {/* ── HEADER ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-nm-highlight/20 flex-shrink-0">
        <div className="w-6 h-6 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center">
          <Brain className="w-3.5 h-3.5 text-nm-accent" />
        </div>
        <div>
          <p className="text-nm-text text-[11px] tracking-widest uppercase">
            Memórias RAG
          </p>
          <p className="text-nm-text-dim text-[9px] tracking-wider">
            Contextos recuperados
          </p>
        </div>

        {/* Badge de contagem */}
        {contexts.length > 0 && (
          <div className="ml-auto px-2 py-0.5 rounded-full shadow-nm-pressed bg-nm-base">
            <span className="text-nm-accent text-[10px] font-medium">{contexts.length}</span>
          </div>
        )}
      </div>

      {/* ── CONTEÚDO ───────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {isLoading ? (
          <LoadingContexts />
        ) : contexts.length === 0 ? (
          <EmptyContexts />
        ) : (
          <div className="flex flex-col gap-3">
            {contexts.map((ctx, i) => (
              <MemoryCard key={`${i}-${ctx.slice(0, 20)}`} fragment={ctx} index={i} />
            ))}
          </div>
        )}
      </div>

      {/* ── FOOTER ─────────────────────────────────────────────── */}
      <div className="px-4 py-3 border-t border-nm-highlight/20 flex-shrink-0">
        <div className="flex items-center gap-2 p-2 rounded-lg shadow-nm-pressed bg-nm-base">
          <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
            contexts.length > 0 ? 'bg-nm-success' : 'bg-nm-text-dim'
          }`} />
          <p className="text-nm-text-dim text-[10px] tracking-wider">
            {contexts.length > 0
              ? `${contexts.length} contexto${contexts.length > 1 ? 's' : ''} injetado${contexts.length > 1 ? 's' : ''} no prompt`
              : 'Aguardando interação'
            }
          </p>
        </div>
      </div>
    </aside>
  )
}
