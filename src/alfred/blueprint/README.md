# Blueprint de projetos

O módulo `alfred.blueprint` identifica pedidos de criação de projeto, classifica o
tipo (`digital`, `fisico` ou `hibrido`), avalia riscos e cria um pacote documental
em `projetos/<slug>/`. O conteúdo completo fica em Markdown; o resumo devolvido ao
Alfred contém o caminho e três próximos passos.

## Estrutura e extensão

- `detector.py`: intenção, classificação e extração do nome.
- `gerador.py`: geração por seção, publicação atômica e metadados JSON.
- `riscos.py`: fatores de risco e a fonte única `LIMITES_FIXOS_BLUEPRINT` para
  limites de recusa. Avisos de segurança operacional ficam separados.
- `normas.py`: referências oficiais condicionais por tipo de projeto.
- `templates/`: orientação de conteúdo para projetos digitais, físicos e híbridos.

Para incluir uma referência, acrescente um registro `Norma` à coleção de domínio
adequada em `normas.py`, com título, aplicação limitada e link da fonte oficial.
Verifique a fonte antes de atualizar a edição e indique que o usuário deve
confirmar a vigência e a aplicabilidade. Nunca invente identificadores ou
cláusulas nem declare conformidade automática.

Para acrescentar um template, crie ou ajuste um arquivo em `templates/` e atualize
o prompt da respectiva seção em `gerador.py`. Preserve as indicações de estimativa,
premissas e itens “a definir”; não acrescente custo, dimensões ou prazos sem base.

Os projetos são saídas do usuário e não entram no Git (`/projetos/` está ignorado).
O módulo não sobrescreve uma pasta existente: cria um sufixo incremental.
