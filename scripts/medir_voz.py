"""Benchmark sintético local. Não usa microfone, alto-falante, rede ou transcrições em disco."""

from __future__ import annotations

import argparse
import gc
import math
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


FALAS_FICTICIAS = (
    "Oi, Alfred, vê se a luz da sala ficou acesa.",
    "É, coloca um lembrete para amanhã às nove.",
    "Não, peraí, eu quis dizer na quinta-feira.",
    "Me fala se vai chover no fim de semana.",
    "A reunião mudou para quinze e quarenta e cinco.",
    "Toca uma música tranquila para eu trabalhar.",
    "Quanto fica vinte por cento de desconto em cinquenta reais?",
    "Abre o arquivo, não, melhor não abrir agora.",
    "A Ana chega depois do almoço, acho que lá pelas duas.",
    "Se puder, deixa a luz do quarto mais baixa.",
    "Humm, procura aquela música que toca no filme.",
    "O endereço é exemplo ponto com barra agenda.",
    "Eu falei sala, quer dizer, cozinha.",
    "Pode repetir só a última parte?",
    "Amanhã de manhã eu saio às sete e meia.",
    "Quanto é dois vírgula cinco vezes quatro?",
    "Liga para a Ana, não, deixa para depois.",
    "Confere se o lembrete ficou para a próxima semana.",
    "A temperatura está em vinte e dois graus.",
    "Valeu, era isso mesmo.",
)


def percentil95(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(0.95 * len(ordenados)) - 1)]


def wer(referencia: str, hipotese: str) -> float:
    a = re.sub(r"[^\w]+", " ", referencia.casefold()).split()
    b = re.sub(r"[^\w]+", " ", hipotese.casefold()).split()
    linha = list(range(len(b) + 1))
    for i, palavra_a in enumerate(a, 1):
        proxima = [i]
        for j, palavra_b in enumerate(b, 1):
            proxima.append(min(
                proxima[-1] + 1,
                linha[j] + 1,
                linha[j - 1] + (palavra_a != palavra_b),
            ))
        linha = proxima
    return linha[-1] / max(1, len(a))


def amostrar_vram() -> str:
    try:
        resultado = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "indisponível"
    return resultado.stdout.strip().replace("\n", "; ")


def percentuais(valores: Iterable[float]) -> tuple[float, float, float]:
    lista = list(valores)
    return statistics.median(lista), percentil95(lista), max(lista)


def resample_16k(audio, taxa: int):
    import numpy as np
    if taxa == 16000:
        return np.asarray(audio, dtype=np.float32)
    tamanho = max(1, round(len(audio) * 16000 / taxa))
    eixo_antigo = np.arange(len(audio), dtype=np.float64)
    eixo_novo = np.linspace(0, max(0, len(audio) - 1), tamanho)
    return np.interp(eixo_novo, eixo_antigo, audio).astype(np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--whisper-local",
        required=True,
        help="pasta local de um modelo faster-whisper já baixado; não aceita baixar modelos",
    )
    parser.add_argument(
        "--piper-modelo",
        help="caminho local do Piper; usa ALFRED_PIPER_MODELO se omitido",
    )
    parser.add_argument(
        "--perfis",
        nargs="+",
        choices=("rápido", "equilibrado", "preciso"),
        default=("rápido", "equilibrado", "preciso"),
    )
    args = parser.parse_args()

    modelo_whisper = Path(args.whisper_local).expanduser()
    if not modelo_whisper.is_dir():
        parser.error("--whisper-local precisa apontar para uma pasta de modelo local existente")

    from alfred.adaptadores.voz.stt import TranscritorLocal, normalizar_transcricao_pt_br
    from alfred.adaptadores.voz.texto_voz import normalizar_texto_para_voz
    from alfred.configuracao.configuracao import carregar_configuracao

    config = carregar_configuracao()
    caminho_piper = Path(args.piper_modelo).expanduser() if args.piper_modelo else config.voz_caminho_modelo_voz
    if not caminho_piper.is_file():
        parser.error("O modelo Piper local não foi encontrado.")
    try:
        from piper import PiperVoice
        import numpy as np
    except ImportError:
        print("Instale o extra alfred[voz] no ambiente local.", file=sys.stderr)
        return 2

    print("Benchmark fictício em memória; nenhuma fala será reproduzida.")
    print(f"VRAM antes={amostrar_vram()}")
    voz = PiperVoice.load(str(caminho_piper))
    taxa = int(voz.config.sample_rate)
    audios: list[object] = []
    tempos_tts: list[float] = []
    for frase in FALAS_FICTICIAS:
        inicio = time.perf_counter()
        texto = normalizar_texto_para_voz(frase)
        audio = np.concatenate([
            np.asarray(bloco.audio_float_array, dtype=np.float32)
            for bloco in voz.synthesize(texto)
        ])
        tempos_tts.append(time.perf_counter() - inicio)
        audios.append(resample_16k(audio, taxa))
    del voz
    gc.collect()
    resumo_tts = percentuais(tempos_tts)
    print(f"piper_sintese_mediana_ms={resumo_tts[0]*1000:.0f} p95_ms={resumo_tts[1]*1000:.0f} pior_ms={resumo_tts[2]*1000:.0f}")

    for perfil in args.perfis:
        stt = TranscritorLocal(
            modelo=str(modelo_whisper), dispositivo=config.voz_dispositivo_stt,
            compute_type=config.voz_compute_type, perfil=perfil,
            engine="faster-whisper",
        )
        tempos_stt: list[float] = []
        erros: list[float] = []
        for referencia, audio in zip(FALAS_FICTICIAS, audios):
            inicio = time.perf_counter()
            transcricao = stt.transcrever(audio)
            tempos_stt.append(time.perf_counter() - inicio)
            erros.append(wer(
                normalizar_transcricao_pt_br(referencia),
                normalizar_transcricao_pt_br(transcricao.texto),
            ))
        resumo = percentuais(tempos_stt)
        media_wer = statistics.mean(erros)
        print(
            f"perfil={perfil} dispositivo={stt.dispositivo} compute_type={stt.compute_type} "
            f"beam_size={stt.PERFIS_BEAM_SIZE[perfil]} "
            f"stt_mediana_ms={resumo[0]*1000:.0f} stt_p95_ms={resumo[1]*1000:.0f} "
            f"stt_pior_ms={resumo[2]*1000:.0f} wer={media_wer:.3f} "
            f"vram={amostrar_vram()}"
        )
        stt._modelo = None
        del stt
        gc.collect()

    print("llm_primeiro_token=NA (o benchmark não chama APIs)")
    print("primeira_frase=NA primeiro_audio=NA (nenhum alto-falante foi aberto)")
    print("Observação: Piper sintetiza fala mais fácil de reconhecer que fala real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
