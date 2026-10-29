"""CRUD de lugares do mapa. Conteúdo fica cifrado em SQLCipher ou em memória."""
from __future__ import annotations

import math
import re
import threading
import unicodedata
from time import time_ns

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.migracao import aplicar_migracoes
from alfred.seguranca.chaves.derivacao import derivar_subchave

CATEGORIAS = {"CAS", "FAC", "TRB", "LOC"}
_id = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f-]{36})$")

def validar_nome(valor):
    if not isinstance(valor, str): raise ValueError("Informe um nome válido (até 80 caracteres).")
    nome = " ".join(unicodedata.normalize("NFC", valor).split())
    if not nome or len(nome) > 80 or any(unicodedata.category(c).startswith("C") for c in nome):
        raise ValueError("Informe um nome válido (até 80 caracteres).")
    return nome

def validar_categoria(valor):
    if valor not in CATEGORIAS: raise ValueError("Categoria inválida.")
    return valor

def validar_coordenadas(lat, lon):
    if isinstance(lat, bool) or isinstance(lon, bool): raise ValueError("Coordenadas inválidas.")
    try: lat, lon = float(lat), float(lon)
    except (TypeError, ValueError): raise ValueError("Coordenadas inválidas.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -85.051129 <= lat <= 85.051129 or not -180 <= lon <= 180:
        raise ValueError("Coordenadas fora dos limites permitidos.")
    return lat, lon

class LugaresMemoria:
    persistent = False
    def __init__(self): self.items = {}; self.seqs = {c: 0 for c in CATEGORIAS}; self.lock = threading.RLock()
    def listar(self):
        with self.lock: return sorted(self.items.values(), key=lambda x:(x["categoria"],x["codigo"]))
    def criar(self,nome,categoria,lat,lon):
        with self.lock:
            self.seqs[categoria]+=1; codigo=f"{categoria}-{self.seqs[categoria]:03d}"; ident=__import__('uuid').uuid4().hex
            item={"id":ident,"codigo":codigo,"nome":nome,"categoria":categoria,"lat":lat,"lon":lon}; self.items[ident]=item; return item
    def atualizar(self,ident,campos):
        with self.lock:
            if ident not in self.items:return None
            self.items[ident].update(campos); return self.items[ident]
    def remover(self,ident):
        with self.lock:return self.items.pop(ident,None) is not None

class LugaresSQLCipher:
    persistent = True
    def __init__(self, caminho, chave):
        self.caminho=caminho; self.chave=derivar_subchave(chave,"alfred.db")
        aplicar_migracoes(caminho,self.chave)
    @staticmethod
    def _item(row): return {"id":row["id"],"codigo":row["codigo"],"nome":row["nome"],"categoria":row["categoria"],"lat":row["lat"],"lon":row["lon"]}
    def listar(self):
        with abrir_conexao(self.caminho,self.chave,escritor=False) as db:return [self._item(x) for x in db.execute("SELECT * FROM lugares ORDER BY categoria,codigo")]
    def criar(self,nome,categoria,lat,lon):
        import uuid
        ident=uuid.uuid4().hex; agora=time_ns()//1_000_000
        with abrir_conexao(self.caminho,self.chave) as db:
            db.execute("INSERT INTO codigos_lugares(categoria,ultimo_numero) VALUES(?,1) ON CONFLICT(categoria) DO UPDATE SET ultimo_numero=ultimo_numero+1",(categoria,))
            n=db.execute("SELECT ultimo_numero FROM codigos_lugares WHERE categoria=?",(categoria,)).fetchone()[0]; codigo=f"{categoria}-{n:03d}"
            db.execute("INSERT INTO lugares VALUES(?,?,?,?,?,?,?,?)",(ident,nome,categoria,lat,lon,codigo,agora,agora)); db.commit()
        return {"id":ident,"codigo":codigo,"nome":nome,"categoria":categoria,"lat":lat,"lon":lon}
    def atualizar(self,ident,campos):
        if not _id.fullmatch(ident):return None
        if not campos:return None
        set_sql=",".join(f"{k}=?" for k in campos); vals=list(campos.values())
        with abrir_conexao(self.caminho,self.chave) as db:
            cur=db.execute(f"UPDATE lugares SET {set_sql}, atualizado_em=? WHERE id=?",(*vals,time_ns()//1_000_000,ident)); db.commit()
            row=db.execute("SELECT * FROM lugares WHERE id=?",(ident,)).fetchone() if cur.rowcount else None
        return self._item(row) if row else None
    def remover(self,ident):
        if not _id.fullmatch(ident):return False
        with abrir_conexao(self.caminho,self.chave) as db:
            cur=db.execute("DELETE FROM lugares WHERE id=?",(ident,)); db.commit(); return cur.rowcount==1
