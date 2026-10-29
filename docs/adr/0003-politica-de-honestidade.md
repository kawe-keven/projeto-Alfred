# ADR 0003: honestidade e procedência controladas pelo código

- **Status:** aceito
- **Data:** 2026-10-15

## Contexto

O modelo pode receber preferências, perfis e resultados de ferramentas que contêm dados não confiáveis. Texto gerado pelo modelo também pode afirmar ações que não ocorreram ou tratar uma simulação como ação real. A aplicação precisa tornar as capacidades observáveis e verificar alegações antes de apresentá-las.

## Decisão

- A política essencial de honestidade é definida pelo código e entra no prompt antes dos documentos de perfil.
- Cada sessão recebe um manifesto derivado do registro de ferramentas e do provedor configurado.
- Resultados de ferramentas usam um envelope tipado com origem, estado e conteúdo delimitado como dado não confiável.
- Alegações reconhecidas de ação concluída ficam retidas até existir um resultado real compatível. O modelo recebe no máximo uma solicitação de revisão; sem confirmação, usa-se uma resposta determinística.
- O comando `/fontes` apresenta as fontes e o contexto registrados para o último turno sem revelar o conteúdo do perfil.
- Buscas pessoais sem correspondência e pedidos de informação instável sem fonte atual são marcados explicitamente.
- Cenários de avaliação contêm apenas nomes e dados fictícios. A avaliação opcional com Ollama é executada pelo usuário e usa ferramentas falsas.

## Consequências

As verificações são conservadoras: algumas frases que não afirmam uma ação podem ser retidas para revisão. O detector de contradição só sinaliza negação textual explícita de fatos com marcador `[declarado]`; não tenta resolver conflitos semânticos. O avaliador de cenário é um auxílio de revisão, não uma prova de honestidade do modelo.

Nenhuma chamada ao Ollama é feita pelos testes unitários. Testes de integração com modelo dependem de execução local explícita pelo usuário.
