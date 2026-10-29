"""Compara VoiceStudio e Piper com frases fictícias, mantendo áudio em memória."""

from __future__ import annotations

import argparse
import ctypes
import http.client
import ipaddress
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


FRASES = (
    "Entendido.",
    "Certo, vou verificar isso agora.",
    "São oito horas e quinze minutos.",
    "O código de confirmação é quatro, dois, oito.",
    "Você quer que eu continue com essa alteração?",
    "Não encontrei uma correspondência segura. Pode esclarecer qual arquivo você quis dizer?",
    "A previsão local está indisponível; posso tentar novamente quando a conexão estiver estável.",
    "O relatório foi preparado. Antes de salvar, confirme o nome e o local que você deseja usar.",
    "Posso abrir a agenda de amanhã? Ainda não recebi confirmação para alterar nenhum compromisso.",
    "A solicitação envolve uma ação sensível. Vou explicar o que será feito, aguardar sua confirmação explícita e só então continuar.",
)
MOTORES_PT_BR = ("omnivoice", "omnivoice-subprocess")
VOZES_BUILTIN = ("alloy", "coral", "nova")


def validar_url(url: str):
    partes = urlsplit(url)
    if (
        partes.scheme not in {"http", "https"}
        or partes.hostname not in {"localhost", "127.0.0.1", "::1"}
        or partes.username is not None
        or partes.password is not None
        or partes.query
        or partes.fragment
    ):
        raise ValueError("A URL deve apontar somente para loopback.")
    porta = partes.port or (443 if partes.scheme == "https" else 80)
    enderecos = socket.getaddrinfo(partes.hostname, porta, type=socket.SOCK_STREAM)
    if not enderecos or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in enderecos):
        raise ValueError("A URL deve resolver somente para loopback.")
    return partes, porta


def caminho_raiz(partes, final: str) -> str:
    prefixo = partes.path.rstrip("/")
    if prefixo.endswith("/v1"):
        prefixo = prefixo[:-3]
    return prefixo + "/" + final.lstrip("/")


class ClienteLocal:
    def __init__(self, url: str, timeout_conexao: float, timeout_leitura: float):
        self.partes, self.porta = validar_url(url)
        self.timeout_conexao = timeout_conexao
        self.timeout_leitura = timeout_leitura
        self.classe = http.client.HTTPSConnection if self.partes.scheme == "https" else http.client.HTTPConnection

    def requisicao(self, metodo: str, caminho: str, corpo: bytes | None = None):
        conexao = self.classe(
            self.partes.hostname, self.porta, timeout=self.timeout_conexao
        )
        try:
            conexao.connect()
            if conexao.sock:
                conexao.sock.settimeout(self.timeout_leitura)
            cabecalhos = {"Accept": "application/json" if metodo == "GET" else "audio/pcm"}
            if corpo is not None:
                cabecalhos["Content-Type"] = "application/json"
            conexao.request(metodo, caminho, body=corpo, headers=cabecalhos)
            resposta = conexao.getresponse()
            return conexao, resposta
        except (OSError, http.client.HTTPException, TimeoutError):
            conexao.close()
            raise RuntimeError("VoiceStudio local indisponível ou tempo esgotado.") from None

    def modelos(self) -> set[str]:
        conexao, resposta = self.requisicao("GET", caminho_raiz(self.partes, "v1/models"))
        try:
            if resposta.status != 200:
                raise RuntimeError("Não foi possível consultar os identificadores de motores locais.")
            dados = json.loads(resposta.read(256_000))
            return {item.get("id", "") for item in dados.get("data", []) if isinstance(item, dict)}
        except (OSError, ValueError, http.client.HTTPException, TimeoutError):
            raise RuntimeError("Resposta malformada ao consultar modelos locais.") from None
        finally:
            conexao.close()

    def sintetizar(self, motor: str, voz: str, texto: str, amostra_audio: bool):
        corpo = json.dumps({
            "model": motor,
            "input": texto,
            "voice": voz,
            "response_format": "pcm",
            "stream_format": "audio",
            "language": "pt",
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        inicio = time.perf_counter()
        conexao, resposta = self.requisicao(
            "POST", caminho_raiz(self.partes, "v1/audio/speech"), corpo
        )
        if resposta.status != 200:
            conexao.close()
            if resposta.status in {301, 302, 303, 307, 308}:
                raise RuntimeError("Redirecionamento recusado.")
            raise RuntimeError(f"VoiceStudio respondeu com status {resposta.status}.")
        tipo = resposta.getheader("Content-Type", "").split(";", 1)[0].lower()
        if tipo not in {"audio/pcm", "application/octet-stream"}:
            conexao.close()
            raise RuntimeError("O VoiceStudio não devolveu PCM.")
        amostras = bytearray()
        primeiro_byte = None
        try:
            while True:
                bloco = resposta.read1(4096)
                if not bloco:
                    break
                if primeiro_byte is None:
                    primeiro_byte = time.perf_counter() - inicio
                amostras.extend(bloco)
        except (OSError, http.client.HTTPException, TimeoutError):
            raise RuntimeError("Tempo esgotado durante a síntese local.") from None
        finally:
            conexao.close()
        decorrido = time.perf_counter() - inicio
        if not amostras or len(amostras) % 2:
            raise RuntimeError("Resposta PCM malformada.")
        duracao = len(amostras) / 2 / 24000
        amostras_imemoria = bytes(amostras)
        if amostra_audio:
            import numpy as np
            import sounddevice as sd
            audio = np.frombuffer(amostras_imemoria, dtype="<i2")
            sd.play(audio, samplerate=24000, blocking=True)
            nota = input("Notas 1-5 (naturalidade, clareza, ritmo, persona), separadas por vírgula: ")
        else:
            nota = ""
        return {
            "primeiro_byte": primeiro_byte,
            "total": decorrido,
            "duracao": duracao,
            "fator": decorrido / duracao if duracao else None,
            "nota": nota,
            "amostra": amostras_imemoria,
        }


class Memoria:
    def __init__(self):
        self.parar = threading.Event()
        self.ram: list[float] = []
        self.vram: list[float] = []
        self._thread = threading.Thread(target=self._medir, daemon=True)

    @staticmethod
    def uso_ram_gb() -> float | None:
        if os.name != "nt":
            return None

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        memoria = MEMORYSTATUSEX()
        memoria.dwLength = ctypes.sizeof(memoria)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memoria)):
            return None
        return (memoria.ullTotalPhys - memoria.ullAvailPhys) / (1024 ** 3)

    @staticmethod
    def uso_vram_gb() -> float | None:
        executavel = shutil.which("nvidia-smi")
        if not executavel:
            return None
        try:
            resultado = subprocess.run(
                [executavel, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=True,
            )
            valores = [float(linha.strip()) / 1024 for linha in resultado.stdout.splitlines() if linha.strip()]
            return sum(valores) if valores else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _medir(self):
        while not self.parar.wait(0.2):
            ram = self.uso_ram_gb()
            vram = self.uso_vram_gb()
            if ram is not None:
                self.ram.append(ram)
            if vram is not None:
                self.vram.append(vram)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self.parar.set()
        self._thread.join(timeout=2)

    def resumo(self):
        return (
            f"RAM total sistema pico={max(self.ram):.2f} GB" if self.ram else "RAM=n/d",
            f"VRAM total GPU pico={max(self.vram):.2f} GB" if self.vram else "VRAM=n/d",
        )


def sintetizar_piper(texto: str, modelo: Path, length_scale: float):
    import numpy as np
    from piper import PiperVoice, SynthesisConfig

    if not modelo.is_file():
        raise RuntimeError("Modelo Piper configurado não encontrado; informe --piper-modelo.")
    inicio_carregamento = time.perf_counter()
    voz = PiperVoice.load(str(modelo))
    carregamento = time.perf_counter() - inicio_carregamento
    config = SynthesisConfig(length_scale=length_scale)
    inicio = time.perf_counter()
    primeiro_byte = None
    blocos = []
    taxa = int(voz.config.sample_rate)
    for bloco in voz.synthesize(texto, syn_config=config):
        if primeiro_byte is None:
            primeiro_byte = time.perf_counter() - inicio
        blocos.append(np.asarray(bloco.audio_float_array, dtype=np.float32))
    audio = np.concatenate(blocos)
    total = time.perf_counter() - inicio
    duracao = len(audio) / taxa
    return {
        "primeiro_byte": primeiro_byte,
        "total": total,
        "duracao": duracao,
        "fator": total / duracao if duracao else None,
        "carregamento": carregamento,
        "audio": audio,
        "taxa": taxa,
    }


def percentil95(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[max(0, min(len(ordenados) - 1, int(len(ordenados) * 0.95 + 0.999999) - 1))]


def resumir_amostras(nome: str, resultados: list[dict], memoria: tuple[str, str]):
    primeiros = [x["primeiro_byte"] for x in resultados if x["primeiro_byte"] is not None]
    fatores = [x["fator"] for x in resultados if x["fator"] is not None]
    if not resultados:
        print(f"{nome}: sem amostras")
        return
    median = lambda xs: statistics.median(xs) if xs else None
    f_ms = lambda x: "n/d" if x is None else f"{x * 1000:.0f} ms"
    f_num = lambda x: "n/d" if x is None else f"{x:.2f}x"
    print(
        f"{nome}: primeiro byte mediana={f_ms(median(primeiros))}, p95={f_ms(percentil95(primeiros))}; "
        f"tempo real mediana={f_num(median(fatores))}; {memoria[0]}; {memoria[1]}"
    )
    notas = [x["nota"] for x in resultados if x.get("nota")]
    if notas:
        print("  notas digitadas: " + " | ".join(notas))


def principal() -> int:
    parser = argparse.ArgumentParser(description="Compara TTS local sem gravar amostras.")
    parser.add_argument("--url", default=os.getenv("ALFRED_VOICESTUDIO_URL", "http://127.0.0.1:3900/v1"))
    parser.add_argument("--timeout-conexao", type=float, default=3.0)
    parser.add_argument("--timeout-leitura", type=float, default=90.0)
    parser.add_argument("--motores", help="IDs já disponíveis, separados por vírgula; nunca instala motores")
    parser.add_argument("--vozes", default=",".join(VOZES_BUILTIN), help="aliases embutidos, nunca lista perfis salvos")
    parser.add_argument("--piper-modelo", type=Path, default=Path(os.getenv("ALFRED_PIPER_MODELO", "dados/modelos/pt_BR-faber-medium.onnx")))
    parser.add_argument("--piper-length-scale", type=float, default=float(os.getenv("ALFRED_PIPER_LENGTH_SCALE", "1.25")))
    parser.add_argument("--avaliar-audio", action="store_true", help="toca cada amostra e pede notas pelo console")
    args = parser.parse_args()
    try:
        cliente = ClienteLocal(args.url, args.timeout_conexao, args.timeout_leitura)
        disponiveis = cliente.modelos()
    except (ValueError, RuntimeError) as erro:
        print(str(erro), file=sys.stderr)
        return 1

    candidatos = [m.strip() for m in args.motores.split(",") if m.strip()] if args.motores else [m for m in MOTORES_PT_BR if m in disponiveis]
    vozes = [v.strip() for v in args.vozes.split(",") if v.strip()]
    candidatos = [m for m in candidatos if m in disponiveis]
    if not candidatos:
        print("Nenhum candidato multilíngue conhecido está disponível; nenhum motor será instalado.")
    resultados_piper = []
    try:
        with Memoria() as memoria:
            carregamento = None
            for texto in FRASES:
                try:
                    amostra = sintetizar_piper(texto, args.piper_modelo, args.piper_length_scale)
                    carregamento = amostra["carregamento"] if carregamento is None else carregamento
                    if args.avaliar_audio:
                        import sounddevice as sd
                        sd.play(amostra["audio"], samplerate=amostra["taxa"], blocking=True)
                        amostra["nota"] = input("Notas 1-5 (naturalidade, clareza, ritmo, persona): ")
                    resultados_piper.append(amostra)
                except (OSError, RuntimeError, ImportError) as erro:
                    print(f"Piper: {erro}")
                    break
            mem = memoria.resumo()
        if carregamento is not None:
            print(f"Piper: carga inicial={carregamento:.2f} s")
        resumir_amostras("Piper pt_BR-faber-medium", resultados_piper, mem)
    except Exception as erro:
        print(f"Piper: medição indisponível ({type(erro).__name__}).")

    for motor in candidatos:
        for voz in vozes:
            resultados = []
            try:
                with Memoria() as memoria:
                    for texto in FRASES:
                        try:
                            resultados.append(cliente.sintetizar(motor, voz, texto, args.avaliar_audio))
                        except RuntimeError as erro:
                            print(f"{motor}/{voz}: síntese não disponível ({str(erro)}).")
                            break
                    mem = memoria.resumo()
                resumir_amostras(f"VoiceStudio {motor}/{voz} pt", resultados, mem)
            except Exception as erro:
                print(f"{motor}/{voz}: medição indisponível ({type(erro).__name__}).")

    print("Recomendação automática: prefira um motor que complete todas as frases pt sem erro e tenha menor fator de tempo real; a nota de naturalidade precisa ser avaliada por você.")
    print("VRAM e RAM são totais do sistema; execute a comparação enquanto os modelos que deseja comparar já estiverem carregados. O script não inicia Alfred/Ollama/Whisper nem grava ou reproduz áudio sem --avaliar-audio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
