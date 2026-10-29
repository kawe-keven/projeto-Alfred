CREATE TABLE latencia_turnos (
    id TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL CHECK (ts_ms >= 0),
    interface TEXT NOT NULL CHECK (interface IN ('cli', 'voz')),
    perfil_desempenho TEXT NOT NULL,
    motor_tts TEXT,
    modelo_stt TEXT,
    modelo_llm TEXT,
    ms_fim_fala_transcricao INTEGER CHECK (ms_fim_fala_transcricao IS NULL OR ms_fim_fala_transcricao >= 0),
    ms_primeiro_token INTEGER CHECK (ms_primeiro_token IS NULL OR ms_primeiro_token >= 0),
    ms_primeira_frase INTEGER CHECK (ms_primeira_frase IS NULL OR ms_primeira_frase >= 0),
    ms_primeiro_audio INTEGER CHECK (ms_primeiro_audio IS NULL OR ms_primeiro_audio >= 0),
    ms_total INTEGER CHECK (ms_total IS NULL OR ms_total >= 0),
    barge_in INTEGER NOT NULL CHECK (barge_in IN (0, 1))
);

CREATE TABLE uso_recursos (
    id TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL CHECK (ts_ms >= 0),
    componente TEXT NOT NULL,
    vram_mb REAL CHECK (vram_mb IS NULL OR vram_mb >= 0),
    ram_mb REAL CHECK (ram_mb IS NULL OR ram_mb >= 0)
);

CREATE INDEX idx_latencia_turnos_ts ON latencia_turnos(ts_ms);
CREATE INDEX idx_uso_recursos_ts ON uso_recursos(ts_ms);
