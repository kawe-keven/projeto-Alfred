/**
 * components/WeatherWidget.tsx — Cards neumórficos multi-cidade.
 *
 * Renderiza um card individual por cidade com:
 *  • Ícone dinâmico (lucide-react) baseado na condição climática
 *  • Temperatura com indicador colorido (bg-nm-accent)
 *  • shadow-nm-inner quando o clima é chuvoso / tempestuoso
 *  • Anel de alerta `ring-nm-error` se temp > 32 °C ou Thunderstorm
 *  • Badge de comparação quando monitorando ≥ 2 cidades
 */
import {
    Sun, Cloud, CloudRain, CloudDrizzle, CloudLightning,
    CloudSnow, Wind, Droplets, AlertTriangle,
} from 'lucide-react'
import type { WeatherData } from '../api/alfred'

// -----------------------------------------------------------------
// Icon + style helpers
// -----------------------------------------------------------------

function WeatherIcon({ main, className }: { main: string; className?: string }) {
    const props = { className: className ?? 'w-4 h-4' }
    switch (main) {
        case 'Clear': return <Sun          {...props} />
        case 'Clouds': return <Cloud        {...props} />
        case 'Rain': return <CloudRain    {...props} />
        case 'Drizzle': return <CloudDrizzle {...props} />
        case 'Thunderstorm': return <CloudLightning {...props} />
        case 'Snow': return <CloudSnow    {...props} />
        default: return <Wind         {...props} />
    }
}

function iconColor(main: string): string {
    switch (main) {
        case 'Clear': return 'text-nm-warning'
        case 'Clouds': return 'text-nm-text'
        case 'Rain':
        case 'Drizzle': return 'text-nm-cyan'
        case 'Thunderstorm': return 'text-nm-error'
        case 'Snow': return 'text-nm-text-bright'
        default: return 'text-nm-text-dim'
    }
}

/** Cards afundam (shadow-nm-inner) para clima chuvoso — sensação de "peso" visual */
function cardShadow(main: string): string {
    return ['Rain', 'Drizzle', 'Thunderstorm'].includes(main)
        ? 'shadow-nm-inner'
        : 'shadow-nm-pressed'
}

function isCriticalCondition(weather: WeatherData): boolean {
    return (!weather.error && (weather.temp > 32 || weather.main === 'Thunderstorm'))
}

// -----------------------------------------------------------------
// Temperature comparison badge (≥ 2 cidades)
// -----------------------------------------------------------------

interface CompareResult { hotter: string; delta: number }

function getComparison(cities: WeatherData[]): CompareResult | null {
    const valid = cities.filter((c) => !c.error && c.temp !== undefined)
    if (valid.length < 2) return null
    const [a, b] = valid
    if (a.temp === b.temp) return null
    return a.temp > b.temp
        ? { hotter: a.city, delta: a.temp - b.temp }
        : { hotter: b.city, delta: b.temp - a.temp }
}

// -----------------------------------------------------------------
// Single city card
// -----------------------------------------------------------------

function CityCard({ weather }: { weather: WeatherData }) {
    if (weather.error) {
        const is401 = weather.error.includes('401') || weather.error.includes('Unauthorized')
        const isTimeout = weather.error.includes('timeout') || weather.error.includes('timed out')
        const hint = is401
            ? 'Chave API inválida — atualize OPENWEATHERMAP_API_KEY no .env'
            : isTimeout
                ? 'Timeout — verifique a conexão'
                : 'Dados indisponíveis'
        return (
            <div className="p-3 rounded-xl shadow-nm-pressed bg-nm-base flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-nm-warning flex-shrink-0 mt-0.5" />
                <div>
                    <p className="text-nm-text text-[11px] font-semibold">{weather.city}</p>
                    <p className="text-nm-warning text-[10px] mt-0.5 leading-tight">{hint}</p>
                </div>
            </div>
        )
    }

    const critical = isCriticalCondition(weather)

    return (
        <div
            className={[
                'p-3 rounded-xl bg-nm-base transition-all duration-300',
                cardShadow(weather.main),
                critical ? 'ring-1 ring-nm-error/40' : '',
            ].join(' ')}
        >
            {/* Header — nome + ícone */}
            <div className="flex items-center justify-between mb-2">
                <p className="text-nm-text-bright text-[11px] font-semibold tracking-wide truncate">
                    {weather.city}
                </p>
                <div className="w-7 h-7 rounded-lg shadow-nm-sm bg-nm-base flex items-center justify-center flex-shrink-0">
                    <WeatherIcon
                        main={weather.main}
                        className={`w-4 h-4 ${iconColor(weather.main)}`}
                    />
                </div>
            </div>

            {/* Temperatura */}
            <div className="flex items-end gap-2">
                <span className="w-2 h-2 rounded-full flex-shrink-0 bg-nm-accent self-center" />
                <span className="text-nm-text-bright text-lg font-bold leading-none">
                    {weather.temp}°C
                </span>
                {critical && (
                    <span className="text-nm-error text-[9px] uppercase tracking-wider font-bold mb-0.5">
                        {weather.main === 'Thunderstorm' ? 'tempestade' : 'calor crítico'}
                    </span>
                )}
            </div>

            {/* Sensação + umidade */}
            <div className="mt-1.5 pt-1.5 border-t border-nm-highlight/20 flex items-center justify-between">
                <p className="text-nm-text-dim text-[10px]">Sens. {weather.feels_like}°C</p>
                <div className="flex items-center gap-1">
                    <Droplets className="w-2.5 h-2.5 text-nm-cyan" />
                    <p className="text-nm-text-dim text-[10px]">{weather.humidity}%</p>
                </div>
            </div>

            {/* Condição textual */}
            <p className="text-nm-text-dim text-[10px] mt-1 truncate">{weather.description}</p>
        </div>
    )
}

// -----------------------------------------------------------------
// Public component
// -----------------------------------------------------------------

export interface WeatherWidgetProps {
    cities: WeatherData[]
    loading?: boolean
}

export default function WeatherWidget({ cities, loading }: WeatherWidgetProps) {
    if (loading && cities.length === 0) {
        return (
            <div className="flex flex-col gap-2 animate-pulse">
                <div className="h-24 rounded-xl shadow-nm-pressed bg-nm-base opacity-60" />
                <div className="h-24 rounded-xl shadow-nm-pressed bg-nm-base opacity-60" />
            </div>
        )
    }

    if (cities.length === 0) return null

    const comparison = getComparison(cities)

    return (
        <div className="flex flex-col gap-2 animate-fade-in">
            {cities.map((city) => (
                <CityCard key={city.city} weather={city} />
            ))}

            {/* Badge de comparação entre cidades */}
            {comparison && (
                <div className="px-2.5 py-1.5 rounded-lg shadow-nm-pressed bg-nm-base flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-nm-accent flex-shrink-0" />
                    <p className="text-nm-text-dim text-[10px] leading-tight">
                        <span className="text-nm-accent font-semibold">{comparison.hotter}</span>
                        {' '}está {comparison.delta}°C mais quente hoje.
                    </p>
                </div>
            )}
        </div>
    )
}
