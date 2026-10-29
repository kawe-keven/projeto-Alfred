CREATE TABLE recuperacao_contexto (
    id TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL CHECK (ts_ms >= 0),
    interface TEXT NOT NULL CHECK (interface IN ('cli', 'voz')),
    latencia_ms INTEGER NOT NULL CHECK (latencia_ms >= 0),
    itens INTEGER NOT NULL CHECK (itens >= 0),
    tokens_estimados INTEGER NOT NULL CHECK (tokens_estimados >= 0)
);

CREATE INDEX idx_recuperacao_contexto_ts ON recuperacao_contexto(ts_ms);
