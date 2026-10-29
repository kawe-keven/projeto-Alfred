# Mapa offline

Este documento acompanha a preparação local dos dados do mapa e seus créditos. O mapa em uso não baixa tiles, estilos, fontes, ícones ou dados de terceiros. A rede é necessária somente quando o usuário decide executar os scripts de preparação.

## Preparar os dados do mapa

1. Escolha uma fonte PMTiles pública cuja licença permita o uso pretendido e cuja política permita leitura HTTP por intervalos. Confira as condições atuais do provedor e o tamanho aproximado antes de iniciar.
2. A área padrão é o estado de Sergipe, com caixa de recorte aproximada de oeste `-38.245`, sul `-11.575`, leste `-36.394` e norte `-9.515`. O centro inicial é Aracaju (`-37.0731`, `-10.9472`), em zoom 15 e visão 3D inclinada para destacar ruas e edifícios. Use o controle “−” para afastar e ver uma área maior do estado. O arquivo PMTiles preparado precisa cobrir esse centro.
3. Execute `scripts/preparar_mapa.ps1` com a URL HTTPS da fonte e a atribuição textual exigida pelo provedor. O recorte Sergipe e zoom máximo 15 são os padrões; podem ser substituídos com `-Oeste`, `-Sul`, `-Leste`, `-Norte` e `-ZoomMaximo`. O script mostra os parâmetros e pede a confirmação literal `PREPARAR` antes de acessar a rede. A saída é `dados/mapa/base.pmtiles`; o texto de atribuição fica em `dados/mapa/atribuicao_fonte.txt`.
4. Para vendorização do runtime, execute `scripts/vendorizar_mapa.ps1`. Ele fixa MapLibre GL JS 5.6.0, confere que a publicação tem mais de 14 dias, valida o SHA-512 publicado pelo registro npm e registra SHA-256 no manifesto local. Não instala Node nem adiciona uma dependência Python.

O utilitário `go-pmtiles` é fixado em 1.31.2. O script consulta a release oficial, confere o SHA-256 do arquivo Windows publicado pela API do GitHub e valida o arquivo baixado antes de executá-lo. A extração remota depende de suporte a requisições HTTP por intervalos da fonte PMTiles.

## Créditos e licenças

- Dados derivados do OpenStreetMap devem exibir atribuição visível a **© OpenStreetMap contributors**, com ligação informativa para `https://www.openstreetmap.org/copyright`, e respeitar a licença **ODbL**. Os termos e a atribuição devem ser conferidos para o extrato específico usado.
- Exiba também o crédito e a licença exigidos pelo provedor dos tiles. O texto informado a `-AtribuicaoFonte` é preservado para a futura atribuição na interface. O provedor e sua licença precisam ser identificados antes da publicação da configuração do mapa.
- O runtime MapLibre GL JS usa licença **BSD-3-Clause**; a cópia da licença é vendorizada junto ao runtime em `ui/vendor/maplibre-gl/LICENSE.txt`.
- A licença do software de extração `go-pmtiles` e os avisos da release devem ser revisados pelo usuário antes da execução. O utilitário é temporário e não é instalado no Alfred.

O arquivo base não é cifrado e revela a região coberta a quem puder ler o arquivo. Lugares salvos pelo usuário são dados sensíveis e serão persistidos somente no SQLCipher; se a chave não estiver disponível, permanecerão apenas na memória da sessão.

## Configuração local

O servidor usa Sergipe como área inicial e Aracaju como centro. As variáveis de ambiente `ALFRED_MAPA_CENTRO_LAT`, `ALFRED_MAPA_CENTRO_LON`, `ALFRED_MAPA_ZOOM`, `ALFRED_MAPA_INCLINACAO`, `ALFRED_MAPA_INCLINACAO_MAXIMA`, `ALFRED_MAPA_ANTIALIASING` e `ALFRED_MAPA_AREA_OESTE`, `ALFRED_MAPA_AREA_SUL`, `ALFRED_MAPA_AREA_LESTE`, `ALFRED_MAPA_AREA_NORTE` podem ajustar a visão. A inclinação máxima é limitada a 70 graus; o antialiasing começa desligado para reduzir o uso da GPU. As variáveis são lidas em memória e não registradas nos logs.

O estilo usa as camadas e atributos Protomaps `water`, `landuse`, `roads`, `buildings`, `kind`, `height` e `min_height`, com extrusão 3D para edifícios. A cobertura, a densidade e as alturas visíveis dependem dos dados OpenStreetMap presentes no arquivo. Para outro esquema, ajuste `ALFRED_MAPA_CAMADA_AGUA`, `ALFRED_MAPA_CAMADA_PARQUES`, `ALFRED_MAPA_CAMADA_RUAS`, `ALFRED_MAPA_CAMADA_EDIFICIOS`, `ALFRED_MAPA_ATRIBUTO_CLASSE`, `ALFRED_MAPA_ATRIBUTO_ALTURA` e `ALFRED_MAPA_ATRIBUTO_ALTURA_MINIMA`.

## Imagem de satélite

O botão `SAT` alterna entre a base vetorial offline e imagens raster de satélite. A imagem é opcional e não é baixada por padrão. No `config.yaml`, preencha `map.satellite_url` com o modelo HTTPS XYZ do provedor (os marcadores `{z}`, `{x}` e `{y}` são obrigatórios) e `map.satellite_attribution` com os créditos exigidos. Exemplo de modelo Esri World Imagery: `https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?token=SEU_TOKEN`. Obtenha uma chave/token válido de acordo com a documentação e os termos atuais do provedor. O endpoint e o token são usados no navegador para buscar tiles; limite a chave à origem e aos serviços necessários no painel do provedor. Reinicie o Alfred após configurar. A atribuição informada também aparece no mapa. Variáveis de ambiente `ALFRED_MAPA_SATELITE_URL` e `ALFRED_MAPA_SATELITE_ATRIBUICAO` podem substituir os valores do YAML.

O modo de satélite mantém os edifícios extrudados em 3D, quando os dados locais os incluem. O PMTiles atual contém polígonos de prédios e casas, áreas naturais, água, parques e ruas, mas não pontos individuais de árvores. Para mostrar árvores, use a camada local opcional abaixo. Imagens aéreas, sozinhas, são pixels e não fornecem coordenadas ou alturas de árvores.


O leitor embutido suporta diretórios sem compressão, gzip e zstd. Diretórios Brotli retornam erro claro até que haja suporte seguro disponível. Tiles gzip, Brotli e zstd são entregues com o `Content-Encoding` correspondente; a leitura atual aceita somente tiles vetoriais MVT.

## Leitor PMTiles

O painel usará um leitor PMTiles próprio, mínimo e somente de leitura no servidor. A versão do runtime de mapa no navegador não lê o arquivo PMTiles diretamente: ela solicita tiles vetoriais ao endpoint local do Alfred. Isso mantém o arquivo fora de um endpoint de intervalos e permite validar coordenadas de tile e limitar cada resposta.
