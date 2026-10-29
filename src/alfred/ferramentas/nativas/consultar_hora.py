from datetime import datetime


def executar() -> str:
    return f"Hora local: {datetime.now().astimezone().strftime('%H:%M')}"
