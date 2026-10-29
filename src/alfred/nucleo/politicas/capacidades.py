"""Manifesto de capacidades derivado da configuração ativa do agente."""

from __future__ import annotations

from urllib.parse import urlparse

from alfred.ferramentas.registro import RegistroDeFerramentas


def montar_manifesto_capacidades(
    registro: RegistroDeFerramentas,
    *,
    modelo: str | None = None,
    url_base: str | None = None,
) -> str:
    """Descreve somente ferramentas registradas e o provedor configurado."""
    linhas = [
        "Capacidades desta sessão (geradas pelo código; correspondem às ferramentas disponíveis):"
    ]
    if modelo:
        linhas.append(f"- Modelo configurado: {modelo}.")
    if url_base:
        host = (urlparse(url_base).hostname or "").casefold()
        local = host in {"localhost", "127.0.0.1", "::1"}
        linhas.append(
            "- Provedor configurado em endereço local."
            if local
            else "- Provedor configurado em endpoint externo; isso não confirma acesso à internet."
        )
    else:
        linhas.append("- O endereço do provedor não foi informado ao manifesto.")
    ferramentas = registro.listar()
    nomes = {f.nome for f in ferramentas}
    if not ferramentas:
        linhas.append("- Nenhuma ferramenta está disponível nesta sessão.")
    else:
        for ferramenta in ferramentas:
            modo = "simulação" if ferramenta.simulada else "execução local"
            # A descrição completa já vai no esquema enviado pela API de tools.
            # Repeti-la aqui aumenta o prompt em toda chamada sem acrescentar
            # informação; o manifesto só precisa esclarecer disponibilidade e modo.
            linhas.append(f"- {ferramenta.nome} ({modo}).")
    if not {"pesquisar_web", "buscar_web", "consultar_web", "buscar_na_internet"}.intersection(nomes):
        linhas.append("- Nenhuma ferramenta de pesquisa externa está registrada nesta sessão.")
    linhas.append(
        "Relate somente capacidades acima ou resultados confirmados por ferramenta. "
        "Uma capacidade simulada nunca prova que a ação aconteceu no mundo real."
    )
    return "\n".join(linhas)
