from __future__ import annotations

import gzip
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from alfred.interfaces.web import mapa


def _varint(valor: int) -> bytes:
    saida = bytearray()
    while valor >= 0x80:
        saida.append((valor & 0x7F) | 0x80)
        valor >>= 7
    saida.append(valor)
    return bytes(saida)


def _pmtiles_minimo(
    caminho: Path, *, tile: bytes | None = None, corrompido: bool = False, zoom_maximo: int = 0
) -> None:
    tile = gzip.compress(b"tile ficticio") if tile is None else tile
    diretorio = b"\x01\x00\x01" + _varint(len(tile)) + b"\x01"
    if corrompido:
        diretorio = b"\x80"
    inicio_dados = 127 + len(diretorio)
    fim_arquivo = inicio_dados + len(tile)
    cabecalho = bytearray(127)
    cabecalho[:7] = b"PMTiles"
    cabecalho[7] = 3
    struct.pack_into(
        "<8Q", cabecalho, 8,
        127, len(diretorio), 0, 0,
        fim_arquivo, 0,
        inicio_dados, len(tile),
    )
    struct.pack_into("<Q", cabecalho, 72, 1)
    cabecalho[97:102] = bytes((1, 2, 1, 0, zoom_maximo))
    struct.pack_into("<4i", cabecalho, 102, -1_000_000, -1_000_000, 1_000_000, 1_000_000)
    caminho.write_bytes(cabecalho + diretorio + tile)


def test_tile_valido_preserva_mvt_gzip_e_cabecalhos(tmp_path: Path) -> None:
    arquivo = tmp_path / "base.pmtiles"
    _pmtiles_minimo(arquivo)

    tile = mapa.ler_tile(arquivo, "0", "0", "0")
    assert tile is not None
    assert tile.codificacao == "gzip"
    assert gzip.decompress(tile.conteudo) == b"tile ficticio"
    status, cabecalhos, corpo = mapa.resposta_http_tile(tile)
    assert status == 200
    assert cabecalhos["Content-Type"] == "application/vnd.mapbox-vector-tile"
    assert cabecalhos["Content-Encoding"] == "gzip"
    assert cabecalhos["Content-Length"] == str(len(corpo))


def test_tile_ausente_e_zoom_fora_do_arquivo(tmp_path: Path) -> None:
    arquivo = tmp_path / "base.pmtiles"
    _pmtiles_minimo(arquivo, zoom_maximo=1)

    assert mapa.ler_tile(arquivo, 1, 1, 1) is None
    assert mapa.ler_tile(arquivo, 1, 0, 0) is None
    assert mapa.resposta_http_tile(None)[0] == 204


@pytest.mark.parametrize(("z", "x", "y"), [("abc", "0", "0"), ("0", "-1", "0"), ("0", "0", "00"), ("1", "2", "0")])
def test_coordenadas_invalidas_sao_rejeitadas(z: str, x: str, y: str, tmp_path: Path) -> None:
    arquivo = tmp_path / "base.pmtiles"
    _pmtiles_minimo(arquivo)
    with pytest.raises(mapa.ErroMapa) as erro:
        mapa.ler_tile(arquivo, z, x, y)
    assert erro.value.status == 400


def test_arquivo_ausente_e_erro_claro_sem_caminho(tmp_path: Path) -> None:
    caminho = tmp_path / "nao-exibir-este-caminho.pmtiles"
    with pytest.raises(mapa.ErroMapa) as erro:
        mapa.ler_tile(caminho, 0, 0, 0)
    assert erro.value.status == 503
    assert "preparado" in str(erro.value)
    assert str(caminho) not in str(erro.value)


def test_arquivo_corrompido_nao_expoe_caminho(tmp_path: Path) -> None:
    arquivo = tmp_path / "sentinela-caminho.pmtiles"
    _pmtiles_minimo(arquivo, corrompido=True)
    with pytest.raises(mapa.ErroMapa) as erro:
        mapa.ler_tile(arquivo, 0, 0, 0)
    assert arquivo.name not in str(erro.value)


def test_configuracao_sem_arquivo_nao_precisa_abri_lo(tmp_path: Path) -> None:
    resultado = mapa.configuracao(tmp_path / "ausente.pmtiles", {})
    assert resultado["available"] is False
    assert "preparado" in resultado["message"]


def test_configuracao_e_estilo_sao_locais_e_sem_rotulos(tmp_path: Path) -> None:
    arquivo = tmp_path / "base.pmtiles"
    _pmtiles_minimo(arquivo)
    ambiente = {
        "ALFRED_MAPA_CENTRO_LAT": "0",
        "ALFRED_MAPA_CENTRO_LON": "0",
        "ALFRED_MAPA_AREA_OESTE": "-0.1",
        "ALFRED_MAPA_AREA_SUL": "-0.1",
        "ALFRED_MAPA_AREA_LESTE": "0.1",
        "ALFRED_MAPA_AREA_NORTE": "0.1",
        "ALFRED_MAPA_ZOOM": "0",
        "ALFRED_MAPA_ATRIBUICAO": "Provedor fictício https://example.invalid/creditos",
    }

    config = mapa.configuracao(arquivo, ambiente)
    estilo = mapa.estilo(arquivo, ambiente)
    serializado = mapa.json_estilo(arquivo, ambiente).decode("utf-8")
    assert config["center"] == [0, 0]
    assert "glyphs" not in estilo and "sprite" not in estilo
    assert "http://" not in serializado and "https://" not in serializado
    assert all(camada["type"] != "symbol" for camada in estilo["layers"])
    assert estilo["sources"]["alfred-base"]["tiles"] == ["/api/mapa/tiles/{z}/{x}/{y}.mvt"]
    assert config["attribution"].startswith("© OpenStreetMap contributors · Provedor fictício")


def test_painel_nao_usa_cdn_ou_javascript_embutido() -> None:
    raiz = Path(__file__).parents[2]
    html = (raiz / "ui" / "index.html").read_text(encoding="utf-8")
    arquivos = [raiz / "ui" / "app.js", raiz / "ui" / "mapa" / "mapa.js"]
    assert "<script>" not in html.casefold()
    assert not any("https://" in linha or "http://" in linha for linha in html.splitlines())
    assert all("https://" not in arquivo.read_text(encoding="utf-8") and "http://" not in arquivo.read_text(encoding="utf-8") for arquivo in arquivos)


def test_configuracao_rejeita_valor_nao_finito(tmp_path: Path) -> None:
    arquivo = tmp_path / "base.pmtiles"
    _pmtiles_minimo(arquivo)
    with pytest.raises(mapa.ErroMapa) as erro:
        mapa.configuracao(arquivo, {"ALFRED_MAPA_CENTRO_LAT": "NaN"})
    assert erro.value.status == 400


def test_validacao_de_host_e_origin_do_painel_rejeita_externos() -> None:
    from alfred.interfaces.web.app import Requisicao

    local = SimpleNamespace(headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
    externo = SimpleNamespace(headers={"Host": "example.invalid", "Origin": "https://example.invalid"})
    origem_externa = SimpleNamespace(headers={"Host": "127.0.0.1:8765", "Origin": "https://example.invalid"})
    assert Requisicao.origem_local(local)
    assert not Requisicao.origem_local(externo)
    assert not Requisicao.origem_local(origem_externa)


def test_metodo_de_escrita_na_rota_mapa_retorna_405() -> None:
    from alfred.interfaces.web.app import Requisicao

    chamada = SimpleNamespace(
        headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"},
        path="/api/mapa/config",
        status=None,
        cabecalhos={},
        origem_local=lambda: True,
        send_response=lambda status: setattr(chamada, "status", status),
        send_header=lambda nome, valor: chamada.cabecalhos.__setitem__(nome, valor),
        end_headers=lambda: None,
    )
    Requisicao._responder_mapa_405(chamada)
    assert chamada.status == 405
    assert chamada.cabecalhos["Allow"] == "GET"
