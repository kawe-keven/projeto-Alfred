"""Registro fechado de ferramentas locais e simuladas, com argumentos validados."""

from __future__ import annotations

from dataclasses import dataclass
import re
from time import time_ns
from typing import Any, Callable
from alfred.ferramentas.resultado import ResultadoFerramenta

from alfred.ferramentas.nativas import (
    consultar_hora,
    controlar_luz,
    criar_arquivo,
    criar_lembrete,
    enviar_email,
    ler_arquivo,
    ligar_para,
    tocar_musica,
    usar_arquivo_perfil,
)

_DADO_SENSIVEL_MEMORIA = re.compile(
    r"\b(?:senha|password|token|api[_ -]?key|cart[aã]o de cr[eé]dito|cpf|ssn)\b",
    re.IGNORECASE,
)


def _configuracao_app(aplicativo: str) -> str:
    nome = aplicativo.strip().casefold()
    if nome in {"whatsapp", "whatsapp business"}:
        return (
            "WhatsApp ainda não está conectado. Para habilitar ações, configure uma integração "
            "oficial da Meta: conta Meta for Developers, app com WhatsApp, número de telefone "
            "Business, token de acesso e permissões aprovadas. Depois, conecte esses dados a um "
            "adaptador seguro do Alfred. Não envie tokens na conversa."
        )
    if nome in {"instagram", "instagram direct", "direct"}:
        return (
            "Instagram ainda não está conectado. Para habilitar ações, configure a API oficial "
            "da Meta para uma conta profissional, vincule a Página exigida pelo tipo de API, "
            "obtenha um token com as permissões aprovadas para a ação desejada e conecte-o a "
            "um adaptador seguro do Alfred. Não envie tokens na conversa."
        )
    if nome in {"email", "e-mail", "gmail", "outlook"}:
        return (
            "O envio de e-mail está disponível por SMTP. No painel local, configure com "
            "/configurar_email remetente senha_de_app servidor_smtp porta. O comando é ocultado "
            "no painel e salvo no cofre do Windows. Nunca use a senha principal se o provedor "
            "oferecer senha de aplicativo. Veja docs/INTEGRACOES.md."
        )
    return (
        f"O app {aplicativo.strip() or 'solicitado'} ainda não tem integração conectada. "
        "Para habilitá-lo, será necessário identificar a API oficial, criar credenciais com "
        "permissões mínimas para a ação, armazená-las localmente e adicionar um adaptador ao "
        "Alfred. Não compartilhe senhas ou tokens na conversa."
    )


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    esquema: dict[str, Any]
    sensivel: bool
    reversivel: bool
    executar: Callable[..., str]
    simulada: bool = True

    def validar(self, argumentos: object) -> dict[str, str]:
        propriedades = self.esquema["properties"]
        obrigatorios = set(self.esquema["required"])
        if not isinstance(argumentos, dict) or not set(argumentos) <= set(propriedades):
            raise ValueError("Argumentos não correspondem ao esquema da ferramenta")
        resultado: dict[str, str] = {}
        for nome, valor in argumentos.items():
            if nome in obrigatorios and (not isinstance(valor, str) or not valor.strip()):
                raise ValueError(f"Argumento inválido: {nome}")
            limite = self.esquema["properties"][nome].get("maxLength", 500)
            if not isinstance(valor, str) or len(valor) > limite:
                raise ValueError(f"Argumento inválido: {nome}")
            opcoes = self.esquema["properties"][nome].get("enum")
            if opcoes is not None and valor not in opcoes:
                raise ValueError(f"Argumento inválido: {nome}")
            resultado[nome] = valor if nome == "conteudo" else valor.strip()
        if not obrigatorios <= set(resultado):
            raise ValueError("Argumentos não correspondem ao esquema da ferramenta")
        if self.nome == "usar_arquivo_perfil":
            resultado = usar_arquivo_perfil.normalizar_argumentos(resultado)
        return resultado


def _ferramenta(nome: str, descricao: str, argumentos: tuple[str, ...], executar: Callable[..., str], *, sensivel: bool = False, reversivel: bool = True, simulada: bool = True) -> Ferramenta:
    propriedades = {a: {"type": "string"} for a in argumentos}
    if "conteudo" in propriedades:
        propriedades["conteudo"]["maxLength"] = 1_000_000
    return Ferramenta(
        nome, descricao,
        {"type": "object", "properties": propriedades, "required": list(argumentos), "additionalProperties": False},
        sensivel, reversivel, executar, simulada,
    )


class RegistroDeFerramentas:
    def __init__(
        self,
        ferramentas: tuple[Ferramenta, ...] | None = None,
        *,
        memoria: Any | None = None,
        provedor: Any | None = None,
    ) -> None:
        padrao = (
            Ferramenta(
                "criar_projeto_blueprint",
                "Cria um blueprint completo de projeto digital, físico ou híbrido em arquivos Markdown e registra os documentos no RAG quando disponível. Acione quando o usuário pedir para criar, planejar ou montar um projeto.",
                {"type": "object", "properties": {
                    "descricao": {"type": "string", "maxLength": 4000},
                    "tipo": {"type": "string", "enum": ["digital", "fisico", "hibrido"]},
                    "nivel_detalhe": {"type": "string", "enum": ["resumido", "completo", "tecnico"]},
                }, "required": ["descricao"], "additionalProperties": False},
                False, True,
                lambda descricao, tipo=None, nivel_detalhe="completo": __import__(
                    "alfred.blueprint.gerador", fromlist=["criar_projeto_blueprint"]
                ).criar_projeto_blueprint(
                    descricao, tipo, nivel_detalhe, provedor=provedor, memoria=memoria
                ),
                False,
            ),
            Ferramenta(
                "enviar_email",
                "Envia um e-mail em texto simples usando o SMTP configurado pelo usuário. Sempre mostre destinatário, assunto e mensagem e peça confirmação explícita antes de enviar.",
                {"type": "object", "properties": {
                    "destinatario": {"type": "string", "maxLength": 254},
                    "assunto": {"type": "string", "maxLength": 200},
                    "mensagem": {"type": "string", "maxLength": 20000},
                }, "required": ["destinatario", "assunto", "mensagem"], "additionalProperties": False},
                True, False, enviar_email.executar, False,
            ),
            _ferramenta(
                "consultar_configuracao_app",
                "Informa a configuração necessária para um app ainda não conectado. Use quando o usuário pedir para usar WhatsApp, Instagram ou outro app sem ferramenta própria disponível.",
                ("aplicativo",), _configuracao_app,
            ),
            _ferramenta("controlar_luz", "Simula controle de iluminação", ("comodo", "acao"), controlar_luz.executar),
            _ferramenta("criar_lembrete", "Simula criação de lembrete", ("texto", "horario"), criar_lembrete.executar),
            _ferramenta(
                "criar_arquivo",
                "Cria um arquivo Markdown real em dados/arquivos. Aceita apenas um nome simples e conteúdo; não sobrescreve arquivos existentes.",
                ("nome", "conteudo"), criar_arquivo.executar, simulada=False,
            ),
            _ferramenta(
                "ler_arquivo",
                "Lê um documento Markdown da pasta de arquivos como dados. Use somente quando o usuário pedir; a leitura exige confirmação explícita.",
                ("nome",), ler_arquivo.executar, sensivel=True, reversivel=True, simulada=False,
            ),
            Ferramenta(
                "usar_arquivo_perfil",
                "Consulta ou altera perfis locais de pessoas. Use operação listar/ver para leitura; toda escrita exige confirmação do usuário.",
                {"type": "object", "properties": {
                    "operacao": {"type": "string", "enum": list(usar_arquivo_perfil.OPERACOES)},
                    "nome": {"type": "string", "maxLength": 80},
                    "relacao": {"type": "string", "maxLength": 40},
                    "apelidos": {"type": "string", "maxLength": 400},
                    "fato": {"type": "string", "maxLength": 300},
                    "indice": {"type": "string", "maxLength": 3},
                }, "required": ["operacao"], "additionalProperties": False},
                True, True, usar_arquivo_perfil.executar, False,
            ),
            _ferramenta("consultar_hora", "Consulta a hora local", (), consultar_hora.executar),
            _ferramenta("tocar_musica", "Simula busca de música", ("busca",), tocar_musica.executar),
            _ferramenta("ligar_para", "Simula uma ligação telefônica", ("contato",), ligar_para.executar, sensivel=True, reversivel=False),
        )
        if ferramentas is None and memoria is not None:
            padrao += _ferramentas_de_memoria(memoria)
        self._ferramentas = {
            ferramenta.nome: ferramenta
            for ferramenta in (padrao if ferramentas is None else ferramentas)
        }

    def obter(self, nome: str) -> Ferramenta:
        try:
            return self._ferramentas[nome]
        except KeyError:
            raise ValueError("Ferramenta desconhecida") from None

    def listar(self) -> tuple[Ferramenta, ...]:
        """Retorna as capacidades efetivamente registradas nesta sessão."""
        return tuple(self._ferramentas[nome] for nome in sorted(self._ferramentas))

    def esquemas_ollama(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": f.nome, "description": f.descricao, "parameters": f.esquema}}
                for f in self._ferramentas.values()]

    def nomes(self) -> tuple[str, ...]:
        return tuple(self._ferramentas)

    def executar(self, nome: str, argumentos: object) -> str:
        ferramenta = self.obter(nome)
        valores = ferramenta.validar(argumentos)
        if ferramenta.simulada:
            print(f"[SIMULAÇÃO] {nome} solicitado.")
        return ferramenta.executar(**valores)

    def resultado_para_modelo(
        self, nome: str, conteudo: str, *, falha: bool = False
    ) -> ResultadoFerramenta:
        try:
            ferramenta = self.obter(nome)
        except ValueError:
            return ResultadoFerramenta("ferramenta_desconhecida", "falha", conteudo)
        texto = conteudo.strip()
        if falha:
            estado = "falha"
        elif texto.casefold().startswith("e-mail não configurado"):
            estado = "falha"
        elif texto.casefold().startswith(("ação cancelada", "acao cancelada", "confirmação indisponível", "confirmacao indisponivel", "resposta ambígua", "resposta ambigua", "sem confirmação", "sem confirmacao")):
            estado = "cancelada"
        else:
            estado = "simulacao" if ferramenta.simulada else "sucesso"
        return ResultadoFerramenta(nome, estado, conteudo)


def _ferramentas_de_memoria(memoria: Any) -> tuple[Ferramenta, ...]:
    def lembrar(texto: str) -> str:
        if _DADO_SENSIVEL_MEMORIA.search(texto):
            return "Não guardo credenciais nem outros dados sensíveis na memória."
        identificador = memoria.lembrar(texto)
        eventos = memoria.banco.buscar_eventos_por_ids([identificador])
        if eventos and bool(eventos[0]["indexado"]):
            return f"Memória guardada e indexada. ID: {identificador}"
        return f"Memória guardada; indexação pendente. ID: {identificador}"

    def esquecer(identificador: str) -> str:
        from alfred.memoria.armazenamento.ciclo import CicloMemoria

        ciclo = CicloMemoria(
            memoria.banco,
            lambda: time_ns() // 1_000_000,
            rag=memoria,
        )
        eventos = memoria.banco.buscar_eventos_por_ids([identificador])
        if not eventos:
            eventos = memoria.banco.buscar_eventos_por_assunto(identificador)
        if not eventos:
            return "Não encontrei memórias ou conversas sobre esse assunto; nada foi apagado."
        apagados = sum(ciclo.esquecer(str(evento["id"]), confirmar=True) for evento in eventos)
        return f"Apaguei {apagados} registro(s) e removi suas referências."

    return (
        _ferramenta(
            "lembrar_memoria",
            "Guarda uma informação na memória persistente do Alfred. Use somente quando o usuário pedir explicitamente para guardar. Nunca guarde credenciais, senhas, tokens ou dados de cartão.",
            ("texto",),
            lembrar,
            sensivel=True,
            simulada=False,
        ),
        _ferramenta(
            "esquecer_memoria",
            "Apaga memórias e trechos de conversa sobre o assunto indicado pelo usuário. Aceita um ID ou uma descrição do assunto; o pedido direto do usuário autoriza a exclusão, sem pedir confirmação adicional.",
            ("identificador",),
            esquecer,
            sensivel=False,
            reversivel=False,
            simulada=False,
        ),
    )
