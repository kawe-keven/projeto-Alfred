# ADR 0008: mapa local offline

## Estado
Aceito.

## Decisão
O mapa carrega uma base PMTiles local recortada para Sergipe e MapLibre empacotado no projeto; a visão inicial centraliza Aracaju, limita a navegação ao estado e não consulta tiles remotos nem solicita geolocalização. Lugares favoritos são validados no servidor e gravados no banco SQLCipher existente quando há chave disponível. Sem chave, a API mantém os lugares apenas em memória e sinaliza essa condição.

Toda criação, alteração, movimentação ou remoção pede confirmação explícita. A auditoria registra somente ação e quantidade, sem nome, coordenadas ou identificador do lugar. As rotas de leitura do mapa aceitam GET e as mutações são limitadas ao recurso de lugares.

## Consequências
A preparação da base e do runtime é uma etapa explícita e local. O primeiro carregamento pode depender do tamanho da base PMTiles. A interface oferece modo leve e informa quando a persistência é apenas de sessão.
