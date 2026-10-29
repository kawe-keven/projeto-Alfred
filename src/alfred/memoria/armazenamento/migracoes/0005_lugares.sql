CREATE TABLE lugares (id TEXT PRIMARY KEY, nome TEXT NOT NULL, categoria TEXT NOT NULL CHECK(categoria IN ('CAS','FAC','TRB','LOC')), lat REAL NOT NULL CHECK(lat BETWEEN -85.051129 AND 85.051129), lon REAL NOT NULL CHECK(lon BETWEEN -180 AND 180), codigo TEXT NOT NULL UNIQUE, criado_em INTEGER NOT NULL, atualizado_em INTEGER NOT NULL);
CREATE TABLE codigos_lugares (categoria TEXT PRIMARY KEY CHECK(categoria IN ('CAS','FAC','TRB','LOC')), ultimo_numero INTEGER NOT NULL CHECK(ultimo_numero > 0));
CREATE INDEX lugares_categoria ON lugares(categoria);
