"""
core/intent_classifier.py — Classificador de intenção baseado em palavras-chave.

Determina SE uma mensagem é uma ação de sistema ou uma conversa geral,
e extrai a ação + payload para o SystemAgent quando aplicável.

Design:
    • Zero dependências de ML — funciona offline e é determinístico.
    • Fácil de estender: basta adicionar entradas nos dicts abaixo.
    • Substitua classify() por um modelo de classificação quando precisar
      de maior cobertura semântica.

Retorna IntentResult com:
    agent   — "system" | "vision" | "general"
    action  — chave de ação (open_app, create_folder, list_folder, system_info, screenshot, analyze_image) ou ""
    payload — argumento da ação ou ""
    confidence — 0.0–1.0 (baseada no número de triggers encontrados)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Vision rules — avaliado ANTES das regras de sistema
# ---------------------------------------------------------------------------

_VISION_RULES: List[Tuple[List[str], str, float]] = [
    # Screenshot / captura de tela
    ([
        "tire um print", "tira um print", "screenshot", "captura de tela",
        "take a screenshot", "take screenshot", "print screen",
        "o que está na minha tela", "o que tem na minha tela",
        "what's on my screen", "what is on my screen",
    ], "screenshot", 0.95),
    # Análise de imagem enviada
    ([
        "analise esta imagem", "analise a imagem", "analisar imagem",
        "analyze this image", "analyze the image", "analyze image",
        "descreva a imagem", "descreva esta imagem", "describe the image",
        "describe this image", "o que você vê", "o que você ve",
        "what do you see", "what can you see", "o que é isso",
        "o que é esta imagem", "what is this image",
    ], "analyze_image", 0.92),
    # Perguntas genéricas sobre visão / o que está na tela
    ([
        "o que tem na tela", "o que está na tela", "veja minha tela",
        "olhe a tela", "look at my screen", "see my screen",
        "what's on the screen", "what is on the screen",
    ], "screenshot", 0.88),
]


@dataclass
class IntentResult:
    agent:      str   = "general"    # "system" | "vision" | "general"
    action:     str   = ""           # subcategoria da ação de sistema
    payload:    str   = ""           # argumento extraído
    confidence: float = 0.0          # grau de certeza da classificação


# ---------------------------------------------------------------------------
# Regras  —  (triggers, action, base_confidence)
# ---------------------------------------------------------------------------

# Cada entrada: (lista de substrings trigger, nome da ação, confiança base)
_SYSTEM_RULES: List[Tuple[List[str], str, float]] = [
    # Abrir aplicativos
    (
        ["abrir ", "abre ", "open ", "abra ", "inicia ", "iniciar ", "lança ", "lançar ",
         "start ", "launch ", "executar ", "execute "],
        "open_app",
        0.80,
    ),
    # Informações do sistema
    (
        ["uso de cpu", "uso da cpu", "cpu usage", "uso de memória", "uso da memória",
         "uso de ram", "ram usage", "quanto de memória", "status do sistema",
         "system info", "informações do sistema", "processos rodando",
         "performance do sistema", "disco cheio", "espaço em disco", "disk usage",
         "quanta ram", "quanto cpu", "uso do processador", "uso do disco"],
        "system_info",
        0.90,
    ),
    # Criar pasta/diretório
    (
        ["criar pasta", "crie uma pasta", "crie a pasta", "nova pasta", "new folder",
         "mkdir", "crie o diretório", "crie a pasta", "criar diretório",
         "create folder", "create directory", "cria pasta", "criar um diretório"],
        "create_folder",
        0.90,
    ),
    # Listar arquivos/pasta
    (
        ["liste os arquivos", "listar arquivos", "listar pasta", "list files",
         "show files", "mostrar arquivos", "conteúdo da pasta", "o que tem na pasta",
         "what's in", "quais arquivos", "ls ", "dir da pasta", "ver pasta",
         "mostre a pasta", "mostre os arquivos", "listar o diretório"],
        "list_folder",
        0.85,
    ),
    # Exportar base de conhecimento para NotebookLM
    (
        [
            "prepare meu conhecimento", "prepare o conhecimento",
            "exportar conhecimento", "export knowledge",
            "notebooklm", "notebook lm",
            "gerar knowledge base", "consolidar conhecimento",
            "preparar conhecimento", "alfred prepare",
            "base de conhecimento para", "knowledge base para",
        ],
        "export_knowledge",
        0.96,
    ),
    # Status do monitoramento / alertas proativos
    (
        ["o que está rodando", "o que esta rodando", "what's running", "what is running",
         "log de monitoramento", "monitor de sistema", "últimos alertas", "ultimos alertas",
         "alertas recentes", "histórico de alertas", "historico de alertas",
         "status do monitor", "o que aconteceu", "o que alfred viu",
         "o que alfred monitorou", "o que está acontecendo no sistema",
         "processos ativos agora", "o que alfred está monitorando"],
        "monitor_status",
        0.88,
    ),
]

# ---------------------------------------------------------------------------
# Regras de integração (weather, news, calendar, briefing matinal)
# Avaliadas ANTES das regras de sistema por terem prioridade de roteamento.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regras de desenvolvimento (Git, código, commits)
# Avaliadas logo após as regras de integração.
# ---------------------------------------------------------------------------

_DEV_RULES: List[Tuple[List[str], str, float]] = [
    # Status Git
    (
        ["git status", "status do repositório", "status do repo",
         "arquivos modificados", "arquivos não commitados", "não commitados",
         "o que mudou", "alterações pendentes", "pending changes",
         "git diff", "what changed", "ver modificações", "ver alterações"],
        "git_status",
        0.90,
    ),
    # Resumo de arquivo
    (
        ["resuma o arquivo", "resume o arquivo", "summarize", "resumo técnico",
         "explique o arquivo", "descreva o arquivo", "documente o arquivo",
         "summarize file", "explain file", "o que faz o arquivo",
         "read the file", "leia o arquivo"],
        "summarize_file",
        0.88,
    ),
    # Sugestão de commit
    (
        ["sugestão de commit", "sugira um commit", "mensagem de commit",
         "conventional commit", "git commit", "o que commitar",
         "commit message", "suggest commit", "crie um commit",
         "me ajude a fazer o commit"],
        "suggest_commit",
        0.92,
    ),
    # Tech stack
    (
        ["stack tecnológica", "tech stack", "quais tecnologias",
         "que tecnologia", "fraemwork", "frameworks do projeto",
         "bibliotecas do projeto", "memorize a stack", "salve a stack",
         "tecnologias do projeto", "linguagens do projeto"],
        "tech_stack",
        0.87,
    ),
    # Status do lab (atalho para morning briefing)
    (
        ["status do lab", "lab status", "status do projeto"],
        "lab_status",
        0.85,
    ),
    # Editar / modificar arquivo
    (
        ["edite o arquivo", "altere o arquivo", "modifique o arquivo",
         "mude o arquivo", "editar arquivo", "alterar arquivo",
         "modificar arquivo", "mudar arquivo", "edit file", "edit the file",
         "modify file", "change file", "update file", "atualize o arquivo",
         "reescreva o arquivo", "adicione ao arquivo", "remova do arquivo",
         "adicione no arquivo", "insira no arquivo", "delete from file",
         "escreva no arquivo", "corrija o arquivo", "fix the file"],
        "edit_file",
        0.88,
    ),
    # Auto-incremento: Alfred cria/expande suas próprias funcionalidades
    (
        ["adicione funcionalidade", "crie uma feature", "nova feature",
         "crie um agente", "auto incrementar", "auto melhorar",
         "adicione capacidade", "novo recurso", "new feature",
         "expanda o alfred", "melhore o alfred", "adicione habilidade",
         "implemente uma funcionalidade", "alfred se incremente",
         "adicione ao alfred", "crie para o alfred",
         "nova habilidade para o alfred", "ensine o alfred",
         "self improve", "self increment", "auto increment"],
        "self_improve",
        0.85,
    ),
]

# ---------------------------------------------------------------------------
# Regras de pesquisa web em tempo real
# Avaliadas ANTES das regras de integração — têm prioridade para buscas
# que precisam de dados ao vivo (cotações, eventos, tópicos em destaque).
# ---------------------------------------------------------------------------

_RESEARCH_RULES: List[Tuple[List[str], str, float]] = [
    # Busca explícita na web
    (
        ["pesquise sobre", "pesquise na web", "busque na internet", "pesquisa na web",
         "procure na web", "busque na web", "search the web", "pesquise por",
         "busque por", "procure por", "me mostre pesquisas sobre",
         "pesquisa sobre"],
        "web_search",
        0.95,
    ),
    # Cotações e preços em tempo real
    (
        ["cotação", "cotações", "preço do dólar", "preço do bitcoin",
         "valor do dólar", "valor do bitcoin", "preço da", "cotação do",
         "cotação da", "bolsa de valores", "ibovespa", "nasdaq",
         "criptomoeda", "cripto hoje", "quanto vale o", "preço atual do",
         "dólar hoje", "euro hoje"],
        "web_search",
        0.92,
    ),
    # Eventos/notícias recentes com marcador de tempo
    (
        ["o que aconteceu hoje", "o que está acontecendo", "evento recente",
         "lançamento recente", "recém lançado", "acontecimentos recentes",
         "o que há de novo sobre", "últimas notícias sobre", "notícia recente",
         "notícias recentes", "novidade sobre"],
        "web_search",
        0.90,
    ),
    # Erros/versões de bibliotecas muito recentes
    (
        ["versão atual do", "versão atual da", "última versão do", "última versão da",
         "novo release do", "changelog do", "release notes do",
         "erro no python", "bug no python", "problema no python"],
        "web_search",
        0.85,
    ),
    # Tópicos de foco especial (sempre vai para pesquisa)
    (
        ["crise hídrica", "ia descentralizada", "inteligência artificial descentralizada",
         "crise da água", "water crisis", "decentralized ai", "crise hidrica"],
        "web_search",
        0.97,
    ),
]

_INTEGRATION_RULES: List[Tuple[List[str], str, float]] = [
    # Briefing matinal
    (
        ["bom dia", "good morning", "bom dia alfred", "good morning alfred",
         "briefing", "resumo do dia", "resumo matinal", "morning briefing",
         "me dê o briefing", "briefing matinal", "começar o dia"],
        "morning_briefing",
        0.95,
    ),
    # Clima
    (
        ["clima", "temperatura", "tempo agora", "como está o tempo", "como ta o tempo",
         "weather", "previsão do tempo", "previsao do tempo", "vai chover",
         "faz calor", "faz frio", "quantos graus", "graus lá fora"],
        "weather",
        0.88,
    ),
    # Notícias de tech
    (
        ["notícias", "noticias", "news", "últimas notícias", "ultimas noticias",
         "novidades", "tech news", "novidades de tech", "novidades de programação",
         "novidades de programacao", "o que há de novo em tech"],
        "news",
        0.85,
    ),
    # Calendário / agenda
    (
        ["agenda", "tarefas", "o que tenho hoje", "meus compromissos",
         "próxima reunião", "proxima reuniao", "calendar", "schedule",
         "deadline", "prazo", "compromisso", "o que está na agenda"],
        "calendar",
        0.85,
    ),
]

# Gatilhos adicionais que elevam a prob. de "system" mas sem ação específica
_SYSTEM_SOFT_TRIGGERS = [
    "no meu computador", "no sistema", "no pc", "no windows", "no linux",
    "no mac", "on my computer", "arquivo", "pasta", "diretório", "aplicativo",
    "programa", "abrir o", "fechar o",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, colapsa espaços, remove pontuação lateral."""
    text = text.lower().strip()
    text = re.sub(r"[!?,;:]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_path(text: str) -> str:
    """Extrai candidato a caminho de sistema do texto original."""
    patterns = [
        r'[A-Za-z]:\\[^\s"\']+',   # C:\foo\bar
        r'~/[^\s"\']*',             # ~/Documentos
        r'/[^\s"\']+',              # /home/user
        r'[A-Za-z]:/[^\s"\']+',    # C:/foo
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0).rstrip('.,!?"\'')
    return ""


def _extract_app_name(text: str, norm: str) -> str:
    """
    Tenta extrair o nome do aplicativo depois de verbos de abertura.
    Retorna string vazia se não encontrar.
    """
    from agents.system_agent import _APP_MAP  # importação local para evitar ciclo

    # Verifica aliases diretos
    for key in _APP_MAP:
        aliases = [key]
        if key == "vscode":
            aliases += ["vs code", "visual studio code", "vscode"]
        for alias in aliases:
            if alias in norm:
                return key

    # Extrai palavra após o verbo
    m = re.search(
        r'(?:abrir?|abre|open|inicia[rn]?|launch|start)\s+([a-zà-ú0-9_\-\.]+)',
        norm,
    )
    if m:
        return m.group(1)
    return ""


def _extract_folder_name(text: str, norm: str) -> str:
    """Extrai nome/caminho de pasta da mensagem."""
    from pathlib import Path

    # Primeiro tenta caminho direto
    path = _extract_path(text)
    if path:
        return path

    # Texto entre aspas
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        candidate = m.group(1)
        if not Path(candidate).is_absolute():
            return str(Path.home() / candidate)
        return candidate

    # "chamado X" / "chamada X" / "named X"
    m2 = re.search(r'(?:chamad[ao]|named?)\s+([^\s.,!?"\']+)', text, re.IGNORECASE)
    if m2:
        return str(Path.home() / m2.group(1))

    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(message: str) -> IntentResult:
    """
    Classifica a intenção da mensagem e retorna um IntentResult.

    Args:
        message: Mensagem bruta do usuário.

    Returns:
        IntentResult com agent, action, payload e confidence.
    """
    norm = _normalize(message)

    # ── Vision rules (prioridade máxima) ─────────────────────────────
    best_vision_conf   = 0.0
    best_vision_action = ""

    for triggers, action, base_conf in _VISION_RULES:
        hits = sum(1 for t in triggers if t in norm)
        if hits == 0:
            continue
        conf = min(base_conf + (hits - 1) * 0.02, 0.99)
        if conf > best_vision_conf:
            best_vision_conf   = conf
            best_vision_action = action

    _VISION_THRESHOLD = 0.75

    if best_vision_conf >= _VISION_THRESHOLD:
        return IntentResult(
            agent="vision",
            action=best_vision_action,
            payload="",
            confidence=best_vision_conf,
        )
    # ── DEV rules (2ª prioridade: Git, código, commits) ──────────────
    best_dev_conf   = 0.0
    best_dev_action = ""

    for triggers, action, base_conf in _DEV_RULES:
        hits = sum(1 for t in triggers if t in norm)
        if hits == 0:
            continue
        conf = min(base_conf + (hits - 1) * 0.02, 0.99)
        if conf > best_dev_conf:
            best_dev_conf   = conf
            best_dev_action = action

    _DEV_THRESHOLD = 0.60

    if best_dev_conf >= _DEV_THRESHOLD:
        return IntentResult(
            agent="dev",
            action=best_dev_action,
            payload="",
            confidence=best_dev_conf,
        )
    # ── Research rules (3ª prioridade — dados ao vivo superam notícias estáticas) ─
    best_res_conf   = 0.0
    best_res_action = ""

    for triggers, action, base_conf in _RESEARCH_RULES:
        hits = sum(1 for t in triggers if t in norm)
        if hits == 0:
            continue
        conf = min(base_conf + (hits - 1) * 0.02, 0.99)
        if conf > best_res_conf:
            best_res_conf   = conf
            best_res_action = action

    _RESEARCH_THRESHOLD = 0.80

    if best_res_conf >= _RESEARCH_THRESHOLD:
        return IntentResult(
            agent="research",
            action=best_res_action,
            payload="",
            confidence=best_res_conf,
        )
    # ── Integration rules (4ª prioridade: briefing, clima, notícias, agenda) ─
    best_int_conf   = 0.0
    best_int_action = ""

    for triggers, action, base_conf in _INTEGRATION_RULES:
        hits = sum(1 for t in triggers if t in norm)
        if hits == 0:
            continue
        conf = min(base_conf + (hits - 1) * 0.02, 0.99)
        if conf > best_int_conf:
            best_int_conf   = conf
            best_int_action = action

    _INTEGRATION_THRESHOLD = 0.60

    if best_int_conf >= _INTEGRATION_THRESHOLD:
        return IntentResult(
            agent="integration",
            action=best_int_action,
            payload="",
            confidence=best_int_conf,
        )
    # ── System rules ─────────────────────────────────────────────────
    best_conf  = 0.0
    best_action = ""

    for triggers, action, base_conf in _SYSTEM_RULES:
        hits = sum(1 for t in triggers if t in norm)
        if hits == 0:
            continue
        # Confiança cresce com o número de triggers correspondidos
        conf = min(base_conf + (hits - 1) * 0.04, 0.99)
        if conf > best_conf:
            best_conf   = conf
            best_action = action

    # Soft triggers elevam ligeiramente se nenhuma regra forte bateu
    if best_conf == 0.0:
        soft_hits = sum(1 for t in _SYSTEM_SOFT_TRIGGERS if t in norm)
        if soft_hits >= 2:
            best_conf = 0.45  # abaixo do threshold → ainda vai para general

    # Threshold de decisão
    _SYSTEM_THRESHOLD = 0.60

    if best_conf < _SYSTEM_THRESHOLD:
        return IntentResult(agent="general", confidence=1.0 - best_conf)

    # Extrai payload conforme a ação
    payload = ""
    if best_action == "open_app":
        payload = _extract_app_name(message, norm)
    elif best_action in ("create_folder", "list_folder"):
        payload = _extract_folder_name(message, norm)
    # system_info não precisa de payload

    return IntentResult(
        agent="system",
        action=best_action,
        payload=payload,
        confidence=best_conf,
    )
