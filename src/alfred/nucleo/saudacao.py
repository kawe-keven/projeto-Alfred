"""Saudação inicial do Alfred conforme o horário local."""

from __future__ import annotations

from datetime import datetime


def saudacao_por_horario(agora: datetime | None = None) -> str:
    """Retorna uma saudação curta usando a hora local da máquina."""
    hora = (agora or datetime.now().astimezone()).hour
    if 5 <= hora < 12:
        return "Bom dia."
    if 12 <= hora < 18:
        return "Boa tarde."
    return "Boa noite."
