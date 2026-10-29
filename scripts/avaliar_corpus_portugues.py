"""Compara transcricoes de audio WebM com arquivos TXT de referencia."""

from __future__ import annotations

import argparse
import csv
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
import av
import numpy as np

from alfred.adaptadores.voz.stt import TranscritorLocal


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto).casefold()
    texto = "".join(
        caractere if caractere.isalnum() or caractere.isspace() else " "
        for caractere in texto
    )
    return re.sub(r"\s+", " ", texto).strip()


def _distancia(a: list[str], b: list[str]) -> int:
    linha = list(range(len(b) + 1))
    for indice_a, item_a in enumerate(a, 1):
        seguinte = [indice_a]
        for indice_b, item_b in enumerate(b, 1):
            seguinte.append(min(
                seguinte[-1] + 1,
                linha[indice_b] + 1,
                linha[indice_b - 1] + (item_a != item_b),
            ))
        linha = seguinte
    return linha[-1]


def _taxa_erro(referencia: str, transcricao: str, *, caracteres: bool = False) -> float:
    ref, hip = _normalizar(referencia), _normalizar(transcricao)
    unidades_ref = list(ref.replace(" ", "")) if caracteres else ref.split()
    unidades_hip = list(hip.replace(" ", "")) if caracteres else hip.split()
    if not unidades_ref:
        return 0.0 if not unidades_hip else 1.0
    return _distancia(unidades_ref, unidades_hip) / len(unidades_ref)


def _decodificar_webm(caminho: Path) -> np.ndarray:
    conteiner = av.open(str(caminho))
    try:
        fluxo = conteiner.streams.audio[0]
        conversor = av.AudioResampler(format="flt", layout="mono", rate=16000)
        partes: list[np.ndarray] = []
        for quadro in conteiner.decode(audio=fluxo.index):
            convertidos = conversor.resample(quadro)
            if convertidos is None:
                continue
            if not isinstance(convertidos, list):
                convertidos = [convertidos]
            partes.extend(
                item.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                for item in convertidos
            )
        finais = conversor.resample(None)
        if finais:
            if not isinstance(finais, list):
                finais = [finais]
            partes.extend(
                item.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                for item in finais
            )
    finally:
        conteiner.close()
    if not partes:
        raise ValueError("audio sem quadros")
    return np.concatenate(partes)


def avaliar(
    diretorio: Path,
    saida: Path,
    engine: str,
    modelo: str = "base",
    dispositivo: str = "cpu",
    compute_type: str = "int8",
    por_grupo: int | None = None,
) -> int:
    audios = sorted(diretorio.rglob("*.webm"))
    if not audios:
        raise SystemExit(f"Nenhum arquivo .webm encontrado em {diretorio}")
    if por_grupo is not None:
        selecionados: list[Path] = []
        grupos: dict[Path, list[Path]] = defaultdict(list)
        for audio in audios:
            grupos[audio.parent].append(audio)
        for arquivos_grupo in grupos.values():
            total = min(por_grupo, len(arquivos_grupo))
            indices = sorted({round(i * (len(arquivos_grupo) - 1) / max(1, total - 1)) for i in range(total)})
            selecionados.extend(arquivos_grupo[i] for i in indices)
        audios = sorted(selecionados)
    transcritor = TranscritorLocal(
        engine=engine,
        modelo=modelo,
        dispositivo=dispositivo,
        compute_type=compute_type,
    )
    print(f"Carregando o reconhecedor {engine} ({modelo}, {dispositivo})...")
    transcritor.carregar()
    saida.parent.mkdir(parents=True, exist_ok=True)
    totais: dict[str, list[float]] = defaultdict(list)
    erros: list[tuple[str, str]] = []
    inicio = time.perf_counter()

    with saida.open("w", encoding="utf-8-sig", newline="") as arquivo_csv:
        campos = ["arquivo", "grupo", "referencia", "transcricao", "wer", "cer", "correspondencia", "erro"]
        escritor = csv.DictWriter(arquivo_csv, fieldnames=campos)
        escritor.writeheader()
        for indice, audio in enumerate(audios, 1):
            referencia_path = audio.with_suffix(".txt")
            grupo = audio.parent.name
            referencia = ""
            transcricao = ""
            erro = ""
            try:
                if not referencia_path.is_file():
                    raise FileNotFoundError("transcricao de referencia ausente")
                referencia = referencia_path.read_text(encoding="utf-8-sig").strip()
                audio_np = _decodificar_webm(audio)
                transcricao = transcritor.transcrever(audio_np).texto.strip()
                wer = _taxa_erro(referencia, transcricao)
                cer = _taxa_erro(referencia, transcricao, caracteres=True)
                correspondencia = _normalizar(referencia) == _normalizar(transcricao)
                totais[grupo].append(wer)
                totais["__global__"].append(wer)
            except Exception as excecao:
                wer = cer = 1.0
                correspondencia = False
                erro = type(excecao).__name__
                erros.append((audio.relative_to(diretorio).as_posix(), erro))
            escritor.writerow({
                "arquivo": audio.relative_to(diretorio).as_posix(),
                "grupo": grupo,
                "referencia": referencia,
                "transcricao": transcricao,
                "wer": f"{wer:.4f}",
                "cer": f"{cer:.4f}",
                "correspondencia": correspondencia,
                "erro": erro,
            })
            if indice % 10 == 0 or indice == len(audios):
                decorrido = time.perf_counter() - inicio
                print(f"Processados {indice}/{len(audios)} audios ({decorrido:.0f}s).", flush=True)

    print("RESULTADO")
    for grupo, valores in sorted(totais.items()):
        correspondencias = sum(valor == 0 for valor in valores)
        print(
            f"{grupo}: {len(valores)} audios; WER medio {sum(valores) / len(valores):.3f}; "
            f"correspondencia textual completa {correspondencias}/{len(valores)}"
        )
    print(f"Falhas de leitura: {len(erros)}")
    if erros:
        for nome, erro in erros[:20]:
            print(f"Falha {nome}: {erro}")
    print(f"Relatorio detalhado: {saida.resolve()}")
    return 1 if erros else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diretorio", type=Path, default=Path("dados/avaliacao_portugues"))
    parser.add_argument("--saida", type=Path, default=Path("dados/avaliacao_portugues/resultados_parakeet.csv"))
    parser.add_argument("--engine", choices=("parakeet", "faster-whisper"), default="parakeet")
    parser.add_argument("--modelo", default="base", help="modelo faster-whisper (padrão: base)")
    parser.add_argument("--dispositivo", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--compute-type", default="int8", help="por exemplo int8 ou float16")
    parser.add_argument("--por-grupo", type=int, help="avalia uma amostra espaçada de cada subpasta")
    argumentos = parser.parse_args()
    return avaliar(
        argumentos.diretorio,
        argumentos.saida,
        argumentos.engine,
        argumentos.modelo,
        argumentos.dispositivo,
        argumentos.compute_type,
        argumentos.por_grupo,
    )


if __name__ == "__main__":
    raise SystemExit(main())
