/**
 * App.tsx — Raiz da aplicação Alfred Dashboard.
 *
 * Gerencia estado global: mensagens, contextos RAG, status do agente
 * e notificações; distribui props para os componentes filhos.
 */
import { useState, useCallback, useRef, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import ChatArea from './components/ChatArea'
import ContextPanel from './components/ContextPanel'
import GlassNotification from './components/GlassNotification'
import BriefingCard from './components/BriefingCard'
import { sendMessage, clearSession, takeScreenshot, getBriefing, AlfredApiError } from './api/alfred'
import type { BriefingResponse } from './api/alfred'
import { useMonitorSocket } from './hooks/useMonitorSocket'
import type { MonitorAlert } from './hooks/useMonitorSocket'
import { AudioQueue } from './utils/AudioQueue'

// -----------------------------------------------------------------
// Types exported for child components
// -----------------------------------------------------------------

export type AgentStatus = 'online' | 'processing' | 'offline'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  agentUsed?: string
  intent?: { agent: string; action: string; confidence: number }
  imageUrl?: string
}

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  message: string
  title?: string
  category?: string   // ex: 'weather', 'cpu', 'ram'
}

// -----------------------------------------------------------------
// Session ID — persisted in sessionStorage for page reload resilience
// -----------------------------------------------------------------

function getOrCreateSessionId(): string {
  const stored = sessionStorage.getItem('alfred_session_id')
  if (stored) return stored
  const id = `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  sessionStorage.setItem('alfred_session_id', id)
  return id
}

// -----------------------------------------------------------------
// App
// -----------------------------------------------------------------

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [ragContexts, setRagContexts] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isResearching, setIsResearching] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [notification, setNotification] = useState<Notification | null>(null)
  const [sessionId] = useState<string>(getOrCreateSessionId)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [voiceMode, setVoiceMode] = useState(true)   // ← voz ativa por padrão
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioQueueRef = useRef<AudioQueue | null>(null)

  // ── Proactive Briefing ────────────────────────────────────────────────
  const [briefingData, setBriefingData] = useState<BriefingResponse | null>(null)
  const [showBriefing, setShowBriefing] = useState(false)
  const briefingFetchedRef = useRef(false)       // evita chamadas duplas
  const pendingBriefingAudioRef = useRef<{ b64: string; mime: string } | null>(null)

  // ── Search Panel ────────────────────────────────────────────────

  const agentStatus: AgentStatus = isLoading ? 'processing' : 'online'

  // -----------------------------------------------------------------
  // AudioQueue initialization
  // -----------------------------------------------------------------

  useEffect(() => {
    audioQueueRef.current = new AudioQueue({
      onStart: () => {
        setIsSpeaking(true)
        console.log('🎙️ AudioQueue: Iniciando reprodução')
      },
      onEnd: () => {
        setIsSpeaking(false)
        console.log('✅ AudioQueue: Reprodução concluída')
        // "Ouvido Atento": abre canal de escuta por 3 segundos
        setIsListening(true)
        setTimeout(() => setIsListening(false), 3_000)
      },
      onChunkStart: (current, total) => {
        console.log(`🔊 AudioQueue: Tocando chunk ${current}/${total}`)
      },
      onChunkEnd: (current, total) => {
        console.log(`✓ AudioQueue: Chunk ${current}/${total} concluído`)
      },
      onError: (error) => {
        console.error('❌ AudioQueue: Erro na reprodução:', error)
        setIsSpeaking(false)
      },
    })

    return () => {
      audioQueueRef.current?.stop()
    }
  }, [])

  // -----------------------------------------------------------------
  // Monitor WebSocket — alertas proativos
  // -----------------------------------------------------------------

  const handleMonitorAlert = useCallback(
    (alert: MonitorAlert) => {
      const category = (alert as MonitorAlert & { category?: string }).category

      // Pesquisa web em andamento — ativa o modo roxo do orbe
      if (category === 'research') {
        setIsResearching(true)
      }

      // Streaming de tokens do LLM — exibe texto progressivamente
      if (category === 'stream_token') {
        const token = (alert as MonitorAlert & { message?: string; done?: boolean })
        if (token.done) {
          // não limpa aqui — handleSendMessage limpa quando HTTP responde
        } else if (token.message) {
          setStreamingContent(prev => prev + token.message)
        }
        return
      }

      // Sinal de briefing_ready — busca o briefing e exibe (uma vez por sessão)
      if (category === 'briefing_ready') {
        if (!briefingFetchedRef.current) {
          briefingFetchedRef.current = true
          fetchBriefing()
        }
        return  // não exibe notificação de toast para o briefing
      }

      setNotification({
        id: `monitor_${Date.now()}`,
        type: alert.type,
        message: alert.message,
        title: alert.title,
        category,
      })
    },
    // fetchBriefing definido abaixo; eslint-disable-next-line é intencional
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  useMonitorSocket({ onAlert: handleMonitorAlert })

  // -----------------------------------------------------------------
  // Proactive Briefing — fetch + reproduz áudio + ouvido atento
  // -----------------------------------------------------------------

  // Toca o áudio do briefing (chamado após primeira interação do usuário ou direto)
  const playBriefingAudio = useCallback((b64: string, mime: string) => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    const audio = new Audio(`data:${mime};base64,${b64}`)
    audioRef.current = audio
    setIsSpeaking(true)

    audio.onended = () => {
      setIsSpeaking(false)
      // "Ouvido Atento": abre canal de escuta por 3 segundos
      setIsListening(true)
      setTimeout(() => setIsListening(false), 3_000)
    }
    audio.onerror = () => setIsSpeaking(false)
    audio.play().catch(() => {
      setIsSpeaking(false)
      // Reprisa: guarda para tocar na próxima interação
      pendingBriefingAudioRef.current = { b64, mime }
    })
  }, [])

  const fetchBriefing = useCallback(async () => {
    try {
      const data = await getBriefing()
      setBriefingData(data)
      setShowBriefing(true)

      if (data.audio_data && data.audio_mime) {
        // Tenta reproduzir imediatamente; se o browser bloquear autoplay,
        // guarda o áudio e registra listener para a primeira interação.
        const b64 = data.audio_data
        const mime = data.audio_mime

        const tryPlay = () => {
          pendingBriefingAudioRef.current = null
          playBriefingAudio(b64, mime)
        }

        // Tenta direto (funciona se já houve alguma interação)
        const testAudio = new Audio()
        testAudio.src = `data:${mime};base64,${b64}`
        testAudio.play()
          .then(() => {
            testAudio.onended = null
            testAudio.pause()
            testAudio.src = ''
            playBriefingAudio(b64, mime)
          })
          .catch(() => {
            // Autoplay bloqueado — aguarda primeiro clique/teclado do usuário
            pendingBriefingAudioRef.current = { b64, mime }
            const handler = () => {
              document.removeEventListener('click', handler)
              document.removeEventListener('keydown', handler)
              tryPlay()
            }
            document.addEventListener('click', handler, { once: true })
            document.addEventListener('keydown', handler, { once: true })
          })
      }
    } catch {
      // falha silenciosa — briefing é opcional
    }
  }, [playBriefingAudio])

  // -----------------------------------------------------------------
  // Notification helpers
  // -----------------------------------------------------------------

  const showNotification = useCallback(
    (type: Notification['type'], message: string) => {
      setNotification({ id: Date.now().toString(), type, message })
    },
    [],
  )


  // -----------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------

  const handleSendMessage = useCallback(
    async (content: string, imageData?: string | null) => {
      if (!content.trim() && !imageData || isLoading) return

      const userMsg: Message = {
        id: `u_${Date.now()}`,
        role: 'user',
        content: content.trim() || '(imagem enviada)',
        timestamp: new Date(),
        imageUrl: imageData ? `data:image/png;base64,${imageData}` : undefined,
      }

      setMessages((prev) => [...prev, userMsg])
      setIsLoading(true)
      setRagContexts([])

      try {
        const data = await sendMessage(
          sessionId,
          content.trim() || 'Analise esta imagem.',
          imageData,
          voiceMode,   // audio_response
        )

        const assistantMsg: Message = {
          id: `a_${Date.now()}`,
          role: 'assistant',
          content: data.response,
          timestamp: new Date(),
          agentUsed: data.agent_used,
          intent: data.intent,
        }

        setMessages((prev) => [...prev, assistantMsg])

        if (data.rag_contexts.length > 0) {
          setRagContexts(data.rag_contexts)
        }

        // ── Reproduce TTS — SISTEMA DE FILA DE ÁUDIO ──────────────────────────────────
        // Usa audio_chunks (novo sistema) ou fallback para audio_data (legacy)
        if (data.audio_chunks && data.audio_chunks.length > 0) {
          console.log(`🎵 Recebido ${data.audio_chunks.length} chunks de áudio`)
          audioQueueRef.current?.enqueue(data.audio_chunks)
        } else if (data.audio_data && data.audio_mime) {
          // Backward compatibility: áudio único (legacy)
          console.log('🎵 Recebido áudio único (modo legacy)')
          playAudio(data.audio_data, data.audio_mime)
        }
      } catch (err) {
        const detail =
          err instanceof AlfredApiError
            ? err.message
            : 'Falha na comunicação com o servidor. Verifique se a API está rodando em localhost:8000.'
        showNotification('error', detail)
      } finally {
        setIsLoading(false)
        setIsResearching(false)
        setStreamingContent('')   // limpa o texto de streaming
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, isLoading, voiceMode, showNotification],
  )

  // -------------------------------------------------------------------
  // Audio playback (TTS)
  // -------------------------------------------------------------------

  const playAudio = useCallback((b64: string, mime: string) => {
    // Para áudio anterior se ainda estiver tocando
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }

    const audio = new Audio(`data:${mime};base64,${b64}`)
    audioRef.current = audio
    setIsSpeaking(true)

    audio.onended = () => setIsSpeaking(false)
    audio.onerror = () => setIsSpeaking(false)
    audio.play().catch(() => setIsSpeaking(false))
  }, [])

  const stopAudio = useCallback(() => {
    // Para tanto o sistema legado quanto a AudioQueue
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    audioQueueRef.current?.stop()
    setIsSpeaking(false)
  }, [])

  const handleScreenshot = useCallback(async () => {
    if (isLoading) return
    showNotification('info', 'Capturando screenshot...')
    try {
      const { image_data } = await takeScreenshot()
      await handleSendMessage('Analise este screenshot da minha tela.', image_data)
    } catch (err) {
      const detail = err instanceof AlfredApiError ? err.message : 'Erro ao capturar screenshot.'
      showNotification('error', detail)
    }
  }, [isLoading, showNotification, handleSendMessage])

  const handleClearSession = useCallback(async () => {
    try {
      await clearSession(sessionId)
      setMessages([])
      setRagContexts([])
      showNotification('info', 'Sessão e memórias desta conversa foram limpas.')
    } catch {
      showNotification('warning', 'Erro ao limpar a sessão no servidor.')
    }
  }, [sessionId, showNotification])

  // -----------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------

  return (
    <div className="flex h-screen w-screen bg-nm-base overflow-hidden font-mono select-none">
      {/* Sidebar esquerda */}
      <Sidebar
        agentStatus={agentStatus}
        sessionId={sessionId}
        onClearSession={handleClearSession}
        isResearching={isResearching}
      />

      {/* Área central */}
      <main className="flex flex-1 min-w-0 overflow-hidden">
        <ChatArea
          messages={messages}
          isLoading={isLoading}
          onSendMessage={handleSendMessage}
          onScreenshot={handleScreenshot}
          isSpeaking={isSpeaking}
          isListening={isListening}
          voiceMode={voiceMode}
          onToggleVoiceMode={() => { stopAudio(); setVoiceMode((v: boolean) => !v) }}
          onListeningChange={setIsListening}
          sessionId={sessionId}
          streamingContent={streamingContent}
        />
        <ContextPanel contexts={ragContexts} isLoading={isLoading} />
      </main>

      {/* Briefing Matinal Proativo */}
      {showBriefing && briefingData && (
        <BriefingCard
          data={briefingData}
          onDismiss={() => setShowBriefing(false)}
        />
      )}

      {/* Notificação glassmorphism */}
      {notification && (
        <GlassNotification
          notification={notification}
          onClose={() => setNotification(null)}
        />
      )}
    </div>
  )
}
