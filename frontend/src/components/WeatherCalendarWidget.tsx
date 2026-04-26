/**
 * components/WeatherCalendarWidget.tsx — Widget neumórfico de clima e agenda.
 *
 * Busca GET /api/widget/status ao montar e refresca a cada 5 minutos.
 * Exibe:
 *  • Card de clima: ícone, temperatura, cidade, condição.
 *  • Card de agenda: próxima tarefa do dia + contagem de tarefas restantes.
 *
 * Trata graciosamente: ausência de chave API, falha de rede, calendário vazio.
 */
import { useEffect, useState, useCallback } from 'react'
import { CalendarDays, Clock, RefreshCw, AlertCircle } from 'lucide-react'
import { getWidgetStatus } from '../api/alfred'
import type { WidgetStatus, CalendarTask } from '../api/alfred'
import WeatherWidget from './WeatherWidget'

// -----------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------

function formatTime(isoString: string): string {
  try {
    const d = new Date(isoString)
    return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '--:--'
  }
}

function taskTypeIcon(type: CalendarTask['type']): string {
  return { meeting: '📅', deadline: '⏰', task: '✅' }[type] ?? '📝'
}

const REFRESH_INTERVAL = 5 * 60 * 1000   // 5 minutos

// -----------------------------------------------------------------
// Component
// -----------------------------------------------------------------

export default function WeatherCalendarWidget() {
  const [data,      setData]      = useState<WidgetStatus | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getWidgetStatus()
      setData(result)
      setLastFetch(new Date())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar widget.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const timer = setInterval(fetchData, REFRESH_INTERVAL)
    return () => clearInterval(timer)
  }, [fetchData])

  // -----------------------------------------------------------------
  // Skeleton loader
  // -----------------------------------------------------------------
  if (loading && !data) {
    return (
      <div className="flex flex-col gap-2 animate-pulse">
        <div className="h-20 rounded-xl shadow-nm-pressed bg-nm-base opacity-60" />
        <div className="h-16 rounded-xl shadow-nm-pressed bg-nm-base opacity-60" />
      </div>
    )
  }

  // -----------------------------------------------------------------
  // Error state
  // -----------------------------------------------------------------
  if (error && !data) {
    return (
      <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base flex items-start gap-2">
        <AlertCircle className="w-4 h-4 text-nm-error flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-nm-error text-[10px] font-semibold uppercase tracking-wider">
            Widget indisponível
          </p>
          <p className="text-nm-text-dim text-[10px] leading-tight mt-0.5 break-words">
            {error}
          </p>
        </div>
      </div>
    )
  }

  if (!data) return null

  // Prefere a lista multi-cidade; fallback para o campo legado `weather`
  const weatherCities = data.cities && data.cities.length > 0
    ? data.cities
    : [data.weather]
  const calendar = data.calendar

  // -----------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------
  return (
    <div className="flex flex-col gap-2 animate-fade-in">

      {/* ── Weather cards (multi-cidade) ─────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase px-1">
            Clima
          </p>
          <button
            onClick={fetchData}
            title="Atualizar"
            className="
              w-5 h-5 rounded-md shadow-nm-sm bg-nm-base
              flex items-center justify-center
              text-nm-text-dim hover:text-nm-accent
              transition-colors duration-150
            "
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin-slow' : ''}`} />
          </button>
        </div>
        <WeatherWidget cities={weatherCities} loading={loading && !data} />
      </div>

      {/* ── Calendar card ─────────────────────────────────────────── */}
      <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base">
        {/* Header */}
        <div className="flex items-center gap-1.5 mb-2">
          <CalendarDays className="w-3 h-3 text-nm-accent" />
          <p className="text-nm-text-dim text-[9px] tracking-[0.2em] uppercase">
            Agenda
          </p>
          {calendar.today_count > 0 && (
            <span className="
              ml-auto px-1.5 py-0.5 rounded-full
              text-[9px] font-bold text-nm-base
              bg-nm-accent
            ">
              {calendar.today_count}
            </span>
          )}
        </div>

        {calendar.next_task ? (
          <div>
            <div className="flex items-start gap-1.5">
              <span className="text-sm leading-none mt-0.5" aria-hidden>
                {taskTypeIcon(calendar.next_task.type)}
              </span>
              <div className="min-w-0">
                <p className="text-nm-text text-[11px] leading-tight line-clamp-2">
                  {calendar.next_task.title}
                </p>
                <div className="flex items-center gap-1 mt-1">
                  <Clock className="w-2.5 h-2.5 text-nm-text-dim flex-shrink-0" />
                  <p className="text-nm-accent text-[10px] font-mono">
                    {formatTime(calendar.next_task.datetime)}
                  </p>
                </div>
              </div>
            </div>
            {calendar.today_count > 1 && (
              <p className="text-nm-text-dim text-[10px] mt-1.5 pt-1.5 border-t border-nm-highlight/20">
                +{calendar.today_count - 1} mais hoje
              </p>
            )}
          </div>
        ) : (
          <p className="text-nm-text-dim text-[10px] leading-relaxed">
            ✅ Nenhuma tarefa pendente.
          </p>
        )}
      </div>

      {/* Last refresh */}
      {lastFetch && (
        <p className="text-nm-text-dim text-[9px] text-center opacity-50">
          Atualizado às {lastFetch.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
        </p>
      )}
    </div>
  )
}
