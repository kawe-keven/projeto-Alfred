CREATE TABLE lembretes (
    id TEXT PRIMARY KEY,
    texto TEXT NOT NULL,
    vencimento_em INTEGER,
    criado_em INTEGER NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendente', 'disparado', 'cancelado', 'concluido')),
    recorrencia TEXT,
    origem TEXT
);

CREATE TABLE avisos (
    id TEXT PRIMARY KEY,
    categoria TEXT NOT NULL,
    criado_em INTEGER NOT NULL,
    nivel INTEGER NOT NULL CHECK (nivel BETWEEN 0 AND 4),
    urgencia REAL NOT NULL,
    utilidade REAL NOT NULL,
    confianca REAL NOT NULL,
    pontuacao REAL NOT NULL,
    contexto TEXT,
    resposta TEXT NOT NULL DEFAULT 'pendente'
        CHECK (resposta IN ('pendente', 'aceitou', 'ignorou', 'dispensou')),
    respondido_em INTEGER
);

CREATE TABLE categorias_aviso (
    categoria TEXT PRIMARY KEY,
    aceitos INTEGER NOT NULL DEFAULT 0 CHECK (aceitos >= 0),
    ignorados INTEGER NOT NULL DEFAULT 0 CHECK (ignorados >= 0),
    dispensados INTEGER NOT NULL DEFAULT 0 CHECK (dispensados >= 0),
    peso REAL NOT NULL DEFAULT 1.0,
    silenciada_ate INTEGER
);

CREATE INDEX idx_lembretes_estado_vencimento ON lembretes(estado, vencimento_em);
CREATE INDEX idx_avisos_resposta_criado ON avisos(resposta, criado_em);

UPDATE meta SET valor = '3' WHERE chave = 'schema_version';
