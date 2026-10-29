"""Leitura local e somente de leitura de tiles PMTiles v3 para o painel."""

from __future__ import annotations

import json
import math
import os
import re
import struct
import zlib
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from alfred.configuracao.configuracao import RAIZ_PROJETO

ARQUIVO_BASE = RAIZ_PROJETO / "dados" / "mapa" / "base.pmtiles"
TAMANHO_CABECALHO = 127
LIMITE_DIRETORIO = 8 * 1024 * 1024
LIMITE_TILE = 5 * 1024 * 1024
LIMITE_PROFUNDIDADE = 4
LIMITE_DIRETORIOS = 32
TIPOS_COMPRESSAO = {1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}
NOMES_CAMADAS = {
    "agua": "water",
    "parques": "landuse",
    "ruas": "roads",
    "edificios": "buildings",
}
_INTEIRO = re.compile(r"^(0|[1-9][0-9]*)$")
_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


class ErroMapa(Exception):
    """Falha segura do mapa, sem incluir o caminho ou conteúdo do arquivo."""

    def __init__(self, mensagem: str, status: int = 500) -> None:
        super().__init__(mensagem)
        self.status = status


@dataclass(frozen=True)
class CabecalhoPmtiles:
    raiz_offset: int
    raiz_tamanho: int
    folhas_offset: int
    folhas_tamanho: int
    dados_offset: int
    dados_tamanho: int
    quantidade_tiles: int
    compressao_interna: int
    compressao_tiles: int
    tipo_tile: int
    zoom_minimo: int
    zoom_maximo: int
    limites: tuple[float, float, float, float]


@dataclass(frozen=True)
class Tile:
    conteudo: bytes
    codificacao: str | None
    max_age: int = 60


@dataclass(frozen=True)
class EntradaDiretorio:
    tile_id: int
    offset: int
    tamanho: int
    quantidade: int


def _ler_exato(arquivo, offset: int, tamanho: int, total: int) -> bytes:
    if offset < 0 or tamanho < 0 or offset > total or tamanho > total - offset:
        raise ErroMapa("O arquivo do mapa está inválido.")
    arquivo.seek(offset)
    conteudo = arquivo.read(tamanho)
    if len(conteudo) != tamanho:
        raise ErroMapa("O arquivo do mapa está incompleto.")
    return conteudo


def _descomprimir(conteudo: bytes, codigo: int) -> bytes:
    nome = TIPOS_COMPRESSAO.get(codigo)
    if nome is None:
        raise ErroMapa("O arquivo do mapa usa uma compressão desconhecida.")
    try:
        if nome == "none":
            return conteudo
        if nome == "gzip":
            descompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            descomprimido = descompressor.decompress(conteudo, LIMITE_DIRETORIO + 1)
            if len(descomprimido) > LIMITE_DIRETORIO or not descompressor.eof:
                raise ErroMapa("O diretório do mapa excede o limite permitido.")
            return descomprimido
        if nome == "brotli":
            raise ErroMapa("O runtime não oferece leitura segura para diretórios Brotli.", 503)
        import zstandard

        return zstandard.ZstdDecompressor().decompress(conteudo, max_output_size=LIMITE_DIRETORIO)
    except ImportError:
        raise ErroMapa("O runtime não tem suporte à compressão usada pelo mapa.", 503) from None
    except Exception:
        raise ErroMapa("O arquivo do mapa está inválido.") from None


def ler_cabecalho(arquivo) -> CabecalhoPmtiles:
    arquivo.seek(0, os.SEEK_END)
    total = arquivo.tell()
    if total < TAMANHO_CABECALHO:
        raise ErroMapa("O arquivo do mapa está inválido.")
    cabecalho = _ler_exato(arquivo, 0, TAMANHO_CABECALHO, total)
    if cabecalho[:7] != b"PMTiles" or cabecalho[7] != 3:
        raise ErroMapa("O arquivo do mapa não é PMTiles v3.")

    raiz_offset, raiz_tamanho, _, _, folhas_offset, folhas_tamanho, dados_offset, dados_tamanho = struct.unpack_from(
        "<8Q", cabecalho, 8
    )
    quantidade_tiles = struct.unpack_from("<Q", cabecalho, 72)[0]
    compressao_interna, compressao_tiles, tipo_tile = cabecalho[97:100]
    zoom_minimo, zoom_maximo = cabecalho[100:102]
    limites_e7 = struct.unpack_from("<4i", cabecalho, 102)
    limites = tuple(valor / 10_000_000 for valor in limites_e7)

    if (
        raiz_tamanho == 0
        or raiz_tamanho > LIMITE_DIRETORIO
        or folhas_tamanho > total
        or dados_tamanho > total
        or zoom_minimo > zoom_maximo
        or zoom_maximo > 30
        or tipo_tile != 1
        or compressao_interna not in TIPOS_COMPRESSAO
        or compressao_tiles not in TIPOS_COMPRESSAO
    ):
        raise ErroMapa("O arquivo do mapa tem um cabeçalho inválido ou não contém tiles vetoriais.")
    for offset, tamanho in ((raiz_offset, raiz_tamanho), (folhas_offset, folhas_tamanho), (dados_offset, dados_tamanho)):
        if offset < TAMANHO_CABECALHO or offset > total or tamanho > total - offset:
            raise ErroMapa("O arquivo do mapa está inválido.")
    oeste, sul, leste, norte = limites
    if not (-180 <= oeste <= leste <= 180 and -90 <= sul <= norte <= 90):
        raise ErroMapa("O arquivo do mapa tem limites geográficos inválidos.")
    return CabecalhoPmtiles(
        raiz_offset,
        raiz_tamanho,
        folhas_offset,
        folhas_tamanho,
        dados_offset,
        dados_tamanho,
        quantidade_tiles,
        compressao_interna,
        compressao_tiles,
        tipo_tile,
        zoom_minimo,
        zoom_maximo,
        limites,
    )


def _ler_varint(conteudo: bytes, cursor: int) -> tuple[int, int]:
    valor = 0
    deslocamento = 0
    while cursor < len(conteudo) and deslocamento <= 63:
        byte = conteudo[cursor]
        cursor += 1
        valor |= (byte & 0x7F) << deslocamento
        if valor >= 1 << 64:
            raise ErroMapa("O diretório do mapa está inválido.")
        if byte < 0x80:
            return valor, cursor
        deslocamento += 7
    raise ErroMapa("O diretório do mapa está inválido.")


def _ler_diretorio(conteudo: bytes) -> list[EntradaDiretorio]:
    quantidade, cursor = _ler_varint(conteudo, 0)
    if quantidade > 1_000_000:
        raise ErroMapa("O diretório do mapa excede o limite permitido.")
    colunas: list[list[int]] = [[], [], [], []]
    for coluna in colunas:
        for _ in range(quantidade):
            valor, cursor = _ler_varint(conteudo, cursor)
            coluna.append(valor)
    if cursor != len(conteudo):
        raise ErroMapa("O diretório do mapa está inválido.")
    ids: list[int] = []
    atual = 0
    for delta in colunas[0]:
        atual += delta
        if atual >= 1 << 64:
            raise ErroMapa("O diretório do mapa está inválido.")
        ids.append(atual)
    entradas: list[EntradaDiretorio] = []
    offset_anterior = 0
    tamanho_anterior = 0
    for indice in range(quantidade):
        codificado = colunas[3][indice]
        offset = offset_anterior + tamanho_anterior if codificado == 0 else codificado - 1
        tamanho = colunas[2][indice]
        quantidade_run = colunas[1][indice]
        entradas.append(EntradaDiretorio(ids[indice], offset, tamanho, quantidade_run))
        offset_anterior, tamanho_anterior = offset, tamanho
    if any(entradas[i].tile_id >= entradas[i + 1].tile_id for i in range(len(entradas) - 1)):
        raise ErroMapa("O diretório do mapa está inválido.")
    return entradas


def _hilbert(x: int, y: int, zoom: int) -> int:
    distancia = 0
    escala = 1 << (zoom - 1)
    while escala:
        rx = 1 if x & escala else 0
        ry = 1 if y & escala else 0
        distancia += escala * escala * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                lado = (1 << zoom) - 1
                x, y = lado - x, lado - y
            x, y = y, x
        escala >>= 1
    return distancia


def _tile_id(z: int, x: int, y: int) -> int:
    if z == 0:
        return 0
    return ((1 << (2 * z)) - 1) // 3 + _hilbert(x, y, z)


def _buscar_tile(arquivo, cabecalho: CabecalhoPmtiles, tile_id: int) -> tuple[int, int] | None:
    offset_dir = cabecalho.raiz_offset
    tamanho_dir = cabecalho.raiz_tamanho
    diretorios_lidos = 0
    for _ in range(LIMITE_PROFUNDIDADE + 1):
        diretorios_lidos += 1
        if diretorios_lidos > LIMITE_DIRETORIOS or tamanho_dir > LIMITE_DIRETORIO:
            raise ErroMapa("O diretório do mapa excede os limites permitidos.")
        conteudo = _ler_exato(arquivo, offset_dir, tamanho_dir, _tamanho_arquivo(arquivo))
        paginas = _descomprimir(conteudo, cabecalho.compressao_interna)
        entradas = _ler_diretorio(paginas)
        if not entradas:
            return None
        ids = [entrada.tile_id for entrada in entradas]
        indice = bisect_right(ids, tile_id) - 1
        if indice < 0:
            return None
        entrada = entradas[indice]
        if entrada.quantidade:
            if tile_id >= entrada.tile_id + entrada.quantidade:
                return None
            if entrada.offset > cabecalho.dados_tamanho or entrada.tamanho > cabecalho.dados_tamanho - entrada.offset:
                raise ErroMapa("O diretório do mapa está inválido.")
            return cabecalho.dados_offset + entrada.offset, entrada.tamanho
        base_folhas = cabecalho.folhas_offset
        if entrada.offset > cabecalho.folhas_tamanho or entrada.tamanho > cabecalho.folhas_tamanho - entrada.offset:
            raise ErroMapa("O diretório do mapa está inválido.")
        offset_dir = base_folhas + entrada.offset
        tamanho_dir = entrada.tamanho
    raise ErroMapa("O diretório do mapa excede a profundidade permitida.")


def _tamanho_arquivo(arquivo) -> int:
    cursor = arquivo.tell()
    arquivo.seek(0, os.SEEK_END)
    total = arquivo.tell()
    arquivo.seek(cursor)
    return total


def ler_tile(caminho: Path, z: str | int, x: str | int, y: str | int) -> Tile | None:
    valores: list[int] = []
    for valor in (z, x, y):
        texto = str(valor)
        if not _INTEIRO.fullmatch(texto) or len(texto) > 10:
            raise ErroMapa("As coordenadas do tile são inválidas.", 400)
        valores.append(int(texto))
    zoom, coluna, linha = valores
    if not 0 <= zoom <= 30 or coluna >= (1 << zoom) or linha >= (1 << zoom):
        raise ErroMapa("As coordenadas do tile estão fora da faixa.", 400)
    try:
        with caminho.open("rb") as arquivo:
            cabecalho = ler_cabecalho(arquivo)
            if not cabecalho.zoom_minimo <= zoom <= cabecalho.zoom_maximo:
                return None
            ident = _tile_id(zoom, coluna, linha)
            resultado = _buscar_tile(arquivo, cabecalho, ident)
            if resultado is None:
                return None
            offset, tamanho = resultado
            if tamanho == 0 or tamanho > LIMITE_TILE:
                raise ErroMapa("O tile excede o limite permitido.", 413)
            conteudo = _ler_exato(arquivo, offset, tamanho, _tamanho_arquivo(arquivo))
            compressao = TIPOS_COMPRESSAO[cabecalho.compressao_tiles]
            codificacao = {"none": None, "gzip": "gzip", "brotli": "br", "zstd": "zstd"}[compressao]
            return Tile(conteudo, codificacao)
    except FileNotFoundError:
        raise ErroMapa("O mapa base ainda não foi preparado.", 503) from None
    except PermissionError:
        raise ErroMapa("O arquivo do mapa não está disponível para leitura.", 503) from None
    except OSError:
        raise ErroMapa("Não foi possível ler o mapa base.", 503) from None


def _numero(
    ambiente: Mapping[str, str], nome: str, padrao: float, minimo: float, maximo: float
) -> float:
    chave = f"ALFRED_MAPA_{nome}"
    try:
        valor = float(ambiente.get(chave, str(padrao)))
    except (TypeError, ValueError):
        raise ErroMapa("A configuração do mapa é inválida.", 400) from None
    if not math.isfinite(valor) or not minimo <= valor <= maximo:
        raise ErroMapa("A configuração do mapa é inválida.", 400)
    return valor


def _identificador(ambiente: Mapping[str, str], nome: str, padrao: str) -> str:
    valor = ambiente.get(f"ALFRED_MAPA_{nome}", padrao)
    if not isinstance(valor, str) or not _IDENTIFICADOR.fullmatch(valor):
        raise ErroMapa("A configuração do esquema do mapa é inválida.", 400)
    return valor


def _atribuicao(ambiente: Mapping[str, str], caminho_atribuicao: Path) -> str:
    fonte = ambiente.get("ALFRED_MAPA_ATRIBUICAO")
    if fonte is None:
        try:
            fonte = caminho_atribuicao.read_text(encoding="utf-8")
        except OSError:
            fonte = "Fonte local"
    fonte = " ".join(str(fonte).split())
    fonte = re.sub(r"(?i)https?://\S+|www\.\S+", "", fonte).strip()
    if not fonte or len(fonte) > 300 or any(ord(caractere) < 32 for caractere in fonte):
        fonte = "Fonte local"
    return f"© OpenStreetMap contributors · {fonte}"


def configuracao(caminho: Path = ARQUIVO_BASE, ambiente: Mapping[str, str] | None = None) -> dict:
    ambiente = os.environ if ambiente is None else ambiente
    if not caminho.is_file():
        return {
            "available": False,
            "message": "O mapa offline ainda não foi preparado. Consulte a seção Mapa do README para gerar a base local.",
        }
    try:
        with caminho.open("rb") as arquivo:
            cabecalho = ler_cabecalho(arquivo)
    except ErroMapa:
        raise
    except OSError:
        raise ErroMapa("Não foi possível ler o mapa base.", 503) from None

    centro_lat = _numero(ambiente, "CENTRO_LAT", -10.9472, -90, 90)
    centro_lon = _numero(ambiente, "CENTRO_LON", -37.0731, -180, 180)
    zoom = _numero(ambiente, "ZOOM", 15.0, cabecalho.zoom_minimo, cabecalho.zoom_maximo)
    pitch = _numero(ambiente, "INCLINACAO", 60.0, 0, 70)
    max_pitch = _numero(ambiente, "INCLINACAO_MAXIMA", 70.0, 0, 70)
    if pitch > max_pitch:
        raise ErroMapa("A inclinação inicial excede o máximo configurado.", 400)
    antialias_texto = ambiente.get("ALFRED_MAPA_ANTIALIASING", "false").casefold()
    if antialias_texto not in {"true", "false", "1", "0", "sim", "nao"}:
        raise ErroMapa("A configuração de antialiasing do mapa é inválida.", 400)
    antialias = antialias_texto in {"true", "1", "sim"}
    oeste = _numero(ambiente, "AREA_OESTE", -38.245, -180, 180)
    sul = _numero(ambiente, "AREA_SUL", -11.575, -90, 90)
    leste = _numero(ambiente, "AREA_LESTE", -36.394, -180, 180)
    norte = _numero(ambiente, "AREA_NORTE", -9.515, -90, 90)
    if not (oeste < leste and sul < norte and oeste <= centro_lon <= leste and sul <= centro_lat <= norte):
        raise ErroMapa("A área e o centro configurados para o mapa são inválidos.", 400)
    min_area_oeste, min_area_sul, max_area_leste, max_area_norte = cabecalho.limites
    if not (
        min_area_oeste <= centro_lon <= max_area_leste
        and min_area_sul <= centro_lat <= max_area_norte
    ):
        raise ErroMapa("O centro configurado está fora da área coberta pelo mapa.", 400)
    camadas = {
        "agua": _identificador(ambiente, "CAMADA_AGUA", NOMES_CAMADAS["agua"]),
        "parques": _identificador(ambiente, "CAMADA_PARQUES", NOMES_CAMADAS["parques"]),
        "ruas": _identificador(ambiente, "CAMADA_RUAS", NOMES_CAMADAS["ruas"]),
        "edificios": _identificador(ambiente, "CAMADA_EDIFICIOS", NOMES_CAMADAS["edificios"]),
    }
    atributos = {
        "classe": _identificador(ambiente, "ATRIBUTO_CLASSE", "kind"),
        "altura": _identificador(ambiente, "ATRIBUTO_ALTURA", "height"),
        "altura_minima": _identificador(ambiente, "ATRIBUTO_ALTURA_MINIMA", "min_height"),
    }
    url_satelite = str(ambiente.get("ALFRED_MAPA_SATELITE_URL", "")).strip()
    if url_satelite and (
        not url_satelite.startswith("https://")
        or any(ord(caractere) < 32 for caractere in url_satelite)
        or len(url_satelite) > 2048
        or not all(marcador in url_satelite for marcador in ("{z}", "{x}", "{y}"))
    ):
        raise ErroMapa("A configuração do serviço de imagem de satélite é inválida.", 400)
    atribuicao_satelite = " ".join(str(ambiente.get("ALFRED_MAPA_SATELITE_ATRIBUICAO", "")).split())
    if len(atribuicao_satelite) > 300 or any(ord(caractere) < 32 for caractere in atribuicao_satelite):
        atribuicao_satelite = ""
    if url_satelite and not atribuicao_satelite:
        raise ErroMapa("Informe a atribuição exigida pelo provedor das imagens de satélite.", 400)
    return {
        "available": True,
        "center": [centro_lon, centro_lat],
        "zoom": zoom,
        "pitch": pitch,
        "maxPitch": max_pitch,
        "antialias": antialias,
        "bounds": [oeste, sul, leste, norte],
        "minZoom": cabecalho.zoom_minimo,
        "maxZoom": cabecalho.zoom_maximo,
        "layers": camadas,
        "attributes": atributos,
        "attribution": _atribuicao(ambiente, caminho.with_name("atribuicao_fonte.txt")),
        "satelliteAvailable": bool(url_satelite),
        "satelliteAttribution": atribuicao_satelite,
    }


def estilo(caminho: Path = ARQUIVO_BASE, ambiente: Mapping[str, str] | None = None) -> dict:
    config = configuracao(caminho, ambiente)
    if not config["available"]:
        raise ErroMapa(str(config["message"]), 503)
    camadas = config["layers"]
    atributos = config["attributes"]
    altura_edificio = ["max", ["to-number", ["get", atributos["altura"]], 3.4], 3.4]
    ambiente = os.environ if ambiente is None else ambiente
    url_satelite = str(ambiente.get("ALFRED_MAPA_SATELITE_URL", "")).strip()
    fontes = {
        "alfred-base": {
            "type": "vector",
            "tiles": ["/api/mapa/tiles/{z}/{x}/{y}.mvt"],
            "bounds": config["bounds"],
            "minzoom": config["minZoom"],
            "maxzoom": config["maxZoom"],
        }
    }
    camadas_estilo = [
        {"id": "fundo", "type": "background", "paint": {"background-color": "#1b1b1d"}},
    ]
    if url_satelite:
        fontes["alfred-satellite"] = {
            "type": "raster",
            "tiles": [url_satelite],
            "tileSize": 256,
            "attribution": config["satelliteAttribution"],
        }
        camadas_estilo.append({
            "id": "imagem-satelite",
            "type": "raster",
            "source": "alfred-satellite",
            "layout": {"visibility": "none"},
            "paint": {"raster-opacity": 1},
        })
    return {
        "version": 8,
        "name": "Alfred offline · Sergipe",
        "sources": fontes,
        "layers": camadas_estilo + [
            {
                "id": "agua",
                "type": "fill",
                "source": "alfred-base",
                "source-layer": camadas["agua"],
                "paint": {"fill-color": "#18191b", "fill-opacity": 0.98},
            },
            {
                "id": "parques",
                "type": "fill",
                "source": "alfred-base",
                "source-layer": camadas["parques"],
                "filter": ["in", ["get", atributos["classe"]], ["literal", ["park", "wood", "grass", "nature_reserve"]]],
                "paint": {"fill-color": "#222426", "fill-opacity": 0.92},
            },
            {
                "id": "edificios-planta",
                "type": "fill",
                "source": "alfred-base",
                "source-layer": camadas["edificios"],
                "minzoom": 10,
                "paint": {"fill-color": "#697581", "fill-opacity": 0.88},
            },
            {
                "id": "edificios-contorno",
                "type": "line",
                "source": "alfred-base",
                "source-layer": camadas["edificios"],
                "minzoom": 15,
                "filter": ["==", ["get", atributos["classe"]], "building"],
                "paint": {
                    "line-color": "#b8ded6",
                    "line-width": ["interpolate", ["linear"], ["zoom"], 15, 0.65, 17, 1.15],
                    "line-opacity": 0.92,
                },
            },
            {
                "id": "ruas",
                "type": "line",
                "source": "alfred-base",
                "source-layer": camadas["ruas"],
                "paint": {
                    "line-color": "rgba(226, 235, 242, 0.92)",
                    "line-width": [
                        "interpolate", ["linear"], ["zoom"],
                        8, ["case", ["in", ["get", atributos["classe"]], ["literal", ["motorway", "trunk", "primary", "highway", "major_road"]]], 1.0, 0.6],
                        10, ["case", ["in", ["get", atributos["classe"]], ["literal", ["motorway", "trunk", "primary", "highway", "major_road"]]], 1.7, 1.0],
                        12, ["case", ["in", ["get", atributos["classe"]], ["literal", ["motorway", "trunk", "primary", "highway", "major_road"]]], 2.5, 1.5],
                        14, ["case", ["in", ["get", atributos["classe"]], ["literal", ["motorway", "trunk", "primary", "highway", "major_road"]]], 3.3, 2.0],
                    ],
                    "line-opacity": 0.94,
                },
            },
            {
                "id": "edificios",
                "type": "fill-extrusion",
                "source": "alfred-base",
                "source-layer": camadas["edificios"],
                "minzoom": 11,
                "paint": {
                    "fill-extrusion-height": altura_edificio,
                    "fill-extrusion-base": ["to-number", ["get", atributos["altura_minima"]], 0],
                    "fill-extrusion-color": [
                        "interpolate", ["linear"], altura_edificio,
                        3.4, "#64717a", 6, "#64717a", 10, "#7b8993", 40, "#98a5ae", 100, "#bcc6cc"
                    ],
                    "fill-extrusion-opacity": 0.98,
                    "fill-extrusion-vertical-gradient": True,
                },
            },
        ],
    }


def resposta_http_tile(tile: Tile | None) -> tuple[int, dict[str, str], bytes]:
    if tile is None:
        return 204, {"Cache-Control": "private, max-age=60"}, b""
    cabecalhos = {
        "Content-Type": "application/vnd.mapbox-vector-tile",
        "Content-Length": str(len(tile.conteudo)),
        "Cache-Control": f"private, max-age={tile.max_age}",
        "X-Content-Type-Options": "nosniff",
    }
    if tile.codificacao:
        cabecalhos["Content-Encoding"] = tile.codificacao
    return 200, cabecalhos, tile.conteudo


def json_estilo(caminho: Path = ARQUIVO_BASE, ambiente: Mapping[str, str] | None = None) -> bytes:
    return json.dumps(estilo(caminho, ambiente), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
