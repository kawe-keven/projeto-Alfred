"""Estado e operações de uma sessão de conversa do Alfred."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
import json
import re
from time import time_ns

from alfred.configuracao.configuracao import Configuracao
from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.memoria.perfil.carregador import (
    Perfil,
    carregar_perfil,
)
from alfred.memoria.perfil.montador_prompt import montar_prompt_sistema
from alfred.memoria.perfil.pessoas import (
    RepositorioDePessoas,
    carregar_pessoas_mencionadas,
    montar_bloco_pessoas,
)
from alfred.nucleo.provedor_llm import ErroProvedorLLM, Mensagem, ProvedorLLM
from alfred.nucleo.agente.roteador_rapido import resposta_saudacao
from alfred.nucleo.politicas.confirmacao import (
    PoliticaDeConfirmacao,
    interpretar_confirmacao,
)
from alfred.nucleo.politicas.fontes import (
    consulta_pessoal_sem_correspondencia,
    detectar_contradicoes_explicitas,
    eh_pergunta_de_memoria_pessoal,
    eh_pergunta_de_historico,
    instrucao_resumo_historico,
    marcador_contradicao,
    marcador_memoria_vazia,
    resultado_busca_historico,
)
from alfred.nucleo.politicas.atualidade import marcador_de_atualidade


def _contexto_pessoas(texto: str, configuracao: Configuracao) -> str:
    repositorio = RepositorioDePessoas(
        configuracao.pasta_pessoas,
        limite_pessoas=configuracao.pessoas_limite_total,
        limite_palavras=configuracao.pessoa_limite_palavras,
    )
    selecionados = carregar_pessoas_mencionadas(texto, repositorio, maximo=3)
    bloco = montar_bloco_pessoas(selecionados)
    if not selecionados and eh_pergunta_de_memoria_pessoal(texto):
        return consulta_pessoal_sem_correspondencia(texto)
    return bloco

FIM = object()
_PEDIDO_MEMORIA_EXPLICITO = re.compile(
    r"^\s*(?:alfred[, ]*)?(?:registre|guarde)\s+na\s+memória\s+que\s+(.+?)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_DADO_SENSIVEL_MEMORIA = re.compile(
    r"\b(?:senha|password|token|api[_ -]?key|cart[aã]o de cr[eé]dito|cpf|ssn)\b",
    re.IGNORECASE,
)
_PEDIDO_ENVIO_EMAIL = re.compile(
    r"\b(?:envie|enviar|mande|mandar|encaminhe|encaminhar)\b.{0,80}\b(?:e-?mail|email)\b",
    re.IGNORECASE,
)


class SessaoConversa:
    """Coordena histórico, perfil, ferramentas e persistência de uma conversa."""

    def __init__(
        self,
        provedor: ProvedorLLM,
        configuracao: Configuracao,
        perfil: Perfil | None = None,
        *,
        agora: datetime | None = None,
        confirmar: Callable[[str], str] | None = None,
        interativo_disponivel: bool = False,
    ) -> None:
        self.provedor = provedor
        self.configuracao = configuracao
        self.perfil = perfil if perfil is not None else carregar_perfil(configuracao.pasta_perfil)
        self.prompt_sistema = montar_prompt_sistema(
            self.perfil, agora or datetime.now().astimezone()
        )
        self.historico: list[Mensagem] = []
        self.confirmar = confirmar
        self.ultima_fontes: list[str] = []
        from alfred.memoria.armazenamento.rag import criar_rag
        self.rag = criar_rag(
            configuracao, interativo_disponivel=interativo_disponivel
        )
        self.registro_ferramentas = RegistroDeFerramentas(memoria=self.rag, provedor=self.provedor)
        self.ultimo_blueprint = None
        self.id_sessao = (
            self.rag.iniciar_sessao(configuracao.modelo)
            if self.rag is not None else None
        )

    def responder(self, texto: str) -> Iterator[str]:
        mensagem = texto.strip()
        if not mensagem:
            return
        saudacao = resposta_saudacao(mensagem)
        if saudacao is not None:
            self.historico.extend((Mensagem("user", mensagem), Mensagem("assistant", saudacao)))
            limite = self.configuracao.janela_mensagens
            if len(self.historico) > limite:
                del self.historico[:-limite]
            yield saudacao
            return
        from alfred.blueprint.detector import detectar_pedido, eh_pedido_exibir_blueprint
        from alfred.blueprint.gerador import caminho_blueprint_da_resposta, ler_blueprint

        if eh_pedido_exibir_blueprint(mensagem):
            pasta = self.ultimo_blueprint
            if pasta is None:
                for item in reversed(self.historico):
                    if item.papel == "assistant":
                        pasta = caminho_blueprint_da_resposta(item.conteudo)
                        if pasta is not None:
                            break
            if pasta is not None:
                try:
                    resposta_blueprint = ler_blueprint(pasta)
                except (OSError, ValueError):
                    pasta = None
            if pasta is None:
                pedidos_anteriores = [
                    detectar_pedido(item.conteudo) for item in reversed(self.historico)
                    if item.papel == "user" and detectar_pedido(item.conteudo) is not None
                ]
                pedido_anterior = pedidos_anteriores[0] if pedidos_anteriores else None
                if pedido_anterior is None and self.rag is not None:
                    try:
                        recuperado = self.rag.recuperar_conversas_recentes("", limite=40)
                        linhas = recuperado.partition("\n")[2].splitlines()
                        for linha in reversed(linhas):
                            item = json.loads(linha)
                            if item.get("papel") == "usuario":
                                pedido_anterior = detectar_pedido(str(item.get("conteudo", "")))
                                if pedido_anterior is not None:
                                    break
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pedido_anterior = None
                if pedido_anterior is None:
                    resposta_blueprint = (
                        "Não encontrei um projeto criado nesta conversa. Diga qual projeto "
                        "você quer que eu gere e eu salvo os arquivos antes de confirmar."
                    )
                else:
                    try:
                        resumo = self.registro_ferramentas.executar(
                            "criar_projeto_blueprint",
                            {"descricao": pedido_anterior.descricao, "tipo": pedido_anterior.tipo},
                        )
                        pasta = caminho_blueprint_da_resposta(resumo)
                        self.ultimo_blueprint = pasta
                        resposta_blueprint = ler_blueprint(pasta) if pasta is not None else resumo
                    except Exception:
                        resposta_blueprint = (
                            "Não consegui recuperar nem gerar o blueprint desse projeto. "
                            "Nenhum sucesso foi confirmado."
                        )
            self.historico.extend((Mensagem("user", mensagem), Mensagem("assistant", resposta_blueprint)))
            limite = self.configuracao.janela_mensagens
            if len(self.historico) > limite:
                del self.historico[:-limite]
            yield resposta_blueprint
            return

        pedido_blueprint = detectar_pedido(mensagem)
        if pedido_blueprint is not None:
            try:
                resposta_blueprint = self.registro_ferramentas.executar(
                    "criar_projeto_blueprint",
                    {"descricao": pedido_blueprint.descricao, "tipo": pedido_blueprint.tipo},
                )
            except Exception:
                resposta_blueprint = "Não consegui confirmar a criação do blueprint. Nenhum sucesso foi registrado."
            self.ultimo_blueprint = caminho_blueprint_da_resposta(resposta_blueprint)
            self.historico.extend((Mensagem("user", mensagem), Mensagem("assistant", resposta_blueprint)))
            limite = self.configuracao.janela_mensagens
            if len(self.historico) > limite:
                del self.historico[:-limite]
            if self.rag is not None and self.id_sessao is not None:
                self.rag.registrar_turno(mensagem, resposta_blueprint, self.id_sessao)
            yield resposta_blueprint
            return
        pedido_memoria = _PEDIDO_MEMORIA_EXPLICITO.fullmatch(mensagem)
        if pedido_memoria:
            fato = pedido_memoria.group(1).strip()
            if _DADO_SENSIVEL_MEMORIA.search(fato):
                yield "Não guardo credenciais nem outros dados sensíveis na memória."
                return
            if self.rag is None or self.id_sessao is None:
                yield (
                    "Não consegui salvar essa informação: a memória persistente está "
                    "indisponível nesta sessão."
                )
                return
            try:
                identificador = self.rag.lembrar(fato)
                evento = self.rag.banco.buscar_eventos_por_ids([identificador])
                if not evento or not evento[0]["indexado"]:
                    yield (
                        "A informação foi guardada no banco local, mas ainda não foi "
                        "indexada no gráfico vetorial."
                    )
                    return
            except Exception:
                log.exception("Falha ao registrar pedido explícito de memória.")
                yield "Não consegui confirmar a gravação dessa informação na memória."
                return
            yield "Preferência salva e indexada na memória vetorial."
            return
        contexto_pessoas = _contexto_pessoas(mensagem, self.configuracao)
        pedido_historico = eh_pergunta_de_historico(mensagem)
        if self.rag is not None and pedido_historico:
            buscar_historico = getattr(self.rag, "recuperar_conversas_recentes", None)
            contexto_rag = (
                buscar_historico(mensagem) if callable(buscar_historico)
                else self.rag.recuperar(mensagem)
            )
        else:
            contexto_rag = self.rag.recuperar(mensagem) if self.rag is not None else ""
        contexto_historico = (
            resultado_busca_historico(
                disponivel=(
                    self.rag is not None
                    and getattr(self.rag, "ultima_busca_disponivel", True)
                ),
                encontrado=bool(contexto_rag),
            )
            if pedido_historico else ""
        )
        if pedido_historico and contexto_rag:
            self.ultima_fontes = ["Mensagem atual do usuário", *self.rag.ultima_fontes]
            sistema_turno = instrucao_resumo_historico() + "\n\n" + contexto_rag
        else:
            self.ultima_fontes = [
                "Mensagem atual do usuário",
                "Perfil local: preferencias_ALFRED.md, fatores_estaveis e conhecimento_abrangente",
                "Conhecimento geral ou inferências do modelo não são verificados por fonte externa",
            ]
            if "status=sem_correspondencia" in contexto_pessoas:
                self.ultima_fontes.append("Busca em perfis de pessoas: nenhuma correspondência")
            elif contexto_pessoas:
                self.ultima_fontes.append("Busca em perfis de pessoas: contexto encontrado")
            if self.rag is not None:
                self.ultima_fontes.extend(self.rag.ultima_fontes)
                if not getattr(self.rag, "ultima_busca_disponivel", True):
                    self.ultima_fontes.append("Busca vetorial de memórias: indisponível")
                elif not self.rag.ultima_fontes:
                    self.ultima_fontes.append("Busca vetorial de memórias: nenhuma correspondência")
            sistema_turno = self.prompt_sistema + "\n\n" + contexto_pessoas
            if contexto_rag:
                sistema_turno += "\n\n" + contexto_rag
            elif eh_pergunta_de_memoria_pessoal(mensagem):
                sistema_turno += "\n\n" + marcador_memoria_vazia(
                    disponivel=self.rag is not None and getattr(self.rag, "ultima_busca_disponivel", True)
                )
            if contexto_historico:
                sistema_turno += "\n\n" + contexto_historico
        marcador_atualidade = marcador_de_atualidade(mensagem, self.registro_ferramentas.nomes())
        if marcador_atualidade:
            sistema_turno += "\n\n" + marcador_atualidade
        if _PEDIDO_ENVIO_EMAIL.search(mensagem):
            from alfred.ferramentas.nativas import enviar_email
            situacao_email = enviar_email.verificar_configuracao()
            sistema_turno += (
                "\n\nEstado operacional do SMTP: "
                + ("configurado; a ferramenta enviar_email pode ser usada." if situacao_email is None else situacao_email)
            )
        fatos_declarados = (
            *self.perfil.fatores_estaveis.corpo.splitlines(),
            *self.perfil.conhecimento_abrangente.corpo.splitlines(),
        )
        contradicoes = detectar_contradicoes_explicitas(mensagem, fatos_declarados)
        if contradicoes:
            sistema_turno += "\n\n" + marcador_contradicao(contradicoes)
            self.ultima_fontes.append("Comparação textual: possível contradição com fato declarado")
        if callable(getattr(self.provedor, "conversar_com_ferramentas", None)):
            yield from self._responder_com_ferramentas(mensagem, sistema_turno)
            return
        self.historico.append(Mensagem("user", mensagem))
        if pedido_historico and contexto_rag:
            janela = [Mensagem(
                "user",
                f"Pedido: {mensagem}\n\n"
                "Use os registros recuperados abaixo para responder ao pedido. "
                "Resuma as conversas mais recentes com fidelidade; não responda com o perfil.\n\n"
                f"{contexto_rag}",
            )]
        else:
            janela = self.historico[-self.configuracao.janela_mensagens :]
        partes: list[str] = []
        for trecho in self.provedor.conversar(janela, sistema=sistema_turno):
            if not isinstance(trecho, str):
                raise ErroProvedorLLM("O provedor retornou um trecho em formato inválido")
            partes.append(trecho)
            yield trecho
        resposta = "".join(partes)
        if resposta:
            self.historico.append(Mensagem("assistant", resposta))
        if self.rag is not None and self.id_sessao is not None and resposta:
            self.rag.registrar_turno(mensagem, resposta, self.id_sessao)

    def _responder_com_ferramentas(self, texto: str, sistema_turno: str | None = None) -> Iterator[str]:
        self.historico.append(Mensagem("user", texto))
        for _ in range(3):
            janela = self.historico[-self.configuracao.janela_mensagens :]
            partes: list[str] = []
            chamadas = []
            eventos = self.provedor.conversar_com_ferramentas(
                janela,
                sistema=sistema_turno or self.prompt_sistema,
                ferramentas=self.registro_ferramentas.esquemas_ollama(),
            )
            for evento in eventos:
                if evento.texto:
                    partes.append(evento.texto)
                    yield evento.texto
                chamadas.extend(evento.chamadas)

            resposta = "".join(partes)
            if not chamadas:
                if resposta:
                    self.historico.append(Mensagem("assistant", resposta))
                    if self.rag is not None and self.id_sessao is not None:
                        self.rag.registrar_turno(texto, resposta, self.id_sessao)
                return

            self.historico.append(
                Mensagem("assistant", resposta, chamadas_ferramenta=tuple(chamadas))
            )
            for chamada in chamadas:
                fonte = f"Resultado de ferramenta: {chamada.nome}"
                if fonte not in self.ultima_fontes:
                    self.ultima_fontes.append(fonte)
                try:
                    ferramenta = self.registro_ferramentas.obter(chamada.nome)
                    if chamada.nome == "usar_arquivo_perfil":
                        politica = PoliticaDeConfirmacao(self.registro_ferramentas)
                        pergunta = politica.preparar(chamada.nome, chamada.argumentos)
                        if politica.pendente is None:
                            resultado = pergunta or "Concluído."
                        elif self.confirmar is None:
                            politica.pendente = None
                            resultado = "Ação cancelada: confirmação indisponível."
                        elif interpretar_confirmacao(self.confirmar(pergunta or "Confirma? ")) is True:
                            pendente = politica.pendente
                            politica.pendente = None
                            from alfred.ferramentas.nativas import usar_arquivo_perfil
                            resultado = usar_arquivo_perfil.executar_confirmado(
                                pendente.argumentos, versao_esperada=pendente.versao_perfil
                            )
                        else:
                            politica.pendente = None
                            resultado = "Ação cancelada: não houve confirmação clara."
                    elif ferramenta.sensivel:
                        valores = ferramenta.validar(chamada.argumentos)
                        if chamada.nome == "enviar_email":
                            from alfred.ferramentas.nativas import enviar_email
                            faltante = enviar_email.verificar_configuracao()
                            if faltante:
                                resultado = faltante
                                pergunta = None
                            else:
                                pergunta = (
                                    "Vou enviar este e-mail:\n"
                                    f"Para: {valores['destinatario']}\n"
                                    f"Assunto: {valores['assunto']}\n"
                                    f"Mensagem:\n{valores['mensagem']}\n"
                                    "Confirma o envio? Digite sim ou não: "
                                )
                        elif chamada.nome == "ler_arquivo":
                            pergunta = (
                                f"Quer que eu use o arquivo {valores['nome']} como contexto de perfil? "
                                "Digite sim ou não: "
                            )
                        else:
                            pergunta = "Esta ação precisa da sua confirmação. Digite sim ou não: "
                        if pergunta is not None:
                            if self.confirmar is None:
                                resultado = "Ação cancelada: confirmação indisponível."
                            elif interpretar_confirmacao(self.confirmar(pergunta)) is True:
                                resultado = self.registro_ferramentas.executar(
                                    chamada.nome, valores
                                )
                            else:
                                resultado = "Ação cancelada: não houve confirmação clara."
                    else:
                        resultado = self.registro_ferramentas.executar(
                            chamada.nome, chamada.argumentos
                        )
                except (ValueError, TypeError):
                    resultado = "Ferramenta recusada por argumentos inválidos."
                    falha_ferramenta = True
                except Exception:
                    resultado = "A ferramenta encontrou um erro e não confirmou a ação."
                    falha_ferramenta = True
                else:
                    falha_ferramenta = False
                envelope_resultado = self.registro_ferramentas.resultado_para_modelo(
                    chamada.nome, resultado, falha=falha_ferramenta
                ).para_modelo()
                self.historico.append(Mensagem("tool", envelope_resultado, chamada.nome))
                if chamada.nome == "criar_arquivo" and resultado.startswith("Criei o arquivo "):
                    self.historico.append(Mensagem("assistant", resultado))
                    if self.rag is not None and self.id_sessao is not None:
                        self.rag.registrar_turno(texto, resultado, self.id_sessao)
                    yield resultado
                    return
        yield "Não consegui concluir essa solicitação."

    def limpar(self) -> None:
        self.historico.clear()

    def recarregar(self, *, agora: datetime | None = None) -> None:
        perfil = carregar_perfil(self.configuracao.pasta_perfil)
        prompt = montar_prompt_sistema(perfil, agora or datetime.now().astimezone())
        self.perfil = perfil
        self.prompt_sistema = prompt

    def resumo_perfil(self) -> tuple[str, ...]:
        documentos = (
            self.perfil.preferencias,
            self.perfil.fatores_estaveis,
            self.perfil.conhecimento_abrangente,
        )
        return tuple(
            f"{doc.nome}: versão {doc.versao}, atualizado em {doc.atualizado.isoformat()}, "
            f"{len(doc.corpo.split())} palavras, sha256 {doc.sha256[:8]}"
            for doc in documentos
        )

    def resumo_voz(self) -> str:
        config = self.configuracao
        if config.voz_motor_tts == "voicestudio":
            from alfred.adaptadores.voz.tts_voicestudio import SintetizadorVoiceStudio
            sintetizador = SintetizadorVoiceStudio(
                config.voicestudio_url,
                config.voicestudio_motor,
                config.voicestudio_voz,
                formato=config.voicestudio_formato,
                taxa_amostragem=config.voicestudio_taxa_amostragem,
                timeout_conexao_s=config.voicestudio_timeout_conexao_s,
                timeout_leitura_s=config.voicestudio_timeout_leitura_s,
                # Este cliente só consulta disponibilidade; não sintetiza áudio.
                fallback="texto",
                aquecer=False,
            )
            try:
                sintetizador.verificar_disponibilidade()
                estado = "disponível"
            except Exception:
                estado = "indisponível"
            return (
                f"Motor: {config.voicestudio_motor}; voz: {config.voicestudio_voz}; "
                f"URL loopback: {config.voicestudio_url}; versão: {sintetizador.versao or 'desconhecida'}; "
                f"estado: {estado}; último primeiro byte: n/d; fallback ativo: não (CLI sem sessão de voz)."
            )
        return (
            f"Motor: Piper; voz: {config.voz_caminho_modelo_voz.name}; URL loopback: local; "
            "versão: n/a; estado: configurado; último primeiro byte: n/d; "
            "fallback ativo: não (CLI sem sessão de voz)."
        )
    def executar_comando(self, comando: str) -> str | object | None:
        if (
            comando in {"/configurar_email", "/configuraremail"}
            or comando.startswith(("/configurar_email ", "/configuraremail "))
        ):
            partes = comando.split()
            if len(partes) == 1:
                return "Para configurar pelo painel local, use /configuraremail remetente senha_de_app servidor_smtp porta."
            if len(partes) != 5:
                return (
                    "Uso: /configuraremail remetente senha_de_app servidor_smtp porta. "
                    "A senha deve ser digitada sem espaços; o Alfred a guarda no cofre do Windows."
                )
            from alfred.seguranca.credenciais_email import (
                CofreEmailIndisponivel,
                guardar,
                validar_configuracao,
            )
            try:
                credenciais = validar_configuracao(*partes[1:])
                guardar(credenciais)
            except ValueError as erro:
                return str(erro)
            except CofreEmailIndisponivel as erro:
                return str(erro)
            return "Credenciais de e-mail armazenadas de forma protegida neste computador."
        if comando == "/sair":
            return FIM
        if comando == "/limpar":
            self.limpar()
            return "Histórico da conversa apagado."
        if comando == "/recarregar":
            self.recarregar()
            return "Perfil recarregado."
        if comando == "/perfil":
            return "\n".join(self.resumo_perfil())
        if comando == "/fontes":
            if not self.ultima_fontes:
                return "Ainda não há uma resposta para consultar fontes."
            return "Fontes e contexto do último turno:\n" + "\n".join(
                f"- {fonte}" for fonte in self.ultima_fontes
            )
        if comando == "/voz":
            return self.resumo_voz()
        if comando == "/ajuda":
            return "Comandos: /ajuda, /perfil, /fontes, /voz, /configuraremail remetente senha_de_app servidor_smtp porta, /lembrar <texto>, /esquecer <id>, /limpar, /recarregar, /sair"
        if comando == "/lembrar" or comando.startswith("/lembrar "):
            texto = comando[len("/lembrar"):].strip()
            if not texto:
                return "Uso: /lembrar <informação que deseja guardar>."
            if self.rag is None:
                return "Não consegui guardar: o armazenamento de memória está indisponível."
            pergunta = f"Quer que eu guarde esta informação como memória?\n{texto}\nDigite sim ou não: "
            if self.confirmar is None or interpretar_confirmacao(self.confirmar(pergunta)) is not True:
                return "Memória não guardada; a confirmação não foi aceita."
            try:
                identificador = self.rag.lembrar(texto)
            except Exception:
                log.exception("Falha ao gravar memória explícita")
                return "Não consegui guardar essa memória."
            eventos = self.rag.banco.buscar_eventos_por_ids([identificador])
            if eventos and bool(eventos[0]["indexado"]):
                return "Memória guardada e indexada."
            return "Memória guardada; a indexação será retomada quando o índice estiver disponível."
        if comando == "/esquecer" or comando.startswith("/esquecer "):
            identificador = comando[len("/esquecer"):].strip()
            if not identificador:
                return "Uso: /esquecer <id mostrado em /fontes>."
            if self.rag is None:
                return "Não consegui esquecer: o armazenamento de memória está indisponível."
            pergunta = f"Confirma apagar a memória {identificador}? Essa ação remove também as referências em resumos e no índice. Digite sim ou não: "
            if self.confirmar is None or interpretar_confirmacao(self.confirmar(pergunta)) is not True:
                return "Memória preservada; a confirmação não foi aceita."
            from alfred.memoria.armazenamento.ciclo import CicloMemoria
            try:
                ciclo = CicloMemoria(self.rag.banco, lambda: time_ns() // 1_000_000, rag=self.rag)
                if ciclo.esquecer(identificador, confirmar=True):
                    return "Memória apagada e referências removidas."
                return "Não encontrei essa memória; nada foi apagado."
            except Exception:
                log.exception("Falha ao esquecer memória")
                return "Não consegui esquecer essa memória."
        return None
