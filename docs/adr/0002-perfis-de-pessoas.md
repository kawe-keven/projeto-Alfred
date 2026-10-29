# ADR 0002: Perfis locais de pessoas

- **Status:** aceito
- **Data:** 2026-10-15

## Contexto

O Alfred precisa guardar fatos declarados pelo usuário sobre pessoas do seu círculo social, consultar esses dados em conversas relevantes e permitir que o usuário os revise ou remova. Os argumentos de ferramentas e documentos lidos são dados não confiáveis. Os três arquivos do perfil principal continuam sob responsabilidade exclusiva do carregador; ferramentas não os escrevem.

## Decisões

1. Perfis de pessoas ficam em `dados/perfil/pessoas/<identificador>.md`, confinados por validação de caminho comum. Cada perfil tem cabeçalho YAML produzido com `yaml.safe_dump`, seções Markdown fixas e campo `versao` para detectar atualizações concorrentes.
2. Identificadores são derivados do nome, sem acentos, em minúsculas e limitados a letras ASCII, números e sublinhados. Colisões nunca sobrescrevem arquivos.
3. O código normaliza fatos em uma linha, neutraliza marcadores Markdown e escapa conteúdo para impedir injeção de cabeçalho ou de prompt. `[declarado]` é acrescentado pelo código somente depois da confirmação.
4. `listar` e `ver` são operações de leitura sem confirmação. A listagem lê somente metadados. Qualquer perfil incluído no prompt é selecionado por correspondência do texto atual com nomes, apelidos ou relação, limitado a três pessoas e cerca de 250 palavras de fatos por pessoa. O bloco é explicitamente marcado como dado.
5. `criar`, `adicionar_fato`, `remover_fato` e `remover_pessoa` exigem confirmação decidida pelo código. A confirmação apresenta o conteúdo normalizado exato que será gravado ou removido. Atualizações exigem a versão que foi revisada; uma mudança concorrente cancela a operação. Remoção apaga o arquivo.
6. O repositório recusa CPF, RG, números de cartão válidos por Luhn, dados bancários, senhas, tokens, códigos de segurança e documentos de identidade. O máximo é 100 perfis e 400 palavras por perfil.
7. `criar_arquivo` continua reservado a documentos gerais em `dados/arquivos`, sem sobrescrita e com gravação atômica. Cotas padrão: 200 arquivos e 20 MiB no total; o limite individual de bytes também é configurável.
8. O antigo comportamento de `usar_arquivo_perfil` (ler um `.md` de `dados/arquivos`) passa a ser `ler_arquivo`, somente leitura e com a confirmação já existente. `usar_arquivo_perfil` fica reservado às operações sobre pessoas.

## Consequências e limites conhecidos

- Os arquivos de pessoas ficam em texto claro. Até existir criptografia de aplicação, use BitLocker ou cifra de disco equivalente e controle o acesso à conta do Windows.
- Pessoas mencionadas nos perfis não consentiram necessariamente com esse armazenamento. Guarde apenas contexto de relacionamento necessário e evite dados íntimos, documentos ou segredos.
- A seleção de perfis é lexical e limitada; não resolve todas as referências indiretas. O pronome “ela” só seleciona um perfil quando existe exatamente uma pessoa com relação feminina reconhecida.
- A leitura `ler_arquivo` e a nova ferramenta de perfis têm nomes e finalidades distintos; consumidores que chamavam `usar_arquivo_perfil` para ler documentos gerais precisam migrar para `ler_arquivo`.
