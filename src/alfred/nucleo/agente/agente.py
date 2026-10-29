"""Laço de agente com streaming, histórico limitado e ferramentas validadas."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.ferramentas.resultado import ResultadoFerramenta
from alfred.nucleo.agente.roteador_rapido import resposta_curta, resposta_saudacao, rotear_comando
from alfred.nucleo.agente.streaming import DivisorDeFrases, em_thread, obter_confirmacao
from alfred.nucleo.politicas.atualidade import marcador_de_atualidade
from alfred.nucleo.politicas.capacidades import montar_manifesto_capacidades
from alfred.nucleo.politicas.confirmacao import PoliticaDeConfirmacao
from alfred.nucleo.politicas.verificador_alegacoes import (
    PEDIDO_DE_REVISAO,
    RESPOSTA_SEM_CONFIRMACAO,
    alegacao_confirmada,
    e_alegacao_de_acao,
)
from alfred.nucleo.provedor_llm import EventoLLM, Mensagem, ProvedorLLMComFerramentas


class Agente:
    def __init__(
        self,
        provedor: ProvedorLLMComFerramentas,
        sistema: str,
        *,
        limite_interacoes: int = 6,
        registro: RegistroDeFerramentas | None = None,
        confirmacao: PoliticaDeConfirmacao | None = None,
        depuracao: bool = False,
        contexto_por_mensagem: Callable[[str], str] | None = None,
        registrar_conversa: Callable[[str, str], None] | None = None,
        modo_voz: bool = False,
    ) -> None:
        self.provedor = provedor
        self.modo_voz = modo_voz
        linhas_sistema = sistema.splitlines()
        marcadores_horario = [linha for linha in linhas_sistema
                              if linha.startswith("Data e hora atuais: ")]
        self._marcador_horario = marcadores_horario[-1] if marcadores_horario else ""
        if self._marcador_horario:
            linhas_sistema.remove(self._marcador_horario)
            sistema = "\n".join(linhas_sistema).strip()
        self.sistema = sistema
        if modo_voz:
            self.sistema += (
                "\n\nMODO VOZ: responda em português brasileiro como numa conversa natural. "
                "Prefira ser breve, mas não imponha um limite fixo de frases; desenvolva quando "
                "o assunto pedir. Use reações breves e naturais quando couber, sem repeti-las "
                "como bordões. Não repita a pergunta, "
                "não use frases de espera, Markdown, listas, emojis ou URLs. Exemplo: pergunta direta, "
                "resposta direta; se faltar um dado essencial, faça uma pergunta curta. Tolere erros "
                "de transcrição e use o contexto recente para resolver referências e correções. "
                "Se houver mais de uma interpretação plausível e a diferença mudar a resposta "
                "ou uma ação, faça uma pergunta curta em vez de adivinhar. "
                "Ajuste o tom ao que foi dito sem presumir emoções nem fingir ser humana. Escreva "
                "números e siglas para leitura em voz alta. Não inicie assuntos pessoais; não repita "
                "dados sensíveis sem necessidade. Nunca revele raciocínio interno. Ações continuam "
                "sujeitas às confirmações e validações do código. Ao criar um blueprint, "
                "use criar_projeto_blueprint e fale apenas o resumo retornado: nome, tipo, "
                "risco, caminho dos arquivos e três próximos passos. O conteúdo completo fica "
                "nos arquivos; não leia o blueprint inteiro em voz alta."
            )
        self.limite_interacoes = max(1, limite_interacoes)
        self.registro = registro or RegistroDeFerramentas()
        provedor_modelo = getattr(provedor, "modelo", None)
        provedor_url = getattr(provedor, "url_base", None)
        self.sistema += "\n\n" + montar_manifesto_capacidades(
            self.registro, modelo=provedor_modelo, url_base=provedor_url
        )
        if modo_voz:
            self.sistema += (
                "\n\nIDENTIDADE FIXA: seu nome é Alfred. Se perguntarem seu nome, diga "
                "‘Sou o Alfred.’ Não negue nem contradiga esse nome. Alfred é seu nome de "
                "assistente; seja honesto de que você é uma inteligência artificial, não uma pessoa."
            )
        self.confirmacao = confirmacao or PoliticaDeConfirmacao(self.registro)
        self.historico: list[Mensagem] = []
        self.ultimo_blueprint = None
        self.depuracao = depuracao
        self.contexto_por_mensagem = contexto_por_mensagem
        self.registrar_conversa = registrar_conversa

    async def responder(self, texto: str, *, receber_confirmacao: Callable[[], Any] | None = None,
                        ao_primeiro_token: Callable[[], None] | None = None) -> AsyncIterator[str]:
        if not texto.strip():
            return
        saudacao = resposta_saudacao(texto)
        if saudacao is not None:
            mensagem = texto.strip()
            self.historico.extend((Mensagem("user", mensagem), Mensagem("assistant", saudacao)))
            if ao_primeiro_token is not None:
                ao_primeiro_token()
            yield saudacao
            return
        from alfred.blueprint.detector import detectar_pedido, eh_pedido_exibir_blueprint
        from alfred.blueprint.gerador import (
            caminho_blueprint_da_resposta,
            resumo_blueprint,
        )

        if eh_pedido_exibir_blueprint(texto):
            mensagem = texto.strip()
            pasta = self.ultimo_blueprint
            if pasta is None:
                for item in reversed(self.historico):
                    if item.papel == "assistant":
                        pasta = caminho_blueprint_da_resposta(item.conteudo)
                        if pasta is not None:
                            break
            if pasta is None:
                pedido_anterior = next(
                    (detectar_pedido(item.conteudo) for item in reversed(self.historico)
                     if item.papel == "user" and detectar_pedido(item.conteudo) is not None),
                    None,
                )
                if pedido_anterior is not None:
                    try:
                        resumo = self.registro.executar(
                            "criar_projeto_blueprint",
                            {"descricao": pedido_anterior.descricao, "tipo": pedido_anterior.tipo},
                        )
                        pasta = caminho_blueprint_da_resposta(resumo)
                        self.ultimo_blueprint = pasta
                    except Exception:
                        pasta = None
            try:
                resposta = resumo_blueprint(pasta) if pasta is not None else (
                    "Não encontrei um blueprint criado nesta conversa. Diga qual projeto "
                    "você quer que eu gere e eu salvo os arquivos antes de confirmar."
                )
            except (OSError, ValueError, KeyError):
                resposta = "Não consegui recuperar os arquivos do blueprint desse projeto."
            self.historico.extend((Mensagem("user", mensagem), Mensagem("assistant", resposta)))
            if ao_primeiro_token is not None:
                ao_primeiro_token()
            yield resposta
            if self.registrar_conversa is not None:
                await asyncio.to_thread(self.registrar_conversa, mensagem, resposta)
            return

        pedido_blueprint = detectar_pedido(texto)
        if pedido_blueprint is not None:
            mensagem = texto.strip()
            self.historico.append(Mensagem("user", mensagem))
            try:
                resposta_blueprint = self.registro.executar(
                    "criar_projeto_blueprint",
                    {"descricao": pedido_blueprint.descricao, "tipo": pedido_blueprint.tipo},
                )
            except Exception:
                resposta_blueprint = "Não consegui confirmar a criação do blueprint. Nenhum sucesso foi registrado."
            self.ultimo_blueprint = caminho_blueprint_da_resposta(resposta_blueprint)
            self.historico.append(Mensagem("assistant", resposta_blueprint))
            if ao_primeiro_token is not None:
                ao_primeiro_token()
            yield resposta_blueprint
            if self.registrar_conversa is not None:
                await asyncio.to_thread(self.registrar_conversa, mensagem, resposta_blueprint)
            posicoes_usuario = [i for i, item in enumerate(self.historico) if item.papel == "user"]
            if len(posicoes_usuario) > self.limite_interacoes:
                del self.historico[:posicoes_usuario[-self.limite_interacoes]]
            return
        atalho = rotear_comando(texto) if self.modo_voz else None
        if atalho is not None:
            try:
                if self.registro.obter(atalho.chamada.nome).sensivel:
                    atalho = None
            except ValueError:
                atalho = None
        if atalho is not None:
            mensagem = texto.strip()
            self.historico.append(Mensagem("user", mensagem))
            try:
                resultado = self.confirmacao.preparar(
                    atalho.chamada.nome, atalho.chamada.argumentos
                )
                tipado = self.registro.resultado_para_modelo(
                    atalho.chamada.nome, resultado or "Concluído."
                )
                fala = resposta_curta(
                    atalho.categoria, atalho.chamada.argumentos, resultado or ""
                )
                if e_alegacao_de_acao(fala) and not alegacao_confirmada(fala, [tipado]):
                    fala = RESPOSTA_SEM_CONFIRMACAO
            except (ValueError, TypeError):
                self.historico.pop()
            else:
                if ao_primeiro_token is not None:
                    ao_primeiro_token()
                yield fala
                self.historico.append(Mensagem("assistant", fala))
                if self.registrar_conversa is not None:
                    await asyncio.to_thread(
                        self.registrar_conversa, mensagem, fala
                    )
                posicoes_usuario = [
                    i for i, item in enumerate(self.historico)
                    if item.papel == "user"
                ]
                if len(posicoes_usuario) > self.limite_interacoes:
                    del self.historico[:posicoes_usuario[-self.limite_interacoes]]
                return
        sistema_turno = self.sistema
        marcador_atualidade = marcador_de_atualidade(texto, self.registro.nomes())
        if marcador_atualidade:
            sistema_turno += "\n\n" + marcador_atualidade
        if self.contexto_por_mensagem is not None:
            contexto_pessoas = await asyncio.to_thread(
                self.contexto_por_mensagem, texto.strip()
            )
            if contexto_pessoas:
                sistema_turno += "\n\n" + contexto_pessoas
        if self._marcador_horario:
            sistema_turno += "\n\n" + self._marcador_horario
        self.historico.append(Mensagem("user", texto.strip()))
        posicoes_usuario = [i for i, mensagem in enumerate(self.historico) if mensagem.papel == "user"]
        if len(posicoes_usuario) > self.limite_interacoes:
            del self.historico[:posicoes_usuario[-self.limite_interacoes]]
        contexto = list(self.historico)
        # Em voz, não emita um corte arbitrário no meio da oração. Aguarde
        # pontuação ou o fim da resposta para entregar unidades completas ao TTS.
        divisor = DivisorDeFrases()
        resposta: list[str] = []
        alegacoes_retidas: list[str] = []
        resultados_turno: list[ResultadoFerramenta] = []
        revisao_usada = False
        token_notificado = False
        notificacao_direta = False
        chamadas_pendentes: tuple[Any, ...] = ()
        for rodada in range(4):
            eventos = self.provedor.conversar_com_ferramentas(contexto, sistema=sistema_turno,
                                                               ferramentas=self.registro.esquemas_ollama())
            async for evento in em_thread(eventos):
                if not isinstance(evento, EventoLLM):
                    continue
                if evento.texto:
                    if not token_notificado and ao_primeiro_token is not None:
                        ao_primeiro_token()
                        token_notificado = True
                    for frase in divisor.adicionar(evento.texto):
                        if e_alegacao_de_acao(frase):
                            alegacoes_retidas.append(frase)
                        else:
                            resposta.append(frase)
                            yield frase
                chamadas_pendentes += evento.chamadas
            final = divisor.finalizar()
            if final:
                if e_alegacao_de_acao(final):
                    alegacoes_retidas.append(final)
                else:
                    resposta.append(final)
                    yield final
            if not chamadas_pendentes:
                invalidas = [
                    frase for frase in alegacoes_retidas
                    if not alegacao_confirmada(frase, resultados_turno)
                ]
                validas = [
                    frase for frase in alegacoes_retidas
                    if alegacao_confirmada(frase, resultados_turno)
                ]
                alegacoes_retidas.clear()
                for frase in validas:
                    resposta.append(frase)
                    yield frase
                if invalidas and not revisao_usada:
                    revisao_usada = True
                    contexto.append(Mensagem("tool", PEDIDO_DE_REVISAO, "verificador_alegacoes"))
                    divisor = DivisorDeFrases()
                    continue
                if invalidas:
                    resposta.append(RESPOSTA_SEM_CONFIRMACAO)
                    yield RESPOSTA_SEM_CONFIRMACAO
                break
            chamadas, chamadas_pendentes = chamadas_pendentes, ()
            chamada_assistente = Mensagem("assistant", "", chamadas_ferramenta=chamadas)
            self.historico.append(chamada_assistente)
            contexto.append(chamada_assistente)
            for chamada in chamadas:
                if self.depuracao:
                    print(f"[DEBUG ferramenta] {chamada.nome}")
                try:
                    resultado = self.confirmacao.preparar(chamada.nome, chamada.argumentos)
                    if self.confirmacao.pendente:
                        try:
                            if chamada.nome == "usar_arquivo_perfil":
                                print(f"[Confirmação completa] {resultado}")
                                yield self.confirmacao.resumo_voz()
                            else:
                                yield resultado or "Ação aguardando confirmação."
                            if receber_confirmacao is None:
                                resultado = "Confirmação indisponível; ação cancelada."
                                self.confirmacao.pendente = None
                            else:
                                resultado = await self.confirmacao.resolver(
                                    obter_confirmacao(receber_confirmacao)
                                )
                        except asyncio.CancelledError:
                            self.confirmacao.pendente = None
                            raise
                    resultado_tipado = self.registro.resultado_para_modelo(
                        chamada.nome, resultado or "Concluído."
                    )
                    resultados_turno.append(resultado_tipado)
                    self.historico.append(Mensagem("tool", resultado_tipado.para_modelo(), chamada.nome))
                    contexto.append(self.historico[-1])
                    if chamada.nome == "criar_arquivo" and (resultado or "").startswith("Criei o arquivo "):
                        resposta.append(resultado)
                        notificacao_direta = True
                        yield resultado
                except (ValueError, TypeError):
                    resultado_tipado = self.registro.resultado_para_modelo(
                        chamada.nome, "Ferramenta recusada por argumentos inválidos.", falha=True
                    )
                    resultados_turno.append(resultado_tipado)
                    self.historico.append(Mensagem("tool", resultado_tipado.para_modelo(), chamada.nome))
                    contexto.append(self.historico[-1])
                except Exception:
                    resultado_tipado = self.registro.resultado_para_modelo(
                        chamada.nome, "A ferramenta encontrou um erro e não confirmou a ação.", falha=True
                    )
                    resultados_turno.append(resultado_tipado)
                    self.historico.append(Mensagem("tool", resultado_tipado.para_modelo(), chamada.nome))
                    contexto.append(self.historico[-1])
            if notificacao_direta:
                break
            resposta.clear()
            divisor = DivisorDeFrases()
        else:
            yield "Não consegui concluir essa solicitação."
        if resposta:
            self.historico.append(Mensagem("assistant", "".join(resposta)))
        if self.registrar_conversa is not None and resposta:
            await asyncio.to_thread(
                self.registrar_conversa, texto.strip(), " ".join(resposta)
            )
        # Remova interações antigas por pares de turnos, mantendo resultados junto ao turno.
        posicoes_usuario = [i for i, mensagem in enumerate(self.historico) if mensagem.papel == "user"]
        if len(posicoes_usuario) > self.limite_interacoes:
            del self.historico[:posicoes_usuario[-self.limite_interacoes]]
