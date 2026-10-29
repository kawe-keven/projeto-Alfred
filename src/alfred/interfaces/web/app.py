"""Painel web local para conversar e controlar as interfaces do Alfred."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from alfred.configuracao.configuracao import RAIZ_PROJETO, carregar_configuracao
from alfred.interfaces.cli.app import FIM, SessaoConversa, _criar_sessao
from alfred.nucleo.provedor_llm import ErroProvedorLLM

log = logging.getLogger(__name__)
UI = RAIZ_PROJETO / "ui"
PREFERENCIAS = RAIZ_PROJETO / "dados" / "perfil" / "voz_alfred.json"
FRASE_PREVIA = "Boa tarde. Esta é a voz configurada do Alfred."


class PainelAlfred:
    def __init__(self) -> None:
        self.sessao: SessaoConversa | None = None
        self.sessao_lock = threading.Lock()
        self.grafo_memoria_lock = threading.Lock()
        self.grafo_memoria_assinatura: tuple | None = None
        self.grafo_memoria_cache: dict | None = None
        self.grafo_repositorio_externo = None
        self.grafo_repositorio_caminho: Path | None = None
        self.voz: subprocess.Popen | None = None
        self.voz_lock = threading.Lock()
        self.voz_muda = False
        self.voz_controle = Path(tempfile.gettempdir()) / f"alfred-voz-controle-{os.getpid()}"
        self.voz_controle_contador = 0
        self.voz_estado = Path(tempfile.gettempdir()) / f"alfred-voz-estado-{os.getpid()}.txt"
        self.confirmacao: dict | None = None
        self.confirmacao_lock = threading.Lock()
        self.confirmacao_evento: threading.Event | None = None

    def _sessao(self) -> SessaoConversa:
        if self.sessao is None:
            configuracao = carregar_configuracao()
            self.sessao = _criar_sessao(
                configuracao, confirmar=self.solicitar_confirmacao
            )
        return self.sessao

    def solicitar_confirmacao(self, pergunta: str) -> str:
        evento = threading.Event()
        with self.confirmacao_lock:
            self.confirmacao = {"question": pergunta, "answer": None}
            self.confirmacao_evento = evento
        if not evento.wait(timeout=120):
            with self.confirmacao_lock:
                self.confirmacao = None
                self.confirmacao_evento = None
            return "não"
        with self.confirmacao_lock:
            resposta = (self.confirmacao or {}).get("answer") or "não"
            self.confirmacao = None
            self.confirmacao_evento = None
        return resposta

    def responder_confirmacao(self, resposta: str) -> bool:
        with self.confirmacao_lock:
            if not self.confirmacao or not self.confirmacao_evento:
                return False
            self.confirmacao["answer"] = "sim" if resposta == "sim" else "não"
            self.confirmacao_evento.set()
            return True

    @staticmethod
    def _preferencias() -> dict:
        if PREFERENCIAS.is_file():
            try:
                resultado = json.loads(PREFERENCIAS.read_text(encoding="utf-8"))
                if isinstance(resultado, dict):
                    return resultado
            except (OSError, json.JSONDecodeError):
                pass
        config = carregar_configuracao()
        return {
            "model": config.voicestudio_motor,
            "voice_id": config.voicestudio_voz,
            "speed": config.voicestudio_velocidade,
            "seed": config.voicestudio_estabilidade_seed,
            "style": config.voicestudio_estilo,
        }

    @staticmethod
    def _url_local() -> str:
        url = carregar_configuracao().voicestudio_url.rstrip("/")
        partes = urlsplit(url)
        if partes.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("O VoiceStudio precisa estar em um endereço local.")
        return url

    def catalogo(self) -> dict:
        base = self._url_local()
        def buscar(rota: str, raiz: bool = False):
            endereco = base[:-3] if raiz and base.endswith("/v1") else base
            with urlopen(Request(f"{endereco}/{rota}", headers={"Accept": "application/json"}), timeout=4) as r:
                return json.loads(r.read(1_000_000))
        modelos_doc = buscar("models")
        vozes_doc = buscar("audio/voices")
        try:
            perfis_doc = buscar("profiles", raiz=True)
        except Exception:
            perfis_doc = []
        perfis = {str(p.get("id")): p for p in perfis_doc if isinstance(p, dict) and p.get("id")} if isinstance(perfis_doc, list) else {}
        engines = {e.get("id"): e for e in vozes_doc.get("engines", []) if isinstance(e, dict)}
        modelos = []
        for item in modelos_doc.get("data", []):
            info = item.get("voicestudio", {}) if isinstance(item, dict) else {}
            ident = str(item.get("id", "")).strip()
            if info.get("kind") == "tts" and not info.get("alias_for_active_engine") and engines.get(ident, {}).get("available", False):
                modelos.append({"id": ident, "label": ident})
        vozes = []
        for item in vozes_doc.get("voices", []):
            if not isinstance(item, dict) or item.get("type") != "profile" or not item.get("voice_id"):
                continue
            perfil = perfis.get(str(item["voice_id"]), {})
            vozes.append({"id": str(item["voice_id"]), "label": str(item.get("name", item["voice_id"])), "language": str(item.get("language", "")), "kind": str(perfil.get("kind", "perfil"))})
        vozes.sort(key=lambda v: (v["label"].casefold() != "alfred", v["label"].casefold()))
        return {"models": modelos, "voices": vozes, "preferences": self._preferencias(), "connected": True}

    def iniciar_voz(self, modo: str) -> dict:
        if modo not in {"apertar", "conversa", "palavra"}:
            raise ValueError("Modo de voz inválido.")
        with self.voz_lock:
            if self.voz and self.voz.poll() is None:
                return {"running": True, "message": "A sessão de voz já está ativa."}
            env = os.environ.copy()
            env["ALFRED_VOZ_MODO"] = modo
            env["ALFRED_VOZ_CONTROLE_ARQUIVO"] = str(self.voz_controle)
            env["ALFRED_VOZ_ESTADO_ARQUIVO"] = str(self.voz_estado)
            self.voz_muda = False
            self.voz_estado.unlink(missing_ok=True)
            self.voz = subprocess.Popen(
                [sys.executable, "-m", "alfred.interfaces.ciclo_de_voz", "--modo", modo],
                cwd=RAIZ_PROJETO, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {"running": True, "message": "Sessão de voz iniciada."}

    def alternar_mudo(self) -> dict:
        with self.voz_lock:
            if not self.voz or self.voz.poll() is not None:
                raise ValueError("Inicie uma sessão de voz antes de silenciar o microfone.")
            self.voz_muda = not self.voz_muda
            self.voz_controle_contador += 1
            comando = self.voz_controle.with_name(
                f"{self.voz_controle.name}-{self.voz_controle_contador}.cmd"
            )
            comando.write_text("m", encoding="utf-8")
            return {"muted": self.voz_muda, "message": "Microfone silenciado." if self.voz_muda else "Escuta ativada."}

    def parar_voz(self) -> dict:
        with self.voz_lock:
            if not self.voz or self.voz.poll() is not None:
                return {"running": False, "message": "A sessão de voz está parada."}
            self.voz.terminate()
            self.voz_muda = False
            self.voz_estado.unlink(missing_ok=True)
            for comando in self.voz_controle.parent.glob(f"{self.voz_controle.name}-*.cmd"):
                comando.unlink(missing_ok=True)
            return {"running": False, "message": "Sessão de voz encerrada."}


PAINEL = PainelAlfred()
_LUGARES_MEMORIA = None
_LUGARES_PERSISTENTE = None

def _repositorio_lugares():
    global _LUGARES_MEMORIA, _LUGARES_PERSISTENTE
    with PAINEL.sessao_lock:
        sessao = PAINEL.sessao
        rag = getattr(sessao, "rag", None) if sessao else None
        if rag is not None:
            from alfred.interfaces.web.lugares import LugaresSQLCipher
            return LugaresSQLCipher(rag.caminho_db, rag._chave_mestra), getattr(rag, "auditoria", None)
    try:
        from alfred.configuracao.configuracao import carregar_configuracao
        from alfred.memoria.armazenamento.rag import resolver_raiz_armazenamento
        from alfred.seguranca.chaves.provedores import resolver_provedor_de_chave
        from alfred.seguranca.auditoria.registro import RegistroDeAuditoria

        config = carregar_configuracao()
        chave = resolver_provedor_de_chave(interativo_disponivel=False).obter_chave_mestra()
    except Exception:
        # Sem chave/armazenamento disponível, a modalidade em memória é explícita na API.
        chave = None
    if chave is not None:
        from alfred.interfaces.web.lugares import LugaresSQLCipher
        raiz = resolver_raiz_armazenamento(config)
        raiz.mkdir(parents=True, exist_ok=True)
        caminho = raiz / "alfred.db"
        if _LUGARES_PERSISTENTE is None or _LUGARES_PERSISTENTE.caminho != caminho:
            _LUGARES_PERSISTENTE = LugaresSQLCipher(caminho, chave)
        auditoria = RegistroDeAuditoria(raiz / "auditoria.db", raiz / "auditoria.ancora", chave)
        return _LUGARES_PERSISTENTE, auditoria
    if _LUGARES_MEMORIA is None:
        from alfred.interfaces.web.lugares import LugaresMemoria
        _LUGARES_MEMORIA = LugaresMemoria()
    return _LUGARES_MEMORIA, None


class Requisicao(BaseHTTPRequestHandler):
    server_version = "AlfredPanel/1.0"

    def log_message(self, formato: str, *args) -> None:
        if urlsplit(self.path).path.startswith("/api/mapa/"):
            return
        log.info("Painel local: " + formato, *args)

    def responder_json(self, dados, status: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def ler_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length", "0"))
        if tamanho > 200_000:
            raise ValueError("A requisição excede o limite permitido.")
        dados = json.loads(self.rfile.read(tamanho))
        if not isinstance(dados, dict):
            raise ValueError("A requisição é inválida.")
        return dados

    def origem_local(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").casefold()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        origem = self.headers.get("Origin")
        return not origem or origem in {
            "http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"
        }

    def do_GET(self) -> None:
        if not self.origem_local():
            self.send_error(403)
            return
        rota = urlsplit(self.path).path
        if rota == "/api/mapa/config":
            from alfred.interfaces.web.mapa import configuracao

            try:
                self.responder_json(configuracao())
            except Exception as erro:
                from alfred.interfaces.web.mapa import ErroMapa

                if isinstance(erro, ErroMapa):
                    self.responder_json({"available": False, "error": str(erro)}, erro.status)
                else:
                    self.responder_json({"available": False, "error": "Não foi possível carregar a configuração do mapa."}, 500)
            return
        if rota == "/api/mapa/estilo":
            from alfred.interfaces.web.mapa import ErroMapa, estilo

            try:
                self.responder_json(estilo())
            except ErroMapa as erro:
                self.responder_json({"available": False, "error": str(erro)}, erro.status)
            except Exception:
                self.responder_json({"available": False, "error": "Não foi possível carregar o estilo do mapa."}, 500)
            return
        if rota == "/api/mapa/lugares":
            repo, _ = _repositorio_lugares()
            self.responder_json({"lugares": repo.listar(), "sessionOnly": not repo.persistent})
            return
        if rota.startswith("/api/mapa/tiles/"):
            from alfred.interfaces.web.mapa import ARQUIVO_BASE, ErroMapa, ler_tile, resposta_http_tile

            partes = rota.removeprefix("/api/mapa/tiles/").split("/")
            if len(partes) != 3 or not partes[2].endswith(".mvt"):
                self.responder_json({"error": "Coordenadas do tile inválidas."}, 400)
                return
            try:
                tile = ler_tile(ARQUIVO_BASE, partes[0], partes[1], partes[2][:-4])
                status, cabecalhos, corpo = resposta_http_tile(tile)
                self.send_response(status)
                for nome, valor in cabecalhos.items():
                    self.send_header(nome, valor)
                self.end_headers()
                if corpo:
                    self.wfile.write(corpo)
            except ErroMapa as erro:
                self.responder_json({"error": str(erro)}, erro.status)
            except Exception:
                self.responder_json({"error": "Não foi possível ler o tile do mapa."}, 500)
            return
        if rota == "/api/status":
            try:
                config = carregar_configuracao()
                ollama = "desconectado"
                caminho_status = (
                    "/models" if config.provedor_llm == "colibri" else "/api/tags"
                )
                try:
                    with urlopen(f"{config.url_llm}{caminho_status}", timeout=1.2):
                        ollama = "conectado"
                except Exception:
                    pass
                with PAINEL.voz_lock:
                    voz = bool(PAINEL.voz and PAINEL.voz.poll() is None)
                with PAINEL.confirmacao_lock:
                    confirmacao = PAINEL.confirmacao
                self.responder_json({"ollama": ollama, "voiceRunning": voz, "voiceMuted": PAINEL.voz_muda, "mode": config.voz_modo, "model": config.modelo, "confirmation": confirmacao})
            except Exception as erro:
                self.responder_json({"error": str(erro)}, 500)
            return
        if rota == "/api/memory/graph":
            atualizar_forcado = parse_qs(urlsplit(self.path).query).get("refresh") == ["1"]
            with PAINEL.sessao_lock:
                sessao = PAINEL.sessao
            rag = getattr(sessao, "rag", None) if sessao is not None else None
            repositorio = getattr(rag, "repositorio", None) if rag is not None else None
            aviso_memoria = None
            if sessao is not None and rag is None:
                aviso_memoria = (
                    "A sessão está sem acesso à memória persistente. Configure a chave "
                    "SQLCipher no cofre do sistema. No terminal do projeto, execute "
                    "python -m alfred.interfaces.cli.armazenamento --diretorio "
                    "dados/bancos_alfred restaurar-chave; a chave será validada no "
                    "banco existente antes de ser guardada."
                )
            elif sessao is None:
                try:
                    from alfred.seguranca.chaves.provedores import resolver_provedor_de_chave

                    resolver_provedor_de_chave(interativo_disponivel=False).obter_chave_mestra()
                except Exception:
                    aviso_memoria = (
                        "O dashboard não encontrou a chave-mestra SQLCipher; a memória "
                        "persistente está bloqueada. Execute no terminal do projeto "
                        "python -m alfred.interfaces.cli.armazenamento --diretorio "
                        "dados/bancos_alfred restaurar-chave para validar a chave original "
                        "e guardá-la no cofre do sistema."
                    )
            if repositorio is None:
                # O CLI e a interface web podem ser processos distintos. Abra o
                # índice persistente diretamente para refletir gravações externas.
                try:
                    from alfred.memoria.armazenamento.rag import resolver_raiz_armazenamento
                    from alfred.memoria.armazenamento.vetorial_chroma import RepositorioVetorialChroma

                    config = carregar_configuracao()
                    caminho = resolver_raiz_armazenamento(config) / "chroma"
                    if caminho.is_dir():
                        with PAINEL.grafo_memoria_lock:
                            if PAINEL.grafo_repositorio_caminho != caminho:
                                if PAINEL.grafo_repositorio_externo is not None:
                                    PAINEL.grafo_repositorio_externo.close()
                                import chromadb
                                from chromadb.config import Settings

                                cliente = chromadb.PersistentClient(
                                    path=str(caminho), settings=Settings(anonymized_telemetry=False)
                                )
                                colecao = cliente.get_collection("memorias")
                                meta = colecao.metadata or {}
                                modelo = str(meta.get("modelo_embeddings", config.modelo_embeddings))
                                dimensao = int(meta.get("dimensao_embeddings", 1024))
                                PAINEL.grafo_repositorio_externo = RepositorioVetorialChroma(
                                    caminho, modelo_embeddings=modelo, dimensao=dimensao
                                )
                                PAINEL.grafo_repositorio_caminho = caminho
                            repositorio = PAINEL.grafo_repositorio_externo
                except Exception:
                    log.exception("Não foi possível abrir o índice vetorial persistente do ALFRED.")
            snapshot = getattr(repositorio, "snapshot_visualizacao", None)
            if not callable(snapshot):
                resposta = {
                    "available": False,
                    "reason": "O índice vetorial local ainda não está disponível.",
                }
                if aviso_memoria:
                    resposta["warning"] = aviso_memoria
                self.responder_json(resposta)
                return
            try:
                with PAINEL.grafo_memoria_lock:
                    assinatura = (
                        id(repositorio),
                        tuple(repositorio.contar(nome) for nome in ("memorias", "conversas", "conhecimento", "resumos")),
                    )
                    if atualizar_forcado or assinatura != PAINEL.grafo_memoria_assinatura:
                        PAINEL.grafo_memoria_cache = snapshot()
                        PAINEL.grafo_memoria_assinatura = assinatura
                    dados_grafo = PAINEL.grafo_memoria_cache
                if aviso_memoria:
                    dados_grafo = dict(dados_grafo)
                    dados_grafo["warning"] = aviso_memoria
                self.responder_json(dados_grafo)
            except Exception:
                log.exception("Falha ao atualizar o gráfico local da memória vetorial.")
                # O Chroma pode manter um cliente persistente com o índice HNSW
                # desatualizado quando outro processo grava no mesmo diretório.
                # Descartar essa conexão permite que a próxima atualização abra
                # o índice novamente e reflita os vetores gravados externamente.
                with PAINEL.grafo_memoria_lock:
                    if repositorio is PAINEL.grafo_repositorio_externo:
                        try:
                            repositorio.close()
                        except Exception:
                            log.exception("Não foi possível fechar a conexão vetorial desatualizada.")
                        PAINEL.grafo_repositorio_externo = None
                        PAINEL.grafo_repositorio_caminho = None
                        PAINEL.grafo_memoria_assinatura = None
                        PAINEL.grafo_memoria_cache = None
                self.responder_json({"available": False, "reason": "Não foi possível atualizar os dados da memória vetorial."}, 503)
            return
        if rota == "/api/voice/state":
            with PAINEL.voz_lock:
                rodando = bool(PAINEL.voz and PAINEL.voz.poll() is None)
                try:
                    estado = PAINEL.voz_estado.read_text(encoding="utf-8").strip() if rodando else "parado"
                except OSError:
                    estado = "iniciando" if rodando else "parado"
                self.responder_json({"running": rodando, "muted": PAINEL.voz_muda, "state": estado})
            return
        if rota == "/api/voice/catalog":
            try:
                self.responder_json(PAINEL.catalogo())
            except Exception as erro:
                self.responder_json({"connected": False, "error": str(erro), "preferences": PAINEL._preferencias(), "models": [], "voices": []}, 200)
            return
        if rota.startswith("/ui/") or rota == "/":
            nome = "index.html" if rota == "/" else rota.removeprefix("/ui/")
            caminho = (UI / nome).resolve()
            if UI.resolve() not in caminho.parents and caminho != UI.resolve():
                self.send_error(404); return
            try:
                corpo = caminho.read_bytes()
            except OSError:
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(caminho.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers(); self.wfile.write(corpo)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.origem_local():
            self.send_error(403)
            return
        rota = urlsplit(self.path).path
        if rota.startswith("/api/mapa/") and rota != "/api/mapa/lugares":
            self._responder_mapa_405()
            return
        try:
            dados = self.ler_json()
            if rota == "/api/mapa/lugares":
                from alfred.interfaces.web.lugares import validar_nome, validar_categoria, validar_coordenadas
                repo, auditoria = _repositorio_lugares()
                nome = validar_nome(dados.get("nome")); categoria = validar_categoria(dados.get("categoria")); lat, lon = validar_coordenadas(dados.get("lat"), dados.get("lon"))
                if PAINEL.solicitar_confirmacao("Salvar este lugar no mapa?") != "sim":
                    self.responder_json({"error":"Ação cancelada."}, 409); return
                item = repo.criar(nome,categoria,lat,lon)
                if auditoria: auditoria.registrar("mapa","criar_lugar","ok","usuario",quantidade=1)
                self.responder_json(item,201); return
            if rota == "/api/chat":
                texto = str(dados.get("text", "")).strip()
                if not texto or len(texto) > 4000:
                    raise ValueError("Digite uma mensagem de até 4.000 caracteres.")
                with PAINEL.sessao_lock:
                    sessao = PAINEL._sessao()
                    if texto.startswith("/"):
                        resultado = sessao.executar_comando(texto)
                        resposta = "Até mais." if resultado is FIM else str(resultado or "Comando desconhecido. Digite /ajuda.")
                        # Comandos com credenciais não entram no RAG nem no modelo.
                        # Mantemos somente uma versão sanitizada na janela da conversa
                        # para que perguntas como "qual motivo?" tenham contexto.
                        if texto not in {"/limpar", "/sair"}:
                            from alfred.nucleo.provedor_llm import Mensagem
                            seguro = (
                                "/configuraremail [credenciais ocultas]"
                                if texto.casefold().startswith(("/configuraremail", "/configurar_email"))
                                else texto
                            )
                            sessao.historico.extend((Mensagem("user", seguro), Mensagem("assistant", resposta)))
                            limite = sessao.configuracao.janela_mensagens
                            if len(sessao.historico) > limite:
                                del sessao.historico[:-limite]
                    else:
                        resposta = "".join(sessao.responder(texto))
                self.responder_json({"reply": resposta or "Não recebi uma resposta nesta rodada."})
                return
            if rota == "/api/voice/start":
                self.responder_json(PAINEL.iniciar_voz(str(dados.get("mode", "conversa"))))
                return
            if rota == "/api/voice/stop":
                self.responder_json(PAINEL.parar_voz())
                return
            if rota == "/api/voice/mute":
                self.responder_json(PAINEL.alternar_mudo())
                return
            if rota == "/api/voice/settings":
                preferencias = {"model": str(dados.get("model", "")).strip(), "voice_id": str(dados.get("voice_id", "")).strip(), "speed": float(dados.get("speed", 1)), "seed": int(dados.get("seed", 42)), "style": str(dados.get("style", "")).strip()}
                if not preferencias["model"] or not preferencias["voice_id"] or not 0.25 <= preferencias["speed"] <= 4 or preferencias["seed"] < 0 or len(preferencias["style"]) > 500:
                    raise ValueError("Confira o motor, perfil, velocidade, seed e estilo da voz.")
                if preferencias["model"] == "omnivoice":
                    permitidos = {"american accent", "australian accent", "british accent", "canadian accent", "child", "chinese accent", "elderly", "female", "high pitch", "indian accent", "japanese accent", "korean accent", "low pitch", "male", "middle-aged", "moderate pitch", "portuguese accent", "russian accent", "teenager", "very high pitch", "very low pitch", "whisper", "young adult"}
                    marcadores = {parte.strip().casefold() for parte in preferencias["style"].split(",") if parte.strip()}
                    if marcadores - permitidos:
                        raise ValueError("OmniVoice aceita marcadores de voz em inglês, separados por vírgulas.")
                catalogo = PAINEL.catalogo()
                if catalogo["connected"] and (preferencias["model"] not in {x["id"] for x in catalogo["models"]} or preferencias["voice_id"] not in {x["id"] for x in catalogo["voices"]}):
                    raise ValueError("Escolha um motor e um perfil fixos disponíveis no VoiceStudio.")
                PREFERENCIAS.parent.mkdir(parents=True, exist_ok=True)
                temporario = PREFERENCIAS.with_suffix(".tmp")
                temporario.write_text(json.dumps(preferencias, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temporario.replace(PREFERENCIAS)
                self.responder_json({"saved": True, "message": "Preferências de voz salvas."})
                return
            if rota == "/api/voice/preview":
                pref = PAINEL._preferencias()
                pref.update({k: dados[k] for k in ("model", "voice_id", "speed", "seed", "style") if k in dados})
                payload = json.dumps({"model": pref["model"], "voice": pref["voice_id"], "input": FRASE_PREVIA, "response_format": "pcm", "language": "pt", "speed": float(pref["speed"]), "seed": int(pref["seed"]), **({"instruct": pref["style"]} if pref.get("style") else {})}, ensure_ascii=False).encode()
                req = Request(f"{PAINEL._url_local()}/audio/speech", data=payload, headers={"Content-Type": "application/json", "Accept": "audio/pcm"}, method="POST")
                with urlopen(req, timeout=60) as resp:
                    audio = resp.read(20_000_000)
                if not audio or len(audio) % 2:
                    raise ValueError("A prévia de áudio retornou dados inválidos.")
                import io
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(audio)
                corpo = buffer.getvalue()
                self.send_response(200); self.send_header("Content-Type", "audio/wav"); self.send_header("Content-Length", str(len(corpo))); self.end_headers(); self.wfile.write(corpo)
                return
            if rota == "/api/confirm":
                if not PAINEL.responder_confirmacao(str(dados.get("answer", "não"))):
                    self.responder_json({"error": "Não há confirmação pendente."}, 409)
                else:
                    self.responder_json({"ok": True})
                return
            self.send_error(404)
        except (ValueError, TypeError, json.JSONDecodeError, URLError, OSError, ErroProvedorLLM) as erro:
            self.responder_json({"error": str(erro) or "Não foi possível concluir esta ação."}, 400)
        except Exception as erro:
            log.exception("Erro no painel web")
            self.responder_json({"error": "O Alfred não conseguiu concluir esta ação."}, 500)

    def _responder_mapa_405(self) -> None:
        if not self.origem_local():
            self.send_error(403)
            return
        self.send_response(405)
        rota = urlsplit(self.path).path
        allow = "GET, POST" if rota == "/api/mapa/lugares" else "GET, PATCH, DELETE" if rota.startswith("/api/mapa/lugares/") else "GET"
        self.send_header("Allow", allow)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _metodo_mapa_nao_permitido(self) -> None:
        if not urlsplit(self.path).path.startswith("/api/mapa/"):
            self.send_error(501)
            return
        self._responder_mapa_405()

    def do_HEAD(self) -> None:
        self._metodo_mapa_nao_permitido()

    def do_PUT(self) -> None:
        self._metodo_mapa_nao_permitido()

    def do_DELETE(self) -> None:
        if urlsplit(self.path).path.startswith("/api/mapa/lugares/"):
            self._alterar_lugar("DELETE")
        else: self._metodo_mapa_nao_permitido()

    def do_PATCH(self) -> None:
        if urlsplit(self.path).path.startswith("/api/mapa/lugares/"):
            self._alterar_lugar("PATCH")
        else: self._metodo_mapa_nao_permitido()

    def _alterar_lugar(self, metodo: str) -> None:
        if not self.origem_local(): self.send_error(403); return
        rota=urlsplit(self.path).path
        ident=rota.removeprefix("/api/mapa/lugares/")
        if not ident or "/" in ident: self.send_error(404); return
        try:
            dados=self.ler_json() if metodo=="PATCH" else {}
            from alfred.interfaces.web.lugares import validar_nome, validar_coordenadas
            repo,auditoria=_repositorio_lugares()
            campos={}
            if metodo=="PATCH":
                if "nome" in dados: campos["nome"]=validar_nome(dados["nome"])
                if "lat" in dados or "lon" in dados:
                    lat,lon=validar_coordenadas(dados.get("lat"),dados.get("lon")); campos.update(lat=lat,lon=lon)
                if not campos: raise ValueError("Nenhuma alteração válida foi informada.")
            acao="remover_lugar" if metodo=="DELETE" else "alterar_lugar"
            if PAINEL.solicitar_confirmacao("Remover este lugar?" if metodo=="DELETE" else "Confirmar alteração do lugar?") != "sim":
                self.responder_json({"error":"Ação cancelada."},409); return
            resultado=repo.remover(ident) if metodo=="DELETE" else repo.atualizar(ident,campos)
            if not resultado: self.responder_json({"error":"Lugar não encontrado."},404); return
            if auditoria: auditoria.registrar("mapa",acao,"ok","usuario",quantidade=1)
            self.responder_json({"ok":True} if metodo=="DELETE" else resultado)
        except (ValueError,TypeError) as erro: self.responder_json({"error":str(erro)},400)
        except Exception: self.responder_json({"error":"Não foi possível alterar o lugar."},500)

    def do_OPTIONS(self) -> None:
        self._metodo_mapa_nao_permitido()

    def do_TRACE(self) -> None:
        self._metodo_mapa_nao_permitido()

    def do_CONNECT(self) -> None:
        self._metodo_mapa_nao_permitido()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    servidor = ThreadingHTTPServer(("127.0.0.1", 8765), Requisicao)
    servidor.daemon_threads = True
    print("Alfred FUI disponível em http://127.0.0.1:8765")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PAINEL.parar_voz()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
