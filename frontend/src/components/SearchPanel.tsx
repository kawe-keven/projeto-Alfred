/**
 * components/SearchPanel.tsx — Painel de pesquisa web / notícias em tempo real.
 *
 * • Slide-in do lado direito (framer-motion)
 * • Toggle web / notícias
 * • Resultado como cards com fonte, URL, trecho e data (notícias)
 * • Síntese do LLM na seção inferior
 * • Botão "Enviar para o chat" para cada resultado
 */
import { useState, useCallback, useRef, type KeyboardEvent, type FormEvent } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
    X, Search, Globe, Newspaper, ExternalLink, Clock,
    Loader2, Copy, ChevronDown, ChevronUp, Sparkles,
} from 'lucide-react'
import { search } from '../api/alfred'
import type { SearchResult, SearchType } from '../api/alfred'

// -----------------------------------------------------------------
// Props
// -----------------------------------------------------------------

interface SearchPanelProps {
    onClose: () => void
    onSendToChat: (text: string) => void
}

// -----------------------------------------------------------------
// Result Card
// -----------------------------------------------------------------

interface ResultCardProps {
    result: SearchResult
    index: number
    onSendToChat: (t: string) => void
}

function ResultCard({ result, index, onSendToChat }: ResultCardProps) {
    const [expanded, setExpanded] = useState(false)

    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
            className="p-3 rounded-xl shadow-nm-sm bg-nm-base border border-white/5 group"
        >
            {/* Header */}
            <div className="flex items-start gap-2 mb-1.5">
                {result.source && (
                    <span className="flex-shrink-0 text-[9px] px-1.5 py-0.5 rounded bg-nm-accent/10 text-nm-accent mt-0.5">
                        {result.source}
                    </span>
                )}
                {result.published && (
                    <div className="flex items-center gap-1 text-nm-text-dim text-[9px] flex-shrink-0 mt-0.5">
                        <Clock className="w-2.5 h-2.5" />
                        {result.published.slice(0, 10)}
                    </div>
                )}
            </div>

            {/* Title */}
            <p className="text-nm-text text-[11px] font-medium leading-snug mb-1">
                {result.title}
            </p>

            {/* Body (collapsible) */}
            <p className={`text-nm-text-dim text-[10px] leading-relaxed ${expanded ? '' : 'line-clamp-2'}`}>
                {result.body}
            </p>
            {result.body.length > 100 && (
                <button
                    onClick={() => setExpanded(!expanded)}
                    className="text-[9px] text-nm-accent mt-1 flex items-center gap-0.5 hover:opacity-80"
                >
                    {expanded ? <><ChevronUp className="w-2.5 h-2.5" />Menos</> : <><ChevronDown className="w-2.5 h-2.5" />Mais</>}
                </button>
            )}

            {/* Footer actions */}
            <div className="flex items-center gap-2 mt-2.5 opacity-0 group-hover:opacity-100 transition-opacity">
                {result.url && (
                    <a
                        href={result.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[9px] text-nm-text-dim hover:text-nm-accent transition-colors"
                    >
                        <ExternalLink className="w-2.5 h-2.5" />
                        Abrir
                    </a>
                )}
                <button
                    onClick={() => onSendToChat(`[${result.title}](${result.url})\n${result.body}`)}
                    className="flex items-center gap-1 text-[9px] text-nm-text-dim hover:text-nm-accent transition-colors"
                >
                    <Copy className="w-2.5 h-2.5" />
                    Citar no chat
                </button>
            </div>
        </motion.div>
    )
}

// -----------------------------------------------------------------
// SearchPanel
// -----------------------------------------------------------------

export default function SearchPanel({ onClose, onSendToChat }: SearchPanelProps) {
    const [query, setQuery] = useState('')
    const [searchType, setSearchType] = useState<SearchType>('web')
    const [results, setResults] = useState<SearchResult[]>([])
    const [synthesis, setSynthesis] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [searchTime, setSearchTime] = useState<number | null>(null)
    const [hasSearched, setHasSearched] = useState(false)
    const [synthVisible, setSynthVisible] = useState(true)
    const inputRef = useRef<HTMLInputElement>(null)

    const handleSearch = useCallback(async (e?: FormEvent) => {
        e?.preventDefault()
        const q = query.trim()
        if (!q || isLoading) return

        setIsLoading(true)
        setError(null)
        setResults([])
        setSynthesis(null)
        setHasSearched(true)

        try {
            const data = await search({
                query: q,
                max_results: 8,
                search_type: searchType,
                synthesize: true,
            })
            setResults(data.results)
            setSynthesis(data.synthesis)
            setSearchTime(data.search_time_ms)
        } catch (err: unknown) {
            setError((err as Error).message ?? 'Erro desconhecido na busca.')
        } finally {
            setIsLoading(false)
        }
    }, [query, searchType, isLoading])

    const handleKey = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') handleSearch()
    }, [handleSearch])

    const handleSendSynthesisToChat = useCallback(() => {
        if (!synthesis) return
        onSendToChat(synthesis)
        onClose()
    }, [synthesis, onSendToChat, onClose])

    return (
        <motion.div
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            className="fixed right-0 top-0 h-full w-96 z-40 flex flex-col
                 border-l border-nm-highlight/20 bg-nm-base shadow-[-8px_0_24px_rgba(0,0,0,0.25)]"
        >
            {/* ── HEADER ───────────────────────────────────────────────── */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-nm-highlight/20 flex-shrink-0">
                <div className="w-7 h-7 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center">
                    <Search className="w-3.5 h-3.5 text-nm-accent" />
                </div>
                <span className="text-nm-text text-xs tracking-widest uppercase flex-1">
                    Pesquisa Web
                </span>
                <button
                    onClick={onClose}
                    className="w-7 h-7 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center
                     text-nm-text-dim hover:text-nm-text transition-colors"
                >
                    <X className="w-3.5 h-3.5" />
                </button>
            </div>

            {/* ── SEARCH BAR ───────────────────────────────────────────── */}
            <div className="px-4 py-3 border-b border-nm-highlight/20 flex-shrink-0">
                {/* Toggle web / notícias */}
                <div className="flex gap-2 mb-3">
                    {(['web', 'news'] as SearchType[]).map((type) => (
                        <button
                            key={type}
                            onClick={() => setSearchType(type)}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] tracking-widest uppercase
                          transition-all duration-150
                          ${searchType === type
                                    ? 'shadow-nm-inner bg-nm-base text-nm-accent'
                                    : 'shadow-nm-flat bg-nm-base text-nm-text-dim hover:text-nm-text'}`}
                        >
                            {type === 'web'
                                ? <><Globe className="w-3 h-3" />Web</>
                                : <><Newspaper className="w-3 h-3" />Notícias</>}
                        </button>
                    ))}
                </div>

                {/* Input */}
                <form onSubmit={handleSearch} className="flex gap-2">
                    <div className="flex-1 rounded-xl shadow-nm-pressed bg-nm-base overflow-hidden
                          focus-within:shadow-nm-accent transition-shadow duration-200">
                        <input
                            ref={inputRef}
                            type="text"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onKeyDown={handleKey}
                            placeholder={searchType === 'news' ? 'Buscar notícias...' : 'Pesquisar na web...'}
                            disabled={isLoading}
                            className="w-full px-3 py-2.5 bg-transparent outline-none text-nm-text-bright
                         text-xs placeholder:text-nm-text-dim disabled:opacity-50"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={!query.trim() || isLoading}
                        className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0
                       shadow-nm-flat bg-nm-base text-nm-text-dim
                       hover:text-nm-accent hover:shadow-nm-accent
                       active:shadow-nm-inner disabled:opacity-40
                       transition-all duration-150"
                    >
                        {isLoading
                            ? <Loader2 className="w-4 h-4 animate-spin text-nm-accent" />
                            : <Search className="w-4 h-4" />}
                    </button>
                </form>

                {/* Meta */}
                {searchTime !== null && !isLoading && (
                    <p className="text-nm-text-dim text-[9px] mt-1.5 tracking-wider">
                        {results.length} resultado{results.length !== 1 ? 's' : ''} em {(searchTime / 1000).toFixed(1)} s
                    </p>
                )}
            </div>

            {/* ── RESULTS ──────────────────────────────────────────────── */}
            <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">

                {/* Error */}
                {error && (
                    <div className="p-3 rounded-xl border border-nm-error/30 text-nm-error text-xs">
                        {error}
                    </div>
                )}

                {/* Loading skeleton */}
                {isLoading && (
                    <div className="flex flex-col gap-3">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="p-3 rounded-xl shadow-nm-sm bg-nm-base animate-pulse">
                                <div className="h-2 w-16 rounded bg-nm-text-dim/20 mb-2" />
                                <div className="h-3 w-4/5 rounded bg-nm-text-dim/20 mb-1.5" />
                                <div className="h-2 w-full rounded bg-nm-text-dim/10 mb-1" />
                                <div className="h-2 w-3/4 rounded bg-nm-text-dim/10" />
                            </div>
                        ))}
                    </div>
                )}

                {/* Empty state */}
                {!isLoading && !hasSearched && (
                    <div className="flex flex-col items-center justify-center flex-1 gap-4 text-center py-8">
                        <div className="w-12 h-12 rounded-2xl shadow-nm-flat bg-nm-base flex items-center justify-center">
                            <Globe className="w-5 h-5 text-nm-text-dim" />
                        </div>
                        <div>
                            <p className="text-nm-text text-sm">Pesquise na web</p>
                            <p className="text-nm-text-dim text-[10px] mt-1 leading-relaxed max-w-[180px]">
                                Busque notícias, preços, informações atuais e muito mais
                            </p>
                        </div>
                    </div>
                )}

                {/* No results */}
                {!isLoading && hasSearched && results.length === 0 && !error && (
                    <p className="text-nm-text-dim text-xs text-center py-8">
                        Nenhum resultado encontrado para "{query}".
                    </p>
                )}

                {/* Result cards */}
                {!isLoading && results.map((r, i) => (
                    <ResultCard key={r.url || i} result={r} index={i} onSendToChat={onSendToChat} />
                ))}
            </div>

            {/* ── SYNTHESIS ────────────────────────────────────────────── */}
            <AnimatePresence>
                {synthesis && !isLoading && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25 }}
                        className="border-t border-nm-highlight/20 flex-shrink-0"
                    >
                        <div className="px-4 py-3">
                            {/* Header */}
                            <div className="flex items-center gap-2 mb-2">
                                <Sparkles className="w-3.5 h-3.5 text-nm-accent" />
                                <span className="text-nm-text-dim text-[9px] tracking-widest uppercase flex-1">
                                    Síntese do Alfred
                                </span>
                                <button
                                    onClick={() => setSynthVisible(!synthVisible)}
                                    className="text-nm-text-dim hover:text-nm-text transition-colors"
                                >
                                    {synthVisible
                                        ? <ChevronDown className="w-3.5 h-3.5" />
                                        : <ChevronUp className="w-3.5 h-3.5" />}
                                </button>
                            </div>

                            {synthVisible && (
                                <>
                                    <p className="text-nm-text text-[11px] leading-relaxed max-h-32 overflow-y-auto">
                                        {synthesis}
                                    </p>
                                    <button
                                        onClick={handleSendSynthesisToChat}
                                        className="mt-2.5 w-full py-2 rounded-xl shadow-nm-flat bg-nm-base
                               text-[10px] text-nm-accent tracking-widest uppercase
                               hover:shadow-nm-inner transition-shadow"
                                    >
                                        Enviar síntese para o chat
                                    </button>
                                </>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    )
}
