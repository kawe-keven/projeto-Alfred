"""Referências oficiais para adaptar projetos sem declarar conformidade.

O gerador cita nomes e links oficiais, sem inventar cláusulas. Como edições e
vigências mudam, cada documento pede conferência da edição aplicável na fonte.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class Norma:
    identificador: str
    titulo: str
    uso: str
    fonte: str
    categoria: str = "norma"

    def como_dict(self) -> dict[str, str]:
        return {
            "identificador": self.identificador,
            "titulo": self.titulo,
            "uso": self.uso,
            "fonte": self.fonte,
            "categoria": self.categoria,
        }


_COMUNS = (
    Norma("ISO 21500:2021", "Gestão de projetos, programas e portfólios — contexto e conceitos", "Use como vocabulário e contexto; aplique só práticas proporcionais ao tamanho do projeto.", "https://www.iso.org/standard/75704.html"),
    Norma("ISO 21502:2020", "Orientações sobre gestão de projetos", "Organize início, planejamento, execução, controle e encerramento em escala leve; conferir revisão/edição vigente.", "https://www.iso.org/standard/74947.html"),
    Norma("ISO 31000:2018", "Gestão de riscos — diretrizes", "Identifique risco, probabilidade, impacto, tratamento e responsável, sem criar falsa precisão.", "https://www.iso.org/standard/65694.html"),
    Norma("PMBOK / PRINCE2 / Scrum / Kanban", "Referências de gestão e métodos de trabalho", "Escolha práticas compatíveis com equipe e recursos; são referências/metodologias, não normas legais.", "https://www.pmi.org/pmbok-guide-standards/foundational/pmbok" , "metodologia"),
)

_DIGITAL = (
    Norma("ISO/IEC/IEEE 12207:2026", "Processos do ciclo de vida de software", "Adapte requisitos, construção, operação, manutenção e retirada ao escopo; conferir a edição oficial.", "https://www.iso.org/standard/90219.html"),
    Norma("ISO/IEC 25010:2023", "Modelo de qualidade de produto de software", "Selecione características mensuráveis que importam ao usuário, como segurança, confiabilidade e usabilidade.", "https://www.iso.org/standard/78176.html"),
    Norma("ISO/IEC/IEEE 29148:2018", "Engenharia de requisitos", "Torne requisitos verificáveis e associe critérios de aceitação; verificar edição vigente.", "https://www.iso.org/standard/72089.html"),
    Norma("OWASP ASVS 5.0.0", "Application Security Verification Standard", "Use como lista verificável de segurança para aplicações web; selecione controles pelo risco e versão citada.", "https://asvs.owasp.org/"),
    Norma("NIST SP 800-218 v1.1 (SSDF)", "Secure Software Development Framework", "Integre práticas de desenvolvimento seguro ao fluxo de trabalho; a versão 1.2 está em rascunho e não deve ser tratada como final.", "https://csrc.nist.gov/pubs/sp/800/218/final"),
    Norma("LGPD — Lei 13.709/2018", "Lei Geral de Proteção de Dados Pessoais", "Se houver dados pessoais, documente finalidade, minimização, acesso, retenção e direitos; confirmar obrigações aplicáveis.", "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm", "lei"),
)

_FISICO = (
    Norma("ISO 9001:2026", "Sistemas de gestão da qualidade — requisitos", "Use princípios de controle e melhoria proporcionais; não alegue certificação nem conformidade. Conferir transição de edição.", "https://www.iso.org/standard/9001"),
    Norma("ISO 45001:2018", "Gestão de saúde e segurança ocupacional", "Considere perigos, controles, treinamento e resposta a incidentes; não substitui análise profissional/local.", "https://www.iso.org/standard/63787.html"),
    Norma("Série ISO 128", "Documentação técnica de produto — representação", "Use convenções de desenho técnico apropriadas; confirme partes e edição aplicáveis.", "https://www.iso.org/standard/65296.html"),
    Norma("ISO 7200", "Documentação técnica de produto — campos de legenda", "Consulte para organização de campos de identificação em desenhos, quando aplicável.", "https://www.iso.org/search.html?q=ISO%207200"),
)

_ELETRICA = (
    Norma("IEC 60364 / ABNT NBR 5410", "Instalações elétricas de baixa tensão", "Aplicar somente se houver instalação elétrica pertinente; verificar edição ABNT/IEC, escopo, dimensionamento e profissional habilitado.", "https://www.abntcatalogo.com.br/"),
    Norma("NR-10", "Segurança em instalações e serviços em eletricidade", "Verificar texto e vigência no Brasil; a publicação informa alteração com vigência futura em 2027.", "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/comissao-tripartite-partitaria-permanente/normas-regulamentadora/normas-regulamentadoras-vigentes/norma-regulamentadora-no-10-nr-10", "regulamento brasileiro"),
)

_IOT = (
    Norma("IEC 61010-1", "Segurança de equipamentos elétricos de medição, controle e laboratório", "Verificar se o equipamento e o ambiente estão no escopo antes de usar como referência.", "https://webstore.iec.ch/en/publication/4279"),
    Norma("ETSI EN 303 645", "Requisitos de base de cibersegurança para IoT de consumo", "Use apenas quando o produto se enquadrar em IoT de consumo; confirmar edição oficial atual.", "https://www.etsi.org/deliver/etsi_en/303600_303699/303645/"),
)


def _normalizar(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in valor if not unicodedata.combining(c))


def normas_para(tipo: str, descricao: str) -> list[dict[str, str]]:
    """Seleciona referências aplicáveis sem presumir que todas são obrigatórias."""
    if tipo not in {"digital", "fisico", "hibrido"}:
        raise ValueError("Tipo de projeto inválido")
    texto = _normalizar(descricao)
    selecionadas = list(_COMUNS)
    if tipo in {"digital", "hibrido"}:
        selecionadas.extend(_DIGITAL)
    if tipo in {"fisico", "hibrido"}:
        selecionadas.extend(_FISICO)
    if re.search(r"\b(?:eletric|energia|rede|tomada|alta tensao|circuito)\w*\b", texto):
        selecionadas.extend(_ELETRICA)
    if re.search(r"\b(?:iot|esp32|arduino|sensor|internet das coisas|laboratorio|medicao)\w*\b", texto):
        selecionadas.extend(_IOT)
    if re.search(r"\b(?:pessoa|usuario|cliente|paciente|aluno|funcionario|dado pessoal|cadastro)\w*\b", texto):
        if tipo == "fisico":
            selecionadas.append(_DIGITAL[-1])
    unicas: dict[str, Norma] = {}
    for norma in selecionadas:
        unicas.setdefault(norma.identificador, norma)
    return [norma.como_dict() for norma in unicas.values()]

