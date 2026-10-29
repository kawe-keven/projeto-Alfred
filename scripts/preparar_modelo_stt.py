"""Baixa o modelo de STT configurado antes de iniciar a conversa por voz."""

from __future__ import annotations

from pathlib import Path

from alfred.configuracao.configuracao import carregar_configuracao


def main() -> int:
    config = carregar_configuracao()
    if config.voz_engine_stt == "parakeet":
        from alfred.adaptadores.voz.stt import preparar_modelo_parakeet
        try:
            caminho = preparar_modelo_parakeet()
        except Exception as erro:
            print(f"Não foi possível preparar o Parakeet: {erro}")
            return 1
        print(f"Parakeet TDT v3 pronto em: {caminho}")
        return 0
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub.errors import IncompleteSnapshotError, LocalEntryNotFoundError
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Instale o extra de voz antes: pip install -e '.[voz]'")
        return 2

    modelo = config.voz_modelo_stt
    repositorio = _MODELS.get(modelo, modelo)
    arquivos = [
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    ]
    print(f"Verificando o cache local de {modelo} ({repositorio}).")
    caminho = None
    try:
        caminho = snapshot_download(repo_id=repositorio, allow_patterns=arquivos, local_files_only=True)
    except (IncompleteSnapshotError, LocalEntryNotFoundError):
        pass

    def pesos_prontos(diretorio: str) -> bool:
        arquivo = Path(diretorio) / "model.bin"
        try:
            return arquivo.is_file() and arquivo.stat().st_size > 0
        except OSError:
            return False

    if caminho and pesos_prontos(caminho):
        print("Modelo já está no cache; não será necessário acessar a rede.")
    else:
        print("Pesos incompletos ou ausentes. Iniciando download; o cache será reutilizado pelo Alfred.")
        try:
            caminho = snapshot_download(repo_id=repositorio, allow_patterns=arquivos)
        except Exception as erro:
            print(f"Não foi possível preparar {modelo}: {erro}")
            print("Confira a conexão com o Hugging Face e execute o comando novamente.")
            return 1
    if not pesos_prontos(caminho):
        print(f"O download de {modelo} ainda não produziu um model.bin válido.")
        return 1
    print(f"Modelo pronto no cache: {caminho}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
