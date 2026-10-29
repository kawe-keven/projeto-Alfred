# ADR 0001: criptografia do perfil e das memórias sensíveis

- **Status:** aceito
- **Decisão:** usar SQLCipher para criptografar em repouso o banco SQLite que contém o perfil pessoal e as memórias classificadas como sensíveis.

## Contexto

O perfil e parte das memórias podem conter informações pessoais. Criptografar o banco inteiro evita depender de criptografia por campo e protege também índices e metadados armazenados nesse banco.

## Consequências

- A implementação Python usa o pacote `sqlcipher3` e deve validar que a conexão está usando SQLCipher antes de criar ou abrir o banco sensível.
- A chave vem de `ALFRED_SQLCIPHER_CHAVE`, configurada fora do controle de versão. O valor não pode aparecer em logs, mensagens de erro ou arquivos de dados.
- A implementação de derivação, hierarquia, guarda e rotação de chaves pertence a `src/alfred/seguranca/chaves/`; primitivas de cifra pertencem a `src/alfred/seguranca/criptografia/`.
- Uma chave ausente ou inválida deve impedir o acesso ao banco; não se deve criar silenciosamente um banco SQLite sem criptografia.
- Backups do banco permanecem criptografados. A recuperação depende da guarda segura da chave.
- A decisão sobre criptografar também bases de dados não sensíveis será tomada quando os respectivos armazenamentos forem implementados.
