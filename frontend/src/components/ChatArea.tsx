/**
 * components/ChatArea.tsx — Área principal de conversa.
 *
 * • Empty state com ParticleOrb grande e texto de boas-vindas.
 * • Lista de mensagens com auto-scroll para baixo.
 * • Indicador de "digitando" animado enquanto Alfred processa.
 * • Input neumórfico: Enter envia, Shift+Enter quebra linha.
 * • Drag-and-drop de imagens + botão screenshot.
 */
import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type KeyboardEvent,
  type FormEvent,
  type ChangeEvent,
  type DragEvent,
} from 'react'
import { Send, Cpu, Camera, X, Image as ImageIcon, Mic, MicOff, Volume2, VolumeX } from 'lucide-react'
import type { Message } from '../App'
import MessageBubble from './MessageBubble'
import ParticleOrb from './ParticleOrb'
import VoiceVisualizer from './VoiceVisualizer'

// -----------------------------------------------------------------
// Typing indicator
// -----------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="w-8 h-8 rounded-full flex-shrink-0 shadow-nm-sm bg-nm-base flex items-center justify-center mt-1">
        <Cpu className="w-4 h-4 text-nm-success animate-pulse-slow" />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-nm-text-dim text-[10px] tracking-widest uppercase px-1">Alfred</span>
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm shadow-nm-flat bg-nm-base border-l-2 border-nm-success/30">
          <div className="flex items-center gap-1.5 h-5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-nm-success inline-block"
                style={{
                  animation: `blink 1.4s ease-in-out ${i * 0.2}s infinite`,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// -----------------------------------------------------------------
// Empty State
// -----------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 animate-fade-in">
      <div className="animate-float">
        <ParticleOrb isLoading={false} size={120} />
      </div>
      <div className="text-center">
        <h2 className="text-nm-text-bright text-xl font-light tracking-[0.2em] mb-2">
          Como posso ajudar?
        </h2>
        <p className="text-nm-text-dim text-xs tracking-wider max-w-xs leading-relaxed">
          Envie uma mensagem para iniciar a conversa.
          Minhas memórias anteriores serão recuperadas automaticamente.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 mt-2 w-72">
        {[
          'O que você consegue fazer?',
          'Resuma nossos papos anteriores',
          'Me ajude a planejar um projeto',
          'Explique machine learning',
        ].map((hint) => (
          <div
            key={hint}
            className="p-3 rounded-xl shadow-nm-sm bg-nm-base text-nm-text-dim text-[11px]
                       text-center leading-relaxed cursor-default hover:text-nm-text
                       transition-colors duration-200"
          >
            {hint}
          </div>
        ))}
      </div>
    </div>
  )
}

// -----------------------------------------------------------------
// ChatArea
// -----------------------------------------------------------------

interface ChatAreaProps {
  messages: Message[]
  isLoading: boolean
  onSendMessage: (content: string, imageData?: string | null) => void
  onScreenshot: () => void
  isSpeaking: boolean
  isListening: boolean
  voiceMode: boolean
  onToggleVoiceMode: () => void
  onListeningChange: (v: boolean) => void
  sessionId: string
  streamingContent?: string
}

export default function ChatArea({
  messages,
  isLoading,
  onSendMessage,
  onScreenshot,
  isSpeaking,
  isListening,
  voiceMode,
  onToggleVoiceMode,
  onListeningChange,
  sessionId: _sessionId,
  streamingContent = '',
}: ChatAreaProps) {
  const [input, setInput] = useState('')
  const [pendingImage, setPendingImage] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)

  // Auto-scroll para a última mensagem
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, streamingContent])

  // Ajusta altura do textarea dinamicamente
  const adjustHeight = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [])

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault()
      const trimmed = input.trim()
      if (!trimmed && !pendingImage || isLoading) return
      onSendMessage(trimmed, pendingImage)
      setInput('')
      setPendingImage(null)
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto'
      }
    },
    [input, pendingImage, isLoading, onSendMessage],
  )

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit],
  )

  const canSend = (input.trim().length > 0 || !!pendingImage) && !isLoading

  // ── Web Speech API (STT no navegador) ────────────────────────────
  const handleMicToggle = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionAPI = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognitionAPI) {
      alert('Web Speech API não suportada neste navegador. Use Chrome ou Edge.')
      return
    }

    if (isListening) {
      recognitionRef.current?.stop()
      return
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const recognition: any = new SpeechRecognitionAPI()
    recognition.lang = 'pt-BR'
    recognition.interimResults = false
    recognition.maxAlternatives = 1
    recognition.continuous = false
    recognitionRef.current = recognition

    recognition.onstart = () => onListeningChange(true)
    recognition.onend = () => onListeningChange(false)
    recognition.onerror = () => onListeningChange(false)

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript as string
      onSendMessage(transcript, pendingImage)
      setPendingImage(null)
    }

    recognition.start()
  }, [isListening, onListeningChange, onSendMessage, pendingImage])

  // ── Image helpers ──────────────────────────────────────────────
  const loadFileAsBase64 = (file: File) => {
    if (!file.type.startsWith('image/')) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const result = ev.target?.result as string
      // Strip data URL prefix — backend expects raw base64
      setPendingImage(result.replace(/^data:image\/[a-z]+;base64,/, ''))
    }
    reader.readAsDataURL(file)
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = () => setIsDragOver(false)

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) loadFileAsBase64(file)
  }

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) loadFileAsBase64(file)
    // Reset so the same file can be re-selected
    e.target.value = ''
  }

  return (
    <div
      className={`flex-1 flex flex-col min-w-0 overflow-hidden relative transition-all duration-200
        ${isDragOver ? 'ring-2 ring-nm-accent/60 ring-inset' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragOver && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center
                        bg-nm-base/90 backdrop-blur-sm pointer-events-none animate-fade-in">
          <ImageIcon className="w-16 h-16 text-nm-accent mb-4 animate-float" />
          <p className="text-nm-accent text-sm tracking-widest uppercase">Solte a imagem aqui</p>
        </div>
      )}

      {/* ── HEADER ───────────────────────────────────────────────── */}
      <header className="flex items-center px-6 py-3 border-b border-nm-highlight/20 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center">
            <Cpu className="w-3.5 h-3.5 text-nm-accent" />
          </div>
          <span className="text-nm-text text-xs tracking-widest uppercase">
            Conversa
          </span>
        </div>
        {/* Visualizador de voz — sempre visível na header, anima quando ativo */}
        <div className="flex-1 flex justify-center">
          <VoiceVisualizer isListening={isListening} isSpeaking={isSpeaking} barCount={16} />
        </div>
        {messages.length > 0 && (
          <span className="ml-auto text-nm-text-dim text-[10px]">
            {messages.length} mensagem{messages.length !== 1 ? 's' : ''}
          </span>
        )}
      </header>

      {/* ── MESSAGES ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && !isLoading ? (
          <EmptyState />
        ) : (
          <div className="flex flex-col gap-5 max-w-3xl mx-auto">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {/* Streaming parcial — exibe tokens em tempo real antes da resposta final */}
            {isLoading && streamingContent && (
              <MessageBubble
                key="streaming"
                message={{
                  id: 'streaming',
                  role: 'assistant',
                  content: streamingContent + '█',
                  timestamp: new Date(),
                }}
              />
            )}
            {/* Typing indicator apenas quando sem streaming ainda */}
            {isLoading && !streamingContent && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* ── INPUT ────────────────────────────────────────────────── */}
      <div className="px-6 py-4 border-t border-nm-highlight/20 flex-shrink-0">

        {/* Image preview */}
        {pendingImage && (
          <div className="max-w-3xl mx-auto mb-3 flex items-start gap-2 animate-slide-up">
            <div className="relative inline-block rounded-xl overflow-hidden shadow-nm-flat border border-nm-accent/20">
              <img
                src={`data:image/png;base64,${pendingImage}`}
                alt="Prévia da imagem"
                className="max-h-32 max-w-xs object-cover"
              />
              <button
                type="button"
                onClick={() => setPendingImage(null)}
                className="absolute top-1 right-1 w-5 h-5 rounded-full bg-nm-base/80
                           flex items-center justify-center text-nm-text-dim
                           hover:text-nm-text transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
            <span className="text-nm-text-dim text-[10px] tracking-wider mt-1">
              Imagem pronta para envio
            </span>
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          className="flex items-end gap-3 max-w-3xl mx-auto"
        >
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />

          {/* Mic button — Web Speech API */}
          <button
            type="button"
            onClick={handleMicToggle}
            disabled={isLoading || isSpeaking}
            title={isListening ? 'Parar de ouvir' : 'Falar com Alfred'}
            className={`
              w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0
              transition-all duration-200
              ${isListening
                ? 'shadow-nm-inner bg-nm-base text-nm-success ring-1 ring-nm-success/40 animate-pulse-slow'
                : 'shadow-nm-flat bg-nm-base text-nm-text-dim hover:text-nm-success hover:shadow-nm-success'
              }
              disabled:opacity-40 disabled:cursor-not-allowed
            `}
          >
            {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>

          {/* Voice mode toggle (Alfred responde com áudio) */}
          <button
            type="button"
            onClick={onToggleVoiceMode}
            title={voiceMode ? 'Desativar resposta em voz' : 'Ativar resposta em voz'}
            className={`
              w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0
              transition-all duration-200
              ${voiceMode
                ? 'shadow-nm-inner bg-nm-base text-nm-accent ring-1 ring-nm-accent/40'
                : 'shadow-nm-flat bg-nm-base text-nm-text-dim hover:text-nm-accent hover:shadow-nm-accent'
              }
            `}
          >
            {voiceMode ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          </button>

          {/* Screenshot button */}
          <button
            type="button"
            onClick={onScreenshot}
            disabled={isLoading}
            title="Capturar screenshot"
            className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0
                       shadow-nm-flat bg-nm-base text-nm-text-dim
                       hover:text-nm-accent hover:shadow-nm-accent
                       active:shadow-nm-inner disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all duration-200"
          >
            <Camera className="w-4 h-4" />
          </button>

          {/* Upload image button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            title="Enviar imagem"
            className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0
                       shadow-nm-flat bg-nm-base text-nm-text-dim
                       hover:text-nm-accent hover:shadow-nm-accent
                       active:shadow-nm-inner disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all duration-200"
          >
            <ImageIcon className="w-4 h-4" />
          </button>

          {/* Textarea neumórfico */}
          <div className="flex-1 rounded-2xl shadow-nm-pressed bg-nm-base overflow-hidden
                          focus-within:shadow-nm-accent transition-shadow duration-300">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => { setInput(e.target.value); adjustHeight() }}
              onKeyDown={handleKeyDown}
              placeholder={pendingImage ? 'Pergunte sobre a imagem… (Enter para enviar)' : 'Mensagem para o Alfred…  (Enter para enviar, Shift+Enter para quebrar linha)'}
              disabled={isLoading}
              rows={1}
              className="
                w-full px-4 py-3 bg-transparent resize-none outline-none
                text-nm-text-bright text-sm placeholder:text-nm-text-dim
                leading-relaxed disabled:opacity-50
              "
              style={{ minHeight: '48px', maxHeight: '140px' }}
            />
          </div>

          {/* Botão de envio */}
          <button
            type="submit"
            disabled={!canSend}
            className={`
              w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0
              transition-all duration-200
              ${canSend
                ? 'shadow-nm-accent bg-nm-base text-nm-accent hover:shadow-nm-inner active:shadow-nm-inner'
                : 'shadow-nm-flat bg-nm-base text-nm-text-dim cursor-not-allowed opacity-50'
              }
            `}
          >
            {isLoading
              ? <ParticleOrb isLoading size={28} />
              : <Send className="w-4 h-4" />
            }
          </button>
        </form>

        <p className="text-nm-text-dim text-[10px] text-center mt-2 tracking-wider">
          Alfred pode cometer erros. Verifique informações importantes.
        </p>
      </div>
    </div>
  )
}
