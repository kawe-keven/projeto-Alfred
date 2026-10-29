"""Painel visual local para selecionar, pré-escutar e salvar a voz do Alfred."""

from __future__ import annotations

import http.client
import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

import yaml

from alfred.configuracao.configuracao import RAIZ_PROJETO


CAMINHO_CONFIG = RAIZ_PROJETO / "config.yaml"
CAMINHO_PREFERENCIAS = RAIZ_PROJETO / "dados" / "perfil" / "voz_alfred.json"
FRASE_PREVIA = (
    "Boa tarde. Esta é a voz configurada do Alfred. "
    "Back end, front end e framework são pronunciados em inglês."
)
DESCRITORES_OMNIVOICE = {
    "american accent", "australian accent", "british accent", "canadian accent",
    "child", "chinese accent", "elderly", "female", "high pitch", "indian accent",
    "japanese accent", "korean accent", "low pitch", "male", "middle-aged",
    "moderate pitch", "portuguese accent", "russian accent", "teenager",
    "very high pitch", "very low pitch", "whisper", "young adult",
}


def _ler_configuracao() -> tuple[dict, dict]:
    try:
        with CAMINHO_CONFIG.open("r", encoding="utf-8") as arquivo:
            documento = yaml.safe_load(arquivo) or {}
    except (OSError, yaml.YAMLError):
        raise RuntimeError("Não consegui ler as configurações do Alfred.") from None
    tts = documento.get("tts") if isinstance(documento, dict) else None
    if not isinstance(tts, dict):
        raise RuntimeError("A seção de voz não está configurada no Alfred.")
    preferencias = dict(tts)
    if CAMINHO_PREFERENCIAS.is_file():
        try:
            with CAMINHO_PREFERENCIAS.open("r", encoding="utf-8") as arquivo:
                salvas = json.load(arquivo)
        except (OSError, json.JSONDecodeError):
            raise RuntimeError("As configurações salvas da voz não puderam ser lidas.") from None
        if isinstance(salvas, dict):
            preferencias.update(salvas)
    return tts, preferencias


class PainelVoz:
    def __init__(self, janela: tk.Tk) -> None:
        self.janela = janela
        self.tts_config, preferencias = _ler_configuracao()
        self.base_url = str(self.tts_config.get("url", "http://127.0.0.1:3900/v1")).rstrip("/")
        self.modelos: dict[str, tuple[str, bool]] = {}
        self.vozes: dict[str, str] = {}
        self.perfis: dict[str, dict] = {}
        self.catalogo_carregado = False
        self._valores_modelo = str(preferencias.get("model", self.tts_config.get("model", "omnivoice")))
        self._valores_voz = str(preferencias.get("voice_id", self.tts_config.get("voice_id", "demo0001")))
        self.modelo_var = tk.StringVar(value=self._valores_modelo)
        self.voz_var = tk.StringVar(value=self._valores_voz)
        self.velocidade_var = tk.DoubleVar(value=float(preferencias.get("speed", self.tts_config.get("speed", 1.0))))
        self.seed_var = tk.StringVar(value=str(preferencias.get("seed", self.tts_config.get("seed", 42))))
        self.status_var = tk.StringVar(value="Conectando ao VoiceStudio local…")
        self._montar_interface(str(preferencias.get("style", self.tts_config.get("style", ""))))
        self.janela.after(100, self._atualizar_listas)

    def _montar_interface(self, estilo: str) -> None:
        self.janela.title("Voz do Alfred")
        self.janela.geometry("700x660")
        self.janela.minsize(610, 580)
        self.janela.columnconfigure(0, weight=1)
        self.janela.rowconfigure(1, weight=1)
        estilo_ttk = ttk.Style(self.janela)
        if "vista" in estilo_ttk.theme_names():
            estilo_ttk.theme_use("vista")

        topo = ttk.Frame(self.janela, padding=(24, 22, 24, 10))
        topo.grid(row=0, column=0, sticky="ew")
        topo.columnconfigure(0, weight=1)
        ttk.Label(topo, text="Voz do Alfred", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            topo,
            text="Escolha um perfil fixo, ajuste o ritmo e escute uma prévia antes de salvar.",
            wraplength=630,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        corpo = ttk.Frame(self.janela, padding=(24, 10, 24, 10))
        corpo.grid(row=1, column=0, sticky="nsew")
        corpo.columnconfigure(0, weight=1)
        corpo.rowconfigure(1, weight=1)

        selecao = ttk.LabelFrame(corpo, text="Identidade da voz", padding=14)
        selecao.grid(row=0, column=0, sticky="ew")
        selecao.columnconfigure(1, weight=1)
        ttk.Label(selecao, text="Motor de fala").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self.modelo_combo = ttk.Combobox(selecao, textvariable=self.modelo_var, state="readonly")
        self.modelo_combo.grid(row=0, column=1, sticky="ew", pady=6)
        self.modelo_combo.bind("<<ComboboxSelected>>", self._mostrar_aviso_modelo)
        ttk.Label(selecao, text="Perfil de voz").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.voz_combo = ttk.Combobox(selecao, textvariable=self.voz_var, state="readonly")
        self.voz_combo.grid(row=1, column=1, sticky="ew", pady=6)
        self.identidade_info = ttk.Label(
            selecao,
            text="Escolha um perfil dedicado de voz. Aliases acompanham o motor ativo e podem trocar de timbre.",
            wraplength=570,
        )
        self.identidade_info.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.voz_combo.bind("<<ComboboxSelected>>", self._mostrar_aviso_voz)

        ajustes = ttk.LabelFrame(corpo, text="Ajustes de fala", padding=14)
        ajustes.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        ajustes.columnconfigure(1, weight=1)
        ttk.Label(ajustes, text="Velocidade").grid(row=0, column=0, sticky="w", padx=(0, 12))
        velocidade = ttk.Scale(ajustes, from_=0.7, to=1.3, variable=self.velocidade_var, orient="horizontal")
        velocidade.grid(row=0, column=1, sticky="ew")
        self.velocidade_texto = ttk.Label(ajustes, text="1,00×", width=7, anchor="e")
        self.velocidade_texto.grid(row=0, column=2, padx=(8, 0))
        velocidade.configure(command=self._atualizar_velocidade)
        ttk.Label(ajustes, text="Seed fixa da voz").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(12, 8))
        ttk.Spinbox(ajustes, from_=0, to=999999999, textvariable=self.seed_var, width=12).grid(
            row=1, column=1, sticky="w", pady=(12, 8)
        )
        ttk.Label(ajustes, text="Características da voz (marcadores em inglês)").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(10, 6)
        )
        self.estilo_texto = tk.Text(ajustes, height=2, wrap="word", font=("Segoe UI", 10), undo=True)
        self.estilo_texto.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.estilo_texto.insert("1.0", estilo)
        ajustes.rowconfigure(3, weight=1)
        ttk.Label(
            ajustes,
            text="OmniVoice aceita marcadores como ‘male, low pitch, portuguese accent’, não frases livres. O perfil selecionado já define essas características.",
            wraplength=580,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        rodape = ttk.Frame(self.janela, padding=(24, 10, 24, 20))
        rodape.grid(row=2, column=0, sticky="ew")
        rodape.columnconfigure(0, weight=1)
        ttk.Label(rodape, textvariable=self.status_var, wraplength=420).grid(row=0, column=0, sticky="w")
        botoes = ttk.Frame(rodape)
        botoes.grid(row=0, column=1, sticky="e")
        self.previa_botao = ttk.Button(botoes, text="Ouvir prévia", command=self._ouvir_previa)
        self.previa_botao.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(botoes, text="Salvar voz", command=self._salvar).grid(row=0, column=1)
        self._atualizar_velocidade(self.velocidade_var.get())

    def _conexao(self, timeout: float = 5.0):
        endereco = urlsplit(self.base_url)
        if endereco.scheme not in {"http", "https"} or endereco.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("O VoiceStudio precisa estar configurado em um endereço local.")
        porta = endereco.port or (443 if endereco.scheme == "https" else 80)
        classe = http.client.HTTPSConnection if endereco.scheme == "https" else http.client.HTTPConnection
        return classe(endereco.hostname, porta, timeout=timeout), endereco.path.rstrip("/")

    def _get_json(self, rota: str, *, raiz: bool = False):
        conexao, base = self._conexao()
        if raiz and base.endswith("/v1"):
            base = base[:-3]
        try:
            conexao.request("GET", f"{base}/{rota.lstrip('/')}", headers={"Accept": "application/json"})
            resposta = conexao.getresponse()
            corpo = resposta.read(1_000_000)
            if resposta.status != 200:
                raise RuntimeError(f"VoiceStudio respondeu com status {resposta.status}.")
            return json.loads(corpo)
        finally:
            conexao.close()

    def _atualizar_listas(self) -> None:
        threading.Thread(target=self._carregar_listas, daemon=True).start()

    def _carregar_listas(self) -> None:
        try:
            modelos_doc = self._get_json("models")
            vozes_doc = self._get_json("audio/voices")
            try:
                perfis_doc = self._get_json("profiles", raiz=True)
            except Exception:
                perfis_doc = []
            perfis = {
                str(item.get("id", "")): item
                for item in perfis_doc
                if isinstance(item, dict) and item.get("id")
            } if isinstance(perfis_doc, list) else {}
            engines = {
                item.get("id"): item
                for item in vozes_doc.get("engines", [])
                if isinstance(item, dict)
            }
            modelos: dict[str, tuple[str, bool]] = {}
            for item in modelos_doc.get("data", []):
                info = item.get("voicestudio", {}) if isinstance(item, dict) else {}
                if info.get("kind") != "tts":
                    continue
                alias = bool(info.get("alias_for_active_engine"))
                if alias:
                    continue
                if not alias and not engines.get(item.get("id"), {}).get("available", False):
                    continue
                identificador = str(item.get("id", "")).strip()
                if not identificador:
                    continue
                descricao = "alias do motor ativo" if alias else "motor fixo"
                modelos[f"{identificador} · {descricao}"] = (identificador, alias)
            vozes: dict[str, str] = {}
            itens_voz = [item for item in vozes_doc.get("voices", []) if isinstance(item, dict)]
            itens_voz.sort(key=lambda item: (
                item.get("type") != "profile",
                item.get("name", "").casefold() != "alfred",
                item.get("name", "").casefold(),
            ))
            for item in itens_voz:
                identificador = str(item.get("voice_id", "")).strip()
                nome = str(item.get("name", identificador)).strip()
                if not identificador:
                    continue
                tipo = str(item.get("type", ""))
                if tipo != "profile":
                    continue
                idioma = str(item.get("language", "")).strip()
                detalhe = f" · {idioma}" if idioma else ""
                perfil = perfis.get(identificador, {})
                if perfil.get("is_demo"):
                    classificacao = "voz demo integrada ao VoiceStudio"
                else:
                    classificacao = f"perfil pessoal · {perfil.get('kind', 'voz')}" if perfil else "perfil de voz"
                rotulo = f"{nome}{detalhe} · {classificacao} [{identificador}]"
                vozes[rotulo] = identificador
            self.janela.after(0, lambda: self._aplicar_listas(modelos, vozes, perfis))
        except Exception as erro:
            mensagem = str(erro)
            self.janela.after(0, lambda mensagem=mensagem: self.status_var.set(
                f"VoiceStudio não está disponível agora. Você ainda pode editar e salvar a voz. {mensagem}"
            ))

    def _aplicar_listas(self, modelos: dict[str, tuple[str, bool]], vozes: dict[str, str], perfis: dict[str, dict]) -> None:
        self.modelos, self.vozes, self.perfis = modelos, vozes, perfis
        self.catalogo_carregado = True
        self.modelo_combo["values"] = tuple(modelos)
        self.voz_combo["values"] = tuple(vozes)
        self._selecionar_item(self.modelo_combo, modelos, self._valores_modelo, lambda item: item[0])
        self._selecionar_item(self.voz_combo, vozes, self._valores_voz, lambda item: item)
        self.status_var.set(f"VoiceStudio conectado · {len(vozes)} perfis fixos disponíveis. Escolha um perfil e escute a prévia.")
        self._mostrar_aviso_modelo()
        self._mostrar_aviso_voz()

    @staticmethod
    def _selecionar_item(combo: ttk.Combobox, opcoes: dict, identificador: str, obter_id) -> None:
        for rotulo, item in opcoes.items():
            if obter_id(item) == identificador:
                combo.set(rotulo)
                return
        combo.set(identificador)

    def _id_modelo(self) -> str:
        selecionado = self.modelo_combo.get()
        return self.modelos.get(selecionado, (selecionado.split(" ·", 1)[0].strip(), False))[0]

    def _id_voz(self) -> str:
        selecionado = self.voz_combo.get()
        return self.vozes.get(selecionado, selecionado.split(" [", 1)[-1].rstrip("]"))

    def _mostrar_aviso_modelo(self, _evento=None) -> None:
        info = self.modelos.get(self.modelo_combo.get())
        if info and info[1]:
            self.identidade_info.configure(
                text="Este modelo acompanha o motor ativo no VoiceStudio. Selecione um motor fixo para evitar mudanças de timbre."
            )
        else:
            self.identidade_info.configure(
                text="Motor fixo selecionado. Escolha um perfil dedicado para manter a mesma identidade de voz."
            )

    def _mostrar_aviso_voz(self, _evento=None) -> None:
        selecionado = self.voz_combo.get()
        perfil = self.perfis.get(self._id_voz(), {})
        if perfil.get("is_demo"):
            self.identidade_info.configure(
                text="Esta é a voz demo original do VoiceStudio, não um perfil pessoal. Selecione seu perfil masculino para usar sua própria identidade de voz."
            )
        elif perfil and perfil.get("kind") == "design":
            self.identidade_info.configure(
                text="Perfil pessoal criado por design de voz. O cadastro local descreve atributos da voz; ele não está marcado como clonagem de uma gravação."
            )
        elif selecionado and self.catalogo_carregado:
            self.identidade_info.configure(
                text=f"Perfil fixo selecionado ({self._id_voz()}). Mantenha este perfil e o motor para preservar a mesma voz nas respostas."
            )

    def _atualizar_velocidade(self, valor) -> None:
        self.velocidade_texto.configure(text=f"{float(valor):.2f}".replace(".", ",") + "×")

    def _valores_atuais(self) -> dict:
        try:
            velocidade = float(self.velocidade_var.get())
            seed = int(self.seed_var.get())
        except (ValueError, tk.TclError):
            raise ValueError("Confira a velocidade e o valor de variação.") from None
        if not 0.25 <= velocidade <= 4 or seed < 0:
            raise ValueError("A velocidade precisa ficar entre 0,25 e 4 e a variação não pode ser negativa.")
        modelo, voz = self._id_modelo(), self._id_voz()
        if not modelo or not voz:
            raise ValueError("Escolha um motor e um perfil de voz.")
        if self.catalogo_carregado:
            if self.modelo_combo.get() not in self.modelos or self.modelos[self.modelo_combo.get()][1]:
                raise ValueError("Escolha um motor fixo disponível; aliases podem trocar de timbre.")
            if self.voz_combo.get() not in self.vozes:
                raise ValueError("Escolha um perfil dedicado disponível para manter a identidade da voz.")
        estilo = self.estilo_texto.get("1.0", "end-1c").strip()
        if modelo == "omnivoice" and estilo:
            marcadores = {item.strip().casefold() for item in estilo.split(",") if item.strip()}
            if marcadores - DESCRITORES_OMNIVOICE:
                raise ValueError(
                    "OmniVoice aceita apenas marcadores específicos em inglês, separados por vírgula. "
                    "Exemplo: male, low pitch, portuguese accent."
                )
        return {
            "model": modelo,
            "voice_id": voz,
            "speed": velocidade,
            "seed": seed,
            "style": estilo,
        }

    def _salvar(self) -> None:
        try:
            preferencias = self._valores_atuais()
            CAMINHO_PREFERENCIAS.parent.mkdir(parents=True, exist_ok=True)
            temporario = CAMINHO_PREFERENCIAS.with_suffix(".tmp")
            temporario.write_text(
                json.dumps(preferencias, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporario.replace(CAMINHO_PREFERENCIAS)
        except (OSError, ValueError) as erro:
            messagebox.showerror("Não foi possível salvar", str(erro), parent=self.janela)
            return
        self.status_var.set("Voz salva. Feche e reabra o Alfred para aplicar a configuração.")
        messagebox.showinfo(
            "Voz salva",
            "A voz foi salva. Feche e reabra o Alfred para usar o perfil selecionado.",
            parent=self.janela,
        )

    def _ouvir_previa(self) -> None:
        try:
            preferencias = self._valores_atuais()
        except ValueError as erro:
            messagebox.showerror("Ajuste os campos", str(erro), parent=self.janela)
            return
        self.previa_botao.configure(state="disabled")
        self.status_var.set("Gerando a prévia local…")
        threading.Thread(target=self._sintetizar_previa, args=(preferencias,), daemon=True).start()

    def _sintetizar_previa(self, preferencias: dict) -> None:
        try:
            conexao, base = self._conexao(timeout=60.0)
            corpo = json.dumps({
                "model": preferencias["model"],
                "voice": preferencias["voice_id"],
                "input": FRASE_PREVIA,
                "response_format": "pcm",
                "language": "pt",
                "speed": preferencias["speed"],
                "seed": preferencias["seed"],
                **({"instruct": preferencias["style"]} if preferencias["style"] else {}),
            }, ensure_ascii=False).encode("utf-8")
            try:
                conexao.request(
                    "POST", f"{base}/audio/speech", body=corpo,
                    headers={"Content-Type": "application/json", "Accept": "audio/pcm"},
                )
                resposta = conexao.getresponse()
                audio = resposta.read(20_000_000)
                if resposta.status != 200:
                    raise RuntimeError(f"VoiceStudio respondeu com status {resposta.status}.")
            finally:
                conexao.close()
            if not audio or len(audio) % 2:
                raise RuntimeError("VoiceStudio retornou uma prévia de áudio inválida.")
            import numpy as np
            import sounddevice as sd
            amostras = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
            sd.play(amostras, samplerate=24000, blocking=True)
            self.janela.after(0, lambda: self.status_var.set("Prévia concluída."))
        except Exception as erro:
            mensagem = str(erro)
            self.janela.after(0, lambda mensagem=mensagem: self.status_var.set(f"Não foi possível reproduzir a prévia: {mensagem}"))
        finally:
            self.janela.after(0, lambda: self.previa_botao.configure(state="normal"))


def main() -> int:
    janela = tk.Tk()
    try:
        PainelVoz(janela)
    except RuntimeError as erro:
        messagebox.showerror("Voz do Alfred", str(erro), parent=janela)
        janela.destroy()
        return 1
    janela.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
