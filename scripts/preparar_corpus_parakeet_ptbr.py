"""Converte pares WebM/TXT em WAV e manifests NeMo com validação separada."""

from __future__ import annotations

import argparse
import json
import random
import wave
from collections import defaultdict
from pathlib import Path, PurePosixPath

import av
import numpy as np


def caminho_consumido_pelo_nemo(path: Path) -> str:
    """Em Windows, grava o caminho padrão montado pelo WSL; em Linux, o nativo."""
    absoluto = path.resolve()
    if absoluto.drive:
        unidade = absoluto.drive[0].lower()
        partes = absoluto.parts[1:]
        return str(PurePosixPath("/mnt", unidade, *partes))
    return absoluto.as_posix()


def converter(caminho: Path, destino: Path) -> float:
    conteiner = av.open(str(caminho))
    try:
        fluxo = conteiner.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        blocos: list[np.ndarray] = []
        for quadro in conteiner.decode(audio=fluxo.index):
            convertidos = resampler.resample(quadro)
            if convertidos is None:
                continue
            if not isinstance(convertidos, list):
                convertidos = [convertidos]
            blocos.extend(item.to_ndarray().reshape(-1) for item in convertidos)
        finais = resampler.resample(None)
        if finais:
            if not isinstance(finais, list):
                finais = [finais]
            blocos.extend(item.to_ndarray().reshape(-1) for item in finais)
    finally:
        conteiner.close()
    if not blocos:
        raise ValueError("nenhum quadro de áudio")
    audio = np.concatenate(blocos).astype(np.int16, copy=False)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(audio.tobytes())
    return len(audio) / 16000


def preparar(origem: Path, saida: Path, fracao_validacao: float, semente: int) -> None:
    arquivos = sorted(origem.rglob("*.webm"))
    if not arquivos:
        raise SystemExit(f"Nenhum WebM encontrado em {origem}")
    if saida.exists() and any(saida.iterdir()):
        raise SystemExit(f"A pasta de saída já contém arquivos: {saida}")

    agrupados: dict[Path, list[Path]] = defaultdict(list)
    for audio in arquivos:
        agrupados[audio.parent].append(audio)
    rng = random.Random(semente)
    validacao: set[Path] = set()
    for grupo in agrupados.values():
        embaralhados = grupo.copy()
        rng.shuffle(embaralhados)
        quantidade = max(1, round(len(grupo) * fracao_validacao))
        validacao.update(embaralhados[:quantidade])

    manifests = {"treino": [], "validacao": []}
    erros: list[dict[str, str]] = []
    for indice, audio in enumerate(arquivos, 1):
        referencia_path = audio.with_suffix(".txt")
        try:
            texto = referencia_path.read_text(encoding="utf-8-sig").strip()
            if not texto:
                raise ValueError("transcrição vazia")
            destino = saida / "wav" / audio.parent.name / f"{audio.stem}.wav"
            duracao = converter(audio, destino)
            conjunto = "validacao" if audio in validacao else "treino"
            manifests[conjunto].append({
                "audio_filepath": caminho_consumido_pelo_nemo(destino),
                "duration": round(duracao, 4),
                "text": texto,
            })
        except Exception as erro:
            erros.append({"arquivo": audio.relative_to(origem).as_posix(), "erro": type(erro).__name__})
        if indice % 100 == 0 or indice == len(arquivos):
            print(f"Preparados {indice}/{len(arquivos)} áudios", flush=True)

    saida.mkdir(parents=True, exist_ok=True)
    for nome, linhas in manifests.items():
        caminho = saida / f"{nome}.jsonl"
        with caminho.open("w", encoding="utf-8", newline="\n") as arquivo:
            for linha in linhas:
                arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
    (saida / "erros.json").write_text(json.dumps(erros, ensure_ascii=False, indent=2), encoding="utf-8")
    total_segundos = sum(item["duration"] for itens in manifests.values() for item in itens)
    print(
        f"Pronto: {len(manifests['treino'])} treino, {len(manifests['validacao'])} validação, "
        f"{len(erros)} falhas; {total_segundos / 3600:.2f} horas de áudio."
    )
    print(f"Saída: {saida.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", type=Path, default=Path("dados/avaliacao_portugues"))
    parser.add_argument("--saida", type=Path, default=Path("dados/treino_parakeet_ptbr"))
    parser.add_argument("--fracao-validacao", type=float, default=0.1)
    parser.add_argument("--semente", type=int, default=20261025)
    args = parser.parse_args()
    if not 0.05 <= args.fracao_validacao <= 0.3:
        raise SystemExit("A validação deve ficar entre 5% e 30% do conjunto")
    preparar(args.origem, args.saida, args.fracao_validacao, args.semente)


if __name__ == "__main__":
    main()
