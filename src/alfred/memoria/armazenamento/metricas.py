"""Armazenamento de métricas sem conteúdo pessoal."""

from __future__ import annotations

import re
import time
import math
from collections.abc import Callable
from pathlib import Path

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.identificadores import gerar_uuid7
from alfred.seguranca.chaves.derivacao import derivar_subchave


_ROTULO = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")
_MS_POR_DIA = 86_400_000


class ErroMetrica(ValueError):
    """Entrada de métrica inválida sem refletir valores no erro."""


class ArmazenamentoDeMetricas:
    """Persiste latência e uso de recursos em SQLCipher."""

    def __init__(
        self,
        caminho: str | Path,
        chave_mestra: bytes,
        *,
        retencao_dias: int = 90,
        relogio_ms: Callable[[], int] | None = None,
    ) -> None:
        if len(chave_mestra) != 32:
            raise ValueError("A chave-mestra deve conter exatamente 32 bytes")
        if retencao_dias < 1:
            raise ValueError("A retenção deve ser de pelo menos um dia")
        self.caminho = Path(caminho)
        self._chave = derivar_subchave(chave_mestra, "metricas.db")
        self.retencao_dias = retencao_dias
        self._relogio_ms = relogio_ms or (lambda: time.time_ns() // 1_000_000)

    @staticmethod
    def _validar_rotulo(valor: str | None, *, opcional: bool = False) -> None:
        if valor is None and opcional:
            return
        if not isinstance(valor, str) or not _ROTULO.fullmatch(valor):
            raise ErroMetrica("Rótulo de configuração inválido")

    @staticmethod
    def _validar_numero(valor: int | float | None) -> None:
        if valor is None:
            return
        if (
            isinstance(valor, bool)
            or not isinstance(valor, (int, float))
            or not math.isfinite(valor)
            or valor < 0
        ):
            raise ErroMetrica("Métrica numérica inválida")

    @staticmethod
    def _validar_tempo(valor: int) -> None:
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            raise ErroMetrica("Instante de métrica inválido")

    def inserir_latencia_turno(
        self,
        *,
        ts_ms: int,
        interface: str,
        perfil_desempenho: str,
        motor_tts: str | None = None,
        modelo_stt: str | None = None,
        modelo_llm: str | None = None,
        ms_fim_fala_transcricao: int | None = None,
        ms_primeiro_token: int | None = None,
        ms_primeira_frase: int | None = None,
        ms_primeiro_audio: int | None = None,
        ms_total: int | None = None,
        barge_in: bool = False,
        id_metrica: str | None = None,
    ) -> str:
        if interface not in {"cli", "voz"}:
            raise ErroMetrica("Interface de métrica inválida")
        self._validar_tempo(ts_ms)
        for rotulo in (perfil_desempenho,):
            self._validar_rotulo(rotulo)
        for rotulo in (motor_tts, modelo_stt, modelo_llm):
            self._validar_rotulo(rotulo, opcional=True)
        valores_tempo = (
            ms_fim_fala_transcricao,
            ms_primeiro_token,
            ms_primeira_frase,
            ms_primeiro_audio,
            ms_total,
        )
        for valor in valores_tempo:
            self._validar_numero(valor)
        if not isinstance(barge_in, bool):
            raise ErroMetrica("Barge-in deve ser booleano")
        identificador = id_metrica or gerar_uuid7()
        with abrir_conexao(self.caminho, self._chave, finalidade="metricas") as conexao:
            conexao.execute(
                "INSERT INTO latencia_turnos(id, ts_ms, interface, perfil_desempenho, "
                "motor_tts, modelo_stt, modelo_llm, ms_fim_fala_transcricao, "
                "ms_primeiro_token, ms_primeira_frase, ms_primeiro_audio, ms_total, barge_in) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identificador,
                    ts_ms,
                    interface,
                    perfil_desempenho,
                    motor_tts,
                    modelo_stt,
                    modelo_llm,
                    ms_fim_fala_transcricao,
                    ms_primeiro_token,
                    ms_primeira_frase,
                    ms_primeiro_audio,
                    ms_total,
                    int(barge_in),
                ),
            )
            conexao.commit()
        return identificador

    def inserir_uso_recursos(
        self,
        *,
        ts_ms: int,
        componente: str,
        vram_mb: float | None,
        ram_mb: float | None,
        id_metrica: str | None = None,
    ) -> str:
        self._validar_tempo(ts_ms)
        self._validar_rotulo(componente)
        self._validar_numero(vram_mb)
        self._validar_numero(ram_mb)
        identificador = id_metrica or gerar_uuid7()
        with abrir_conexao(self.caminho, self._chave, finalidade="metricas") as conexao:
            conexao.execute(
                "INSERT INTO uso_recursos(id, ts_ms, componente, vram_mb, ram_mb) "
                "VALUES(?, ?, ?, ?, ?)",
                (identificador, ts_ms, componente, vram_mb, ram_mb),
            )
            conexao.commit()
        return identificador

    def inserir_recuperacao_contexto(
        self,
        *,
        ts_ms: int,
        interface: str,
        latencia_ms: int,
        itens: int,
        tokens_estimados: int,
        id_metrica: str | None = None,
    ) -> str:
        """Registra apenas volume e latência da recuperação, sem texto pessoal."""
        if interface not in {"cli", "voz"}:
            raise ErroMetrica("Interface de métrica inválida")
        self._validar_tempo(ts_ms)
        for valor in (latencia_ms, itens, tokens_estimados):
            self._validar_numero(valor)
            if valor is None or not isinstance(valor, int):
                raise ErroMetrica("Métrica inteira inválida")
        identificador = id_metrica or gerar_uuid7()
        with abrir_conexao(self.caminho, self._chave, finalidade="metricas") as conexao:
            conexao.execute(
                "INSERT INTO recuperacao_contexto "
                "(id, ts_ms, interface, latencia_ms, itens, tokens_estimados) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (identificador, ts_ms, interface, latencia_ms, itens, tokens_estimados),
            )
            conexao.commit()
        return identificador

    def limpar_expiradas(self, *, agora_ms: int | None = None) -> dict[str, int]:
        instante = int(self._relogio_ms()) if agora_ms is None else agora_ms
        self._validar_tempo(instante)
        limite = instante - self.retencao_dias * _MS_POR_DIA
        with abrir_conexao(self.caminho, self._chave, finalidade="metricas") as conexao:
            removidas_latencia = conexao.execute(
                "DELETE FROM latencia_turnos WHERE ts_ms < ?", (limite,)
            ).rowcount
            removidas_recursos = conexao.execute(
                "DELETE FROM uso_recursos WHERE ts_ms < ?", (limite,)
            ).rowcount
            removidas_contexto = conexao.execute(
                "DELETE FROM recuperacao_contexto WHERE ts_ms < ?", (limite,)
            ).rowcount
            conexao.commit()
        return {
            "latencia_turnos": int(removidas_latencia),
            "uso_recursos": int(removidas_recursos),
            "recuperacao_contexto": int(removidas_contexto),
        }
