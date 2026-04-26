/**
 * utils/AudioQueue.ts — Sistema de Fila de Áudio para reprodução sequencial.
 *
 * Gerencia múltiplos chunks de áudio, tocando-os em sequência sem interrupções.
 * Implementa limpeza automática de memória e callbacks para estado de reprodução.
 */

export interface AudioChunk {
    data: string  // base64
    mime: string  // audio/mpeg, audio/wav, etc.
}

export interface AudioQueueOptions {
    onStart?: () => void
    onEnd?: () => void
    onChunkStart?: (index: number, total: number) => void
    onChunkEnd?: (index: number, total: number) => void
    onError?: (error: Error) => void
}

export class AudioQueue {
    private queue: AudioChunk[] = []
    private currentAudio: HTMLAudioElement | null = null
    private isPlaying = false
    private currentIndex = 0
    private options: AudioQueueOptions

    constructor(options: AudioQueueOptions = {}) {
        this.options = options
    }

    /**
     * Adiciona chunks à fila e inicia reprodução automaticamente se não estiver tocando.
     */
    enqueue(chunks: AudioChunk[]): void {
        if (chunks.length === 0) return

        this.queue.push(...chunks)

        // Inicia reprodução automaticamente se não estiver tocando
        if (!this.isPlaying) {
            this.play()
        }
    }

    /**
     * Inicia ou retoma a reprodução da fila.
     */
    private async play(): Promise<void> {
        if (this.isPlaying || this.queue.length === 0) return

        this.isPlaying = true
        this.currentIndex = 0
        this.options.onStart?.()

        await this.playNext()
    }

    /**
     * Toca o próximo chunk na fila.
     */
    private async playNext(): Promise<void> {
        if (this.currentIndex >= this.queue.length) {
            this.finish()
            return
        }

        const chunk = this.queue[this.currentIndex]
        const totalChunks = this.queue.length

        try {
            this.options.onChunkStart?.(this.currentIndex + 1, totalChunks)

            await this.playChunk(chunk)

            this.options.onChunkEnd?.(this.currentIndex + 1, totalChunks)

            // Limpa o chunk da memória após reprodução
            this.queue[this.currentIndex] = { data: '', mime: '' }

            this.currentIndex++

            // Toca o próximo chunk
            await this.playNext()
        } catch (error) {
            this.options.onError?.(error as Error)
            this.finish()
        }
    }

    /**
     * Reproduz um chunk individual de áudio.
     */
    private playChunk(chunk: AudioChunk): Promise<void> {
        return new Promise((resolve, reject) => {
            // Limpa áudio anterior
            if (this.currentAudio) {
                this.currentAudio.pause()
                this.currentAudio.src = ''
                this.currentAudio = null
            }

            const audio = new Audio(`data:${chunk.mime};base64,${chunk.data}`)
            this.currentAudio = audio

            audio.onended = () => {
                resolve()
            }

            audio.onerror = () => {
                reject(new Error(`Falha ao reproduzir chunk ${this.currentIndex + 1}`))
            }

            audio.play().catch(reject)
        })
    }

    /**
     * Finaliza a reprodução e limpa recursos.
     */
    private finish(): void {
        this.isPlaying = false
        this.queue = []
        this.currentIndex = 0

        if (this.currentAudio) {
            this.currentAudio.pause()
            this.currentAudio.src = ''
            this.currentAudio = null
        }

        this.options.onEnd?.()
    }

    /**
     * Para a reprodução imediatamente e limpa a fila.
     */
    stop(): void {
        this.finish()
    }

    /**
     * Retorna true se há áudio sendo reproduzido.
     */
    isCurrentlyPlaying(): boolean {
        return this.isPlaying
    }

    /**
     * Retorna o progresso atual (chunk atual / total de chunks).
     */
    getProgress(): { current: number; total: number } {
        return {
            current: this.currentIndex,
            total: this.queue.length,
        }
    }
}
