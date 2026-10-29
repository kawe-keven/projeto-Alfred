# ADR 0006: operação dos armazenamentos locais

- **Estado:** aceito.
- **Data:** 2026-10-18.
- **Refina:** ADR 0001, sem alterá-lo.

## Decisão sobre chaves

`ALFRED_SQLCIPHER_CHAVE` contém a chave-mestra de 32 bytes em base64. A chave de cada banco e a chave HMAC da auditoria são derivadas por HKDF-SHA256, com rótulos distintos (`alfred.db`, `auditoria.db`, `metricas.db` e `auditoria.hmac`). A chave-mestra não é gravada pelo Alfred; os bytes permanecem em memória durante a operação. O ADR 0001 não proíbe explicitamente a derivação de subchaves e continua vigente.

O provedor de ambiente tem precedência quando a variável está definida. Se não estiver, o Alfred solicita a chave por leitura oculta (`getpass`) em terminal interativo. Sem variável e sem terminal interativo, a operação falha com mensagem clara. Chave ausente ou inválida nunca permite criar banco sem cifra.

**Não** defina `ALFRED_SQLCIPHER_CHAVE` permanentemente no perfil do usuário nem use `setx`. **Não** cole a chave em uma linha de comando, pois ela pode ficar no histórico. Prefira a leitura oculta. O agente de código executado como o mesmo usuário pode ler a variável de ambiente e acessar a chave enquanto o processo estiver ativo.

O extra opcional `seguranca` instala `keyring`; ele não é dependência padrão. A resolução prioriza a variável de ambiente, depois consulta a credencial `alfred` / `sqlcipher-chave-mestra` no backend do sistema, e usa a leitura oculta se a credencial não existir ou o backend estiver indisponível. Uma credencial existente mas inválida causa erro, sem recuo silencioso para outra chave. A API `ProvedorDeKeyring.guardar_chave_mestra` grava a chave fornecida no backend do sistema. Não existe comando `guardar-chave` nesta fase.

O backend selecionado nesta máquina é `WinVaultKeyring`. A integração foi exercitada com uma chave aleatória sintética sob serviço temporário, usando set/get/delete; a entrada foi removida ao fim do teste e nenhuma credencial Alfred existente foi consultada. O ambiente pode ainda retornar WinError 1312 em sessões isoladas; nesse caso o provedor falha fechado para uso do banco e solicita a leitura oculta, sem criar banco sem cifra. Sem keyring instalado, a variável de ambiente e a leitura oculta continuam disponíveis.

## Bancos, retenção e auditoria

Assume-se que nenhum banco real foi criado até esta decisão. Os comandos administrativos usam `dados/bancos/` como destino padrão, mas não criam diretórios nem bancos até uma operação explícita. SQLCipher deve ser carregado e validado antes de qualquer esquema; cada conexão tem fechamento explícito e tenta `PRAGMA wal_checkpoint(TRUNCATE)` ao fechar.

O banco principal, o banco de auditoria e o banco de métricas recebem subchaves independentes. A auditoria mantém cadeia HMAC e uma âncora local separada. Métricas guardam apenas números e rótulos de configuração, com retenção padrão de 90 dias. Conteúdo de conversa não deve aparecer em logs.

O campo `arquivo` usa `lzma` por padrão. A coluna `algoritmo` identifica a compressão usada para permitir mudança futura sem ambiguidade.

## Vetores e embeddings

O extra opcional fixa `chromadb==1.5.9`. O cliente persistente desativa telemetria. As coleções são abertas com `embedding_function=None` e recebem vetores pré-calculados; texto/documentos não são enviados ao Chroma. O contrato aceita apenas identificadores, vetores e metadados mínimos (tipo, data, importância e estado). O nome do modelo e a dimensão ficam na coleção e em `meta`.

O adaptador de embeddings permanece atrás de `GeradorDeEmbeddings` e usa Ollama local. Nenhum modelo de embeddings é baixado sem aprovação explícita. A instalação de dependências de Chroma é responsabilidade do usuário. Keyring é uma dependência opcional e isolada no extra `seguranca`.

## Operação

`python -m alfred.interfaces.cli.armazenamento --help` documenta os comandos administrativos. `criar` aplica as migrações; `status` informa presença e contagens agregadas; `verificar` checa integridade e cadeia de auditoria; `backup` produz cópias SQLCipher e copia a âncora e o índice local quando disponíveis; `limpar-metricas` aplica retenção; `reindexar` envia textos apenas ao Ollama local para calcular embeddings e passa ao Chroma somente IDs, vetores e metadados mínimos. A reindexação não baixa modelos; requer que o modelo esteja previamente disponível no Ollama. Se modelo ou dimensão mudarem, cria primeiro um índice substituto e preserva a pasta anterior como `chroma.anterior`; não sobrescreve uma cópia anterior existente.

O comando de conversa `criar_lembrete` continua sendo apenas simulado.
