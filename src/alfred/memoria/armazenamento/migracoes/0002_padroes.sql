CREATE TABLE padroes (
    id TEXT PRIMARY KEY,
    categoria TEXT NOT NULL CHECK (categoria IN ('rotina', 'preferencia', 'conhecimento')),
    descricao TEXT NOT NULL,
    primeira_em INTEGER NOT NULL,
    ultima_em INTEGER NOT NULL,
    ocorrencias INTEGER NOT NULL DEFAULT 0 CHECK (ocorrencias >= 0),
    estado TEXT NOT NULL CHECK (estado IN ('observando', 'proposto', 'confirmado', 'recusado', 'ignorado')),
    destino TEXT CHECK (destino IS NULL OR destino IN ('fatores_estaveis', 'preferencias', 'conhecimento_abrangente')),
    proposto_em INTEGER,
    recusado_ate INTEGER,
    CHECK (ultima_em >= primeira_em)
);

CREATE TABLE padroes_ocorrencias (
    id_padrao TEXT NOT NULL REFERENCES padroes(id) ON DELETE CASCADE,
    ocorrido_em INTEGER NOT NULL,
    PRIMARY KEY (id_padrao, ocorrido_em)
);

CREATE INDEX idx_padroes_estado_categoria ON padroes(estado, categoria);
CREATE INDEX idx_padroes_ocorrencias_tempo ON padroes_ocorrencias(id_padrao, ocorrido_em);

UPDATE meta SET valor = '2' WHERE chave = 'schema_version';
