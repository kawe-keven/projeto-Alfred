/**
 * api/alfred.ts — Cliente Axios para a API Alfred (FastAPI).
 *
 * Todas as requisições são prefixadas com /api, que o Vite Dev Server
 * faz proxy para http://localhost:8000 automaticamente.
 */
import axios, { AxiosError } from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 180_000,  // 3 min — LLM + TTS pode demorar 60-90 s
})

// -----------------------------------------------------------------
// Types
// -----------------------------------------------------------------

export interface ChatRequest {
  session_id: string
  message: string
  image_data?: string | null
  audio_response?: boolean
}

export interface IntentInfo {
  agent: string
  action: string
  confidence: number
}

export interface ChatResponse {
  session_id: string
  message: string
  response: string
  agent_used: string
  rag_contexts_used: number
  rag_contexts: string[]
  intent: IntentInfo
  audio_data?: string | null
  audio_mime?: string | null
  audio_chunks?: Array<{ data: string; mime: string }> | null
}

export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface HistoryEntry {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  metadata: Record<string, unknown>
}

export interface ScreenshotResponse {
  image_data: string
  width: number
  height: number
}

export class AlfredApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'AlfredApiError'
  }
}

// -----------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------

function handleError(err: unknown): never {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail ?? err.message
    throw new AlfredApiError(String(detail), err.response?.status)
  }
  throw err
}

// -----------------------------------------------------------------
// Endpoints
// -----------------------------------------------------------------

export async function sendMessage(
  session_id: string,
  message: string,
  image_data?: string | null,
  audio_response?: boolean,
): Promise<ChatResponse> {
  try {
    const { data } = await api.post<ChatResponse>('/chat', {
      session_id,
      message,
      image_data: image_data ?? null,
      audio_response: audio_response ?? false,
    })
    return data
  } catch (err) {
    return handleError(err)
  }
}

export async function takeScreenshot(): Promise<ScreenshotResponse> {
  try {
    const { data } = await api.post<ScreenshotResponse>('/screenshot')
    return data
  } catch (err) {
    return handleError(err)
  }
}

export async function getHealth(): Promise<HealthResponse> {
  try {
    const { data } = await api.get<HealthResponse>('/health')
    return data
  } catch (err) {
    return handleError(err)
  }
}

export async function getHistory(
  session_id: string,
  limit = 20,
): Promise<HistoryEntry[]> {
  try {
    const { data } = await api.get<HistoryEntry[]>(`/session/${session_id}`, {
      params: { limit },
    })
    return data
  } catch (err) {
    return handleError(err)
  }
}

export async function clearSession(session_id: string): Promise<void> {
  try {
    await api.delete(`/session/${session_id}`)
  } catch (err) {
    return handleError(err)
  }
}

// -----------------------------------------------------------------
// Widget status — clima + calendário para a Sidebar
// -----------------------------------------------------------------

export interface WeatherData {
  city: string
  temp: number
  feels_like: number
  humidity: number
  description: string
  main: string
  icon: string
  wind_speed: number
  error?: string
}

export interface CalendarTask {
  title: string
  datetime: string
  type: 'meeting' | 'deadline' | 'task'
}

export interface CalendarData {
  today_count: number
  next_task: CalendarTask | null
}

export interface WidgetStatus {
  weather: WeatherData        // primeira cidade (retrocompat)
  cities?: WeatherData[]      // todas as cidades monitoradas
  calendar: CalendarData
  fetched_at: string
}

export async function getWidgetStatus(): Promise<WidgetStatus> {
  try {
    const { data } = await api.get<WidgetStatus>('/widget/status')
    return data
  } catch (err) {
    return handleError(err)
  }
}

// -----------------------------------------------------------------
// Proactive Briefing
// -----------------------------------------------------------------

export interface BriefingResponse {
  text: string
  topics: string[]
  weather_city: string
  cpu: number
  ram: number
  audio_data: string | null
  audio_mime: string | null
}

export async function getBriefing(): Promise<BriefingResponse> {
  try {
    const { data } = await api.get<BriefingResponse>('/briefing')
    return data
  } catch (err) {
    return handleError(err)
  }
}

// -----------------------------------------------------------------
// Search API
// -----------------------------------------------------------------

export type SearchType = 'web' | 'news'

export interface SearchRequest {
  query: string
  max_results?: number        // 1–20, default 8
  search_type?: SearchType    // 'web' | 'news', default 'web'
  synthesize?: boolean       // default true
  audio_response?: boolean      // default false
}

export interface SearchResult {
  title: string
  url: string
  body: string
  source: string
  published: string | null
}

export interface SearchResponse {
  query: string
  search_type: string
  results: SearchResult[]
  result_count: number
  synthesis: string | null
  audio_data: string | null
  audio_mime: string | null
  search_time_ms: number
}

export async function search(req: SearchRequest): Promise<SearchResponse> {
  try {
    const { data } = await api.post<SearchResponse>('/search', {
      query: req.query,
      max_results: req.max_results ?? 8,
      search_type: req.search_type ?? 'web',
      synthesize: req.synthesize ?? true,
      audio_response: req.audio_response ?? false,
    })
    return data
  } catch (err) {
    return handleError(err)
  }
}
