"""Geração atômica de blueprints de projetos locais."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from alfred.nucleo.provedor_llm import Mensagem
from alfred.configuracao.configuracao import RAIZ_PROJETO
from alfred.blueprint.detector import classificar_tipo, extrair_nome_projeto
from alfred.blueprint.normas import normas_para
from alfred.blueprint.riscos import bloco_cuidados, classificar_risco, limite_aplicavel
from alfred.ferramentas.nativas._caminhos import resolver_pasta_absoluta, resolver_pasta_confinada


_ARQUIVOS = (
    "00-visao-geral.md", "01-requisitos.md", "02-arquitetura.md",
    "03-plano-de-execucao.md", "04-lista-de-materiais-ou-stack.md",
    "05-riscos-e-seguranca.md", "06-testes-e-validacao.md",
    "07-operacao-e-manutencao.md", "08-proximos-passos.md",
)
_SECOES = (
    ("00-visao-geral.md", "Visão geral", "Objetivo, público, contexto, escopo e fora de escopo; resumo executivo."),
    ("01-requisitos.md", "Requisitos", "Requisitos funcionais e não funcionais com critérios de aceitação verificáveis, prioridades e premissas."),
    ("02-arquitetura.md", "Arquitetura", "Componentes, responsabilidades, interfaces, fluxo de dados, integrações, segurança e desenho Mermaid flowchart padrão."),
    ("03-plano-de-execucao.md", "Plano de execução", "Etapas, dependências, entregáveis e pontos de decisão; não invente prazos."),
    ("04-lista-de-materiais-ou-stack.md", "Materiais ou stack", "Para projeto físico: BOM estimada com item, quantidade, função e alternativa econômica; dimensões a definir após medição/protótipo. Para digital: stack mínima, justificativas e alternativas."),
    ("05-riscos-e-seguranca.md", "Riscos e segurança", "Registro de riscos com probabilidade/impacto qualitativos, mitigação, responsável a definir e verificações legais/técnicas aplicáveis."),
    ("06-testes-e-validacao.md", "Testes e validação", "Plano de testes, critérios de aprovação e validação em ambiente seguro."),
    ("07-operacao-e-manutencao.md", "Operação e manutenção", "Implantação/montagem, operação, suporte, manutenção, recuperação e descarte quando aplicável."),
    ("08-proximos-passos.md", "Próximos passos", "Três ações iniciais concretas, dúvidas/premissas a confirmar e decisões pendentes."),
)
_DIAGRAMAS = {
    "digital": "```mermaid\nflowchart LR\n  U[Pessoa usuária] --> UI[Interface]\n  UI --> API[Serviço da aplicação]\n  API --> DB[(Armazenamento)]\n  API --> EXT[Integrações autorizadas]\n```",
    "fisico": "```mermaid\nflowchart LR\n  IN[Entrada ou energia] --> CTRL[Controle]\n  CTRL --> ACT[Atuação ou saída]\n  SENS[Sensores, se aplicável] --> CTRL\n```",
    "hibrido": "```mermaid\nflowchart LR\n  DEV[Dispositivo e firmware] -->|canal autenticado| GW[Gateway]\n  GW -->|dados minimizados| API[Backend]\n  API --> DB[(Armazenamento)]\n  API --> UI[Interface]\n```",
}
_CONTEXTO_MILITAR_DRONE = re.compile(
    r"\b(?:drone|vant|aeronave nao tripulada)\b.{0,60}\b(?:militar|defesa|tatico)\b|"
    r"\b(?:militar|defesa|tatico)\b.{0,60}\b(?:drone|vant|aeronave nao tripulada)\b",
    re.IGNORECASE,
)


def _slug(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.casefold())
    ascii_texto = "".join(c for c in normalizado if not unicodedata.combining(c))
    valor = re.sub(r"[^a-z0-9]+", "-", ascii_texto).strip("-")
    return (valor[:64].strip("-") or "projeto")


def caminho_blueprint_da_resposta(resposta: str) -> Path | None:
    """Extrai o caminho do resumo gerado pelo código, sem confiar em caminho do LLM."""
    for linha in resposta.splitlines():
        if linha.startswith("Pasta: "):
            valor = Path(linha.removeprefix("Pasta: ").strip())
            try:
                raiz = resolver_pasta_absoluta(RAIZ_PROJETO, criar=True)
                projetos = resolver_pasta_confinada(raiz, "projetos", criar=True)
                projeto = resolver_pasta_confinada(projetos, valor.name)
                if valor.is_absolute() and projeto == valor.resolve(strict=True):
                    return projeto
            except (OSError, ValueError):
                return None
    return None


def ler_blueprint(pasta: Path) -> str:
    """Lê somente os documentos canônicos de um blueprint dentro da pasta autorizada."""
    raiz = resolver_pasta_absoluta(RAIZ_PROJETO, criar=True)
    projetos = resolver_pasta_confinada(raiz, "projetos", criar=True)
    projeto = resolver_pasta_confinada(projetos, pasta.name)
    if projeto != pasta.resolve(strict=True):
        raise ValueError("O caminho do blueprint não corresponde à pasta autorizada.")
    partes = []
    for nome in _ARQUIVOS:
        arquivo = projeto / nome
        if arquivo.is_symlink() or not arquivo.is_file() or arquivo.resolve().parent != projeto:
            raise ValueError("O blueprint está incompleto ou contém caminhos inválidos.")
        partes.append(arquivo.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(partes)


def resumo_blueprint(pasta: Path) -> str:
    """Retorna apenas dados confirmados dos metadados para a resposta de voz."""
    raiz = resolver_pasta_absoluta(RAIZ_PROJETO, criar=True)
    projetos = resolver_pasta_confinada(raiz, "projetos", criar=True)
    projeto = resolver_pasta_confinada(projetos, pasta.name)
    if projeto != pasta.resolve(strict=True):
        raise ValueError("O caminho do blueprint não corresponde à pasta autorizada.")
    arquivo_metadados = projeto / "blueprint.json"
    if arquivo_metadados.is_symlink() or arquivo_metadados.resolve().parent != projeto:
        raise ValueError("Os metadados do blueprint têm um caminho inválido.")
    metadados = json.loads(arquivo_metadados.read_text(encoding="utf-8"))
    return (
        f"Blueprint de {metadados['nome']}: tipo {metadados['tipo']}, "
        f"risco {metadados['risco']}. Os documentos estão em {projeto}."
    )


def _conteudo_llm(provedor: Any, *, descricao: str, tipo: str, nivel: str,
                  nome: str, secao: str, detalhe: str, contexto: str,
                  template: str) -> str:
    sistema = (
        "Você é o gerador documental local do Alfred. Produza somente o conteúdo Markdown "
        "da seção pedida, em português claro. Não execute ações. Marque estimativas como "
        "estimativas, premissas como premissas e informações não fornecidas como 'a definir'. "
        "Nunca invente normas, cláusulas, preços, dimensões, prazos ou certificações. "
        "Se uma referência estiver incerta, escreva 'verificar na norma oficial'. "
        "Não inclua instruções para uso nocivo."
    )
    contexto_especial = ""
    if tipo == "fisico" and _CONTEXTO_MILITAR_DRONE.search(descricao):
        contexto_especial = (
            "Enquadramento de segurança obrigatório: não recuse somente por se tratar de drone "
            "ou contexto militar. Trate como plataforma não armada, com escopo conceitual de "
            "observação de áreas sem identificar indivíduos, busca e salvamento, logística ou "
            "pesquisa. Não inclua armas, integração de armamento, ataques, aquisição de alvos, "
            "interferência/ataque a comunicações ou instruções para vigiar pessoas. Marque a "
            "premissa de uso não armado e inclua cuidados de risco alto.\n\n"
        )
    prompt = (
        f"Projeto: {nome}\nTipo: {tipo}\nRisco avaliado: {nivel}\n"
        f"Descrição original: {descricao}\nNível de detalhe: {detalhe}\n"
        f"Referências a considerar (não declarar conformidade): {contexto}\n"
        f"Orientações específicas de template:\n{template}\n\n"
        f"{contexto_especial}"
        f"Escreva a seção '{secao}'. Escopo desta seção: {next(d for f, _, d in _SECOES if f == secao)}\n"
        "Use listas ou tabelas quando facilitarem a leitura. O texto deve ser específico ao projeto."
    )
    texto = "".join(provedor.conversar([Mensagem("user", prompt)], sistema=sistema)).strip()
    if not texto:
        raise RuntimeError(f"O modelo não produziu conteúdo para {secao}.")
    return texto


def criar_projeto_blueprint(
    descricao: str,
    tipo: str | None = None,
    nivel_detalhe: str = "completo",
    *, provedor: Any | None = None,
    memoria: Any | None = None,
    raiz: str | Path | None = None,
) -> str:
    """Cria nove documentos e metadados sem sobrescrever projeto existente."""
    descricao = descricao.strip()
    if not descricao:
        return "Descreva o projeto para eu criar o blueprint."
    bloqueio = limite_aplicavel(descricao)
    if bloqueio:
        categoria, alternativa = bloqueio
        return f"Não posso criar esse projeto ({categoria.replace('_', ' ')}). Posso ajudar com {alternativa}."
    if provedor is None:
        return "Não foi possível gerar os documentos: o provedor de linguagem não está disponível."
    tipo_final = tipo or classificar_tipo(descricao)
    if tipo_final not in {"digital", "fisico", "hibrido"}:
        return "Tipo inválido. Use digital, fisico ou hibrido."
    if nivel_detalhe not in {"resumido", "completo", "tecnico"}:
        return "Nível de detalhe inválido. Use resumido, completo ou tecnico."
    nome = extrair_nome_projeto(descricao)
    slug_base = _slug(nome)
    risco, fatores = classificar_risco(descricao)
    referencias = normas_para(tipo_final, descricao)
    normas_txt = "\n".join(f"- {n['identificador']}: {n['uso']} ({n['fonte']})" for n in referencias)
    base = Path(raiz) if raiz is not None else Path(__file__).resolve().parents[3]
    try:
        base = resolver_pasta_absoluta(base, criar=True)
        projetos = resolver_pasta_confinada(base, "projetos", criar=True)
    except (OSError, ValueError):
        return "Não consegui criar o blueprint: a pasta de projetos não passou pela validação de segurança."
    destino = projetos / slug_base
    sufixo = 2
    while destino.exists():
        destino = projetos / f"{slug_base}-{sufixo}"
        sufixo += 1
    try:
        resolver_pasta_confinada(projetos, destino.name)
    except ValueError:
        return "Não consegui criar o blueprint: o caminho de destino não passou pela validação de segurança."
    template_path = Path(__file__).with_name("templates") / f"{tipo_final}.md"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError:
        return "Não consegui criar o blueprint: o template do projeto está indisponível."
    temporario = Path(tempfile.mkdtemp(prefix=".blueprint-", dir=projetos))
    try:
        for arquivo, titulo, _ in _SECOES:
            conteudo = _conteudo_llm(
                provedor, descricao=descricao, tipo=tipo_final, nivel=risco,
                nome=nome, secao=arquivo, detalhe=nivel_detalhe,
                contexto=normas_txt, template=template,
            )
            if arquivo == "02-arquitetura.md" and not re.search(
                r"```mermaid\s*flowchart\s+(?:LR|TB|RL|BT)\b", conteudo, re.IGNORECASE
            ):
                conteudo += "\n\n" + _DIAGRAMAS[tipo_final]
            if arquivo == "05-riscos-e-seguranca.md":
                cuidados = bloco_cuidados(risco, fatores)
                if cuidados:
                    conteudo = cuidados + "\n\n" + conteudo
                conteudo += "\n\n## Referências para validação\n\n" + normas_txt
            (temporario / arquivo).write_text(f"# {titulo}\n\n{conteudo}\n", encoding="utf-8")
        metadados = {
            "versao": 1, "slug": destino.name, "nome": nome,
            "tipo": tipo_final, "risco": risco, "fatores_risco": list(fatores),
            "descricao": descricao, "nivel_detalhe": nivel_detalhe,
            "normas_referencias": referencias,
            "criado_em": datetime.now(timezone.utc).isoformat(),
            "arquivos": list(_ARQUIVOS),
            "observacao": "Referências são orientativas; confirme edição, vigência e aplicabilidade em fontes oficiais.",
        }
        (temporario / "blueprint.json").write_text(
            json.dumps(metadados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporario.rename(destino)
    except Exception as erro:
        shutil.rmtree(temporario, ignore_errors=True)
        return f"Não consegui concluir o blueprint; nenhum projeto parcial foi publicado ({type(erro).__name__})."

    indexacao = ""
    if memoria is not None:
        try:
            documentos = {p.name: p.read_text(encoding="utf-8") for p in destino.glob("*.md")}
            memoria.indexar_documentos_projeto(destino.name, documentos)
            indexacao = " Os documentos foram enviados para indexação na memória RAG."
        except Exception:
            indexacao = " A memória RAG não confirmou a indexação; os arquivos foram preservados."
    cuidados = bloco_cuidados(risco, fatores)
    resumo_cuidados = f"\n{cuidados}" if cuidados else ""
    proximos = "\n".join((
        "1. Revise o escopo e confirme as premissas.",
        "2. Valide requisitos e riscos com as pessoas responsáveis.",
        "3. Escolha um primeiro protótipo ou tarefa do MVP.",
    ))
    return (
        f"Blueprint criado: {nome}\nTipo: {tipo_final} | Risco: {risco}\n"
        f"Pasta: {destino}\nPróximos passos:\n{proximos}{resumo_cuidados}{indexacao}"
    )
