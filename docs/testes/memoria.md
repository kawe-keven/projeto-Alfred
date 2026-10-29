# Auditoria do ciclo de memória

Esta suíte mede o que existe no repositório e mantém as lacunas visíveis. Ela não implementa nem corrige o serviço de memória. Os dados de teste usam personas inventadas e armazenamento temporário; nenhuma execução desta suíte deve apontar para `dados/`.

## Executar

O comando rápido padrão exclui os marcadores `lento`, `integracao` e `ao_vivo`:

```powershell
python -m pytest
```

Execute níveis específicos quando necessário:

```powershell
python -m pytest -m integracao
python -m pytest -m lento
```

O modo controlado do auditor não acessa a rede e usa vetores definidos no próprio cenário:

```powershell
python scripts/auditar_memoria.py
```

Esse modo mede o contrato vetorial e imprime métricas por categoria. A busca controlada comprova a ordenação e a consulta do Chroma; **não mede qualidade semântica**.

Para avaliar embeddings com Ollama local, execute manualmente:

```powershell
python scripts/auditar_memoria.py --modelo-real
```

O auditor envia somente o conjunto de consultas e documentos fictícios ao endpoint local configurado em `ALFRED_OLLAMA_URL` (padrão `http://localhost:11434`). O modelo de embeddings vem de `ALFRED_MODELO_EMBEDDINGS` (padrão `qwen3-embedding:0.6b`). O script não baixa modelos. O resultado inclui recall@5 e MRR por categoria e no total, sem combinar categorias numa nota única.

Na avaliação local de 25/10/2026 com `qwen3-embedding:0.6b`, as 40 consultas fictícias recuperaram o fato esperado entre os cinco primeiros resultados (recall@5 1,000; MRR 1,000 em cada categoria). Esse conjunto pequeno e preparado não representa a qualidade de todas as consultas reais; os testes da suíte verificam a conexão entre memória e sessão, enquanto a qualidade do fluxo conversacional completo permanece sem avaliação semântica automatizada.

Para revisar respostas de um modelo Ollama local:

```powershell
python scripts/auditar_memoria.py --llm-real
```

Esse modo executa cinco cenários fictícios e lista respostas sanitizadas para revisão humana. É um **harness de prompt direto** que usa o núcleo de honestidade do Alfred; não percorre a sessão real nem prova que o Alfred use RAG. O cenário de esquecimento não apaga nada e não chama ferramentas. Não execute `--modelo-real` ou `--llm-real` sem intenção de consultar o Ollama local.

As opções podem ser combinadas. O armazenamento é criado em diretório temporário próprio, com chave aleatória descartável. A saída contém versões, estados e métricas; não imprime textos das memórias ou a chave.

## O que os testes demonstram

| Nível | O que verifica | O que não demonstra |
|---|---|---|
| Rápido | Fixtures isoladas, cifragem básica, gravação relacional, vetores controlados, reconciliação, auditoria, primitivas de criação/esquecimento e lacunas explicitamente puladas. | Não demonstra qualidade semântica de embeddings ou comportamento de LLM real. |
| `integracao` | Componentes conectados em cenários sem modelos reais, quando houver testes marcados para isso. | Não substitui sessão nova de CLI/voz com armazenamento real e índice previamente reindexado. |
| `lento` | 50 mil eventos e vetores de baixa dimensão; tempo de indexação, latência mediana/p95, memória estimada e espaço em disco. | Não prevê desempenho com hardware, corpus, modelo de embedding ou configurações diferentes. Sem variáveis de limite, não reprova por tempo/uso; só verifica contagens e resultados de sanidade. |
| `ao_vivo` | Reservado a verificações manuais com modelos locais. Use as opções do auditor acima. | Não roda por padrão e não deve usar dados reais. |

## RAG no fluxo de conversa

Quando `dados/bancos/alfred.db` e `dados/bancos/chroma/` existem, a chave-mestra está disponível no ambiente ou no keyring e o modelo de embeddings local está pronto no Ollama, CLI, painel web e voz consultam os índices de memórias, conhecimento, resumos e falas anteriores a cada turno. O contexto é limitado a cinco itens relevantes, usa um limiar de distância cosine e é inserido no prompt como dado não confiável. `/fontes` no CLI informa os IDs, tipos e datas dos itens recuperados. Falhas de chave, modelo ou índice deixam a sessão sem RAG; nenhum texto é enviado a serviço remoto.

CLI e voz usam o mesmo banco cifrado, índice vetorial, chave do perfil e registro de ferramentas quando esses recursos estão disponíveis. Turnos concluídos são gravados e indexados; ambos podem acessar `lembrar_memoria` e `esquecer_memoria`, com confirmação antes de gravar ou apagar pela ferramenta. Na CLI, `/lembrar` e `/esquecer` também usam esse armazenamento. A reindexação e a geração de resumos por período continuam sendo operações de manutenção, sem execução automática por turno.

Para configurar limites do benchmark lento, defina apenas os que deseja impor:

- `ALFRED_MEMORIA_LENTO_MAX_INDEXACAO_S`
- `ALFRED_MEMORIA_LENTO_MAX_P95_MS`
- `ALFRED_MEMORIA_LENTO_MAX_RAM_MB`
- `ALFRED_MEMORIA_LENTO_MAX_DISCO_MB`

O relatório de RAM separa o delta residente amostrado do pico de alocação Python. A alocação Python não inclui toda a memória nativa do Chroma; compare esses números com cuidado.

## Limites de privacidade e esquecimento

Os testes verificam bytes de armazenamentos temporários fictícios e validam que texto não é enviado ao repositório Chroma nos cenários exercitados. Isso não prova ausência de resíduos em um armazenamento real. Exclusão lógica, páginas livres, arquivos WAL/SHM, compactação interna do Chroma, backups, snapshots do sistema e cópias externas exigem verificações distintas. A suíte não lê nem varre `dados/`.

Os testes de SQLite confirmam apenas as operações relacionais implementadas. O ciclo completo de esquecimento, remoção de vetores, edição/regeneração de resumos e auditoria ligada à operação ainda não existe no fluxo e permanece como lacuna.

## Bancos reais

Esta suíte não abre bancos reais nem lê seu conteúdo. O repositório contém o CLI operacional em `alfred.interfaces.cli.armazenamento`, com comandos de metadados `status` e `verificar`. Não foi encontrado módulo `alfred.bancos` no código inspecionado. Não passe `dados/` ao auditor e não execute os níveis ao vivo automaticamente.
