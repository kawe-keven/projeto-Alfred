CREATE TABLE meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

INSERT INTO meta(chave, valor) VALUES
    ('schema_version', '1'),
    ('modelo_embeddings', ''),
    ('dimensao_embeddings', ''),
    ('criado_em', '');

CREATE TABLE sessoes (
    id TEXT PRIMARY KEY,
    iniciada_em INTEGER NOT NULL,
    encerrada_em INTEGER,
    interface TEXT NOT NULL CHECK (interface IN ('cli', 'voz')),
    modelo_llm TEXT,
    CHECK (encerrada_em IS NULL OR encerrada_em >= iniciada_em)
);

CREATE TABLE resumos (
    id TEXT PRIMARY KEY,
    nivel TEXT NOT NULL CHECK (nivel IN ('dia', 'semana', 'mes', 'ano')),
    periodo_inicio INTEGER NOT NULL,
    periodo_fim INTEGER NOT NULL,
    texto TEXT NOT NULL,
    gerado_em INTEGER NOT NULL,
    modelo TEXT,
    versao_prompt TEXT,
    indexado INTEGER NOT NULL DEFAULT 0 CHECK (indexado IN (0, 1)),
    UNIQUE (nivel, periodo_inicio),
    CHECK (periodo_fim >= periodo_inicio)
);

CREATE TABLE eventos (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('conversa', 'nota', 'memoria', 'conhecimento')),
    papel TEXT CHECK (papel IS NULL OR papel IN ('usuario', 'alfred', 'sistema')),
    texto TEXT,
    criado_em INTEGER NOT NULL,
    sessao_id TEXT REFERENCES sessoes(id) ON DELETE SET NULL,
    origem TEXT NOT NULL CHECK (origem IN ('usuario', 'alfred', 'arquivo', 'importacao')),
    importancia INTEGER NOT NULL DEFAULT 50 CHECK (importancia BETWEEN 0 AND 100),
    fixada INTEGER NOT NULL DEFAULT 0 CHECK (fixada IN (0, 1)),
    estado TEXT NOT NULL DEFAULT 'ativa' CHECK (estado IN ('ativa', 'resumida', 'arquivada')),
    indexado INTEGER NOT NULL DEFAULT 0 CHECK (indexado IN (0, 1)),
    hash_texto TEXT NOT NULL,
    acessos INTEGER NOT NULL DEFAULT 0 CHECK (acessos >= 0),
    ultimo_acesso_em INTEGER,
    id_resumo_pai TEXT REFERENCES resumos(id) ON DELETE SET NULL,
    CHECK (estado = 'arquivada' OR texto IS NOT NULL)
);

CREATE TABLE resumo_itens (
    id_resumo TEXT NOT NULL REFERENCES resumos(id) ON DELETE CASCADE,
    tipo_origem TEXT NOT NULL CHECK (tipo_origem IN ('evento', 'resumo')),
    id_origem TEXT NOT NULL,
    PRIMARY KEY (id_resumo, tipo_origem, id_origem)
);

CREATE TABLE arquivo (
    id_evento TEXT PRIMARY KEY REFERENCES eventos(id) ON DELETE CASCADE,
    blob BLOB NOT NULL,
    algoritmo TEXT NOT NULL,
    tamanho_original INTEGER NOT NULL CHECK (tamanho_original >= 0),
    arquivado_em INTEGER NOT NULL
);

CREATE INDEX idx_eventos_tipo_criado ON eventos(tipo, criado_em);
CREATE INDEX idx_eventos_sessao_criado ON eventos(sessao_id, criado_em);
CREATE INDEX idx_eventos_estado ON eventos(estado);
CREATE INDEX idx_eventos_pendente_indexacao ON eventos(indexado) WHERE indexado = 0;
CREATE UNIQUE INDEX idx_eventos_conhecimento_hash
    ON eventos(tipo, hash_texto) WHERE tipo = 'conhecimento';
CREATE INDEX idx_resumos_periodo ON resumos(nivel, periodo_inicio, periodo_fim);

UPDATE meta SET valor = strftime('%s', 'now') || '000' WHERE chave = 'criado_em';
