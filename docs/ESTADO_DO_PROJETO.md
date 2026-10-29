# Auditoria de estado do projeto Alfred

**Data:** 2026-10-23  
**Raiz:** `<raiz>`  
**Escopo:** inspeção estática de código, documentação, configuração não secreta, estrutura e metadados agregados de `dados/`. Nenhum serviço foi iniciado, nenhum áudio foi capturado ou reproduzido e nenhum conteúdo de `dados/` foi aberto.

## Resumo executivo

O Alfred hoje tem um CLI de texto, um painel web local, um ciclo de voz local, ferramentas com validação e confirmação, perfis em arquivos e armazenamento SQLCipher/Chroma. Com uma chave local disponível, a sessão prepara o banco principal cifrado; o índice e a recuperação dependem do modelo de embeddings local.

O que não está demonstrado é uma memória conversacional completa: os turnos do CLI e da voz ficam em histórico de sessão, não são gravados automaticamente; `/lembrar`, `/memorias`, `/fixar` e `/esquecer` não existem no CLI. Geração de resumos, detecção de padrões e esquecimento em cascata aparecem como lacunas explícitas. O resultado de testes desta auditoria é **NÃO EXECUTADO**: um teste chama configuração que abre preferências reais se presentes, o que violaria o limite de leitura de `dados/`.

**Cinco riscos principais:** perfis textuais sem cifragem; arquivos de perfil com nomes pessoais no diretório de código (conteúdo não aberto; rastreamento Git não verificável); painel sem autenticação, embora vinculado ao loopback; testes não executáveis com segurança nesta auditoria e duas falhas históricas documentadas; memória local depende da disponibilidade da chave e do modelo de embeddings.

**Cinco próximos passos recomendados:** retirar dados pessoais de `src/` e verificar o rastreamento num ambiente Git confiável; isolar a leitura de preferências reais em testes; decidir e implementar criptografia do perfil em arquivos; especificar e ligar o ciclo de memória ponta a ponta; reforçar autenticação/CSRF e cabeçalhos do painel. Esses passos são recomendações, não alterações realizadas.

## 1. Identidade e ambiente

| Item | Estado observado | Evidência |
|---|---|---|
| Projeto e versão | `alfred` 0.1.0 | `pyproject.toml` |
| Python | `.venv` usa Python 3.14.7; o sistema lista Python 3.14.7; requisito declarado `>=3.11` | `py -0p`, `.venv\Scripts\python.exe --version`, `pyproject.toml` |
| Sistema operacional | Windows | inicializadores `.bat`, caminhos e ambiente desta auditoria |
| Raiz | `<raiz>` | diretório do projeto; caminho do usuário omitido |
| Dependências base | `sqlcipher3>=0.6.4`, `PyYAML>=6.0`; sem limites superiores | `pyproject.toml` |
| Extras | `dev`: `pytest>=8`; `memoria`: `chromadb==1.5.9`; `seguranca`: `keyring>=25`; `voz`: NumPy, sounddevice, Silero VAD, PyTorch, ONNX Runtime, OpenWakeWord, faster-whisper e Piper, todos com limites mínimos e sem versão máxima | `pyproject.toml` |
| Entradas instaladas | `alfred`, `alfred-armazenamento`, `alfred-painel` | `[project.scripts]` em `pyproject.toml` |
| Pacotes relevantes instalados | SQLCipher 0.6.4; PyYAML 6.0.3; Chroma 1.5.9; NumPy 2.5.4; sounddevice 0.5.6; Silero VAD 6.2.3; PyTorch 2.14.1; ONNX Runtime 1.31.0; faster-whisper 1.2.1; OpenWakeWord 0.6.0; Piper 1.8.0; pytest 9.1.1 | `pip list --format=freeze` do `.venv` |
| GPU / VRAM | Uma GPU detectada; 8192 MiB totais e 674 MiB usados no instante da consulta | `nvidia-smi` consultou apenas números |
| RAM | 15,8 GB registrados em observação histórica do ADR 0005; não medidos nesta auditoria | `docs/adr/0005-motor-de-voz-voicestudio.md` |
| Ollama | Configuração aponta para `qwen3.5:4b`; embeddings configurados como `qwen3-embedding:0.6b`; instalação local e tamanhos **NÃO VERIFICADOS** | `config.yaml`, configuração do carregador; `ollama list` não foi executado |
| Git | **NÃO VERIFICADO.** Git recusou as leituras por divergência de proprietário do diretório. Branch, contagem de commits, estado pendente, diff e últimos 15 commits não foram obtidos; nenhuma configuração Git foi alterada | `git status`, `git branch`, `git rev-list`, `git log` e `git diff --stat` recusados pelo Git |

### Configuração e segredos

`config.yaml` é YAML dividido em `llm`, `audio`, `vad`, `stt`, `tts` e `voice`. Os valores tipados abrangem strings, números, booleanos e listas de strings; o perfil TTS e os detalhes que identificam uma voz foram omitidos. Valores não sensíveis incluem endpoints loopback e nomes de modelos. O carregador também aceita variáveis `ALFRED_*` e, se presente, importa preferências TTS de um arquivo sob `dados/` para o ambiente do processo. O conteúdo e o nome desse arquivo não foram lidos.

`.env.exemplo` foi processado somente para enumerar nomes de variáveis e tipos inferidos; nenhum valor foi exibido. A lista contém opções de caminhos, modelo, limites, voz, VAD, STT/TTS e chave. O arquivo `.env` não foi aberto. O ambiente desta tarefa não consultou, imprimiu nem armazenou a chave dos bancos. `pip list` não mostrou o extra `keyring` instalado; isso não informa se existe uma credencial em outro backend.

### Metadados de `dados/`

Somente nomes de subpastas de primeiro nível, contagens e bytes foram consultados. As contagens incluem arquivos em níveis inferiores; nomes de arquivos e conteúdo não foram enumerados.

| Subpasta de primeiro nível | Arquivos | Bytes totais |
|---|---:|---:|
| `backups_agente` | 1 | 5.463 |
| `bancos` | 1 | 196.608 |
| `logs` | 1 | 213.908 |
| `modelos` | 2 | 63.206.149 |
| `perfil` | 4 | 14.568 |
| `registros` | 0 | 0 |

Não há subpasta de primeiro nível `arquivos` na listagem observada. Existe um arquivo em `dados/bancos`, mas seu nome e tipo não foram consultados; portanto, a existência de um arquivo de banco específico do Alfred e de um índice vetorial não pode ser confirmada. Não foi possível determinar se bancos reais já foram criados: há arquivo no diretório esperado, mas não se pode atribuir sua identidade sem listar o nome. Nenhum backup foi aberto.

## 2. Estrutura do projeto

Rótulos abaixo descrevem implementação e ligação estática ao fluxo. Como os testes não foram executados nesta auditoria, não se atribui `✅ LIGADO E TESTADO` a código cujo resultado atual não foi confirmado.

```text
<raiz>/
├── config.yaml — 🟠 configuração tipada carregada pelo código
├── .env.exemplo — 🟠 catálogo de variáveis; valores não reproduzidos
├── pyproject.toml, requirements.txt — 🟠 empacotamento e dependências
├── iniciar_alfred_visual.bat — 🟠 inicia dependências locais e painel
├── iniciar_configurador_voz.bat — 🟠 inicia configurador Tk
├── docs/ — 🟠 documentação e ADRs; não provam execução
├── prompts/system.txt — 🟠 prompt usado na montagem do agente
├── scripts/ — 🟠 ferramentas de auditoria, avaliação e medição
├── src/alfred/
│   ├── adaptadores/llm/ — 🟠 Ollama local
│   ├── adaptadores/voz/ — 🟠 captura, VAD, STT, TTS e wake word
│   ├── configuracao/ — 🟠 carregador e pronúncias
│   ├── ferramentas/ — 🟠 registro, resultados e ferramentas nativas
│   ├── interfaces/cli, web, ciclo_de_voz, configuracao_voz — 🟠 interfaces usadas
│   ├── interfaces/api/ — ⚪ diretório sem módulo implementado
│   ├── memoria/armazenamento/ — 🟠 SQLCipher, migrações, Chroma, embeddings e RAG
│   ├── memoria/perfil/ — 🟠 carregador, montador, perfis de pessoas; inclui três
│   │   arquivos Markdown com nomes pessoais, conteúdo não aberto e nomes omitidos
│   ├── memoria/esquecimento/ — ⚪ diretório sem módulo implementado
│   ├── memoria/resumidores/ — ⚪ diretório sem módulo implementado
│   ├── nucleo/agente, politicas — 🟠 núcleo ligado à conversa e à voz
│   ├── nucleo/eventos, modelos, proatividade — ⚪ diretórios sem implementação
│   └── seguranca/chaves, auditoria — 🟠 implementados; outros subpacotes abaixo são vazios
├── testes/unitarios/, testes/memoria/ — 🟠 testes encontrados; execução atual bloqueada
└── ui/ — 🟠 HTML, CSS, JavaScript e imagem da esfera do Alfred
```

Outros subpacotes sem arquivos Python encontrados: `adaptadores/fontes`, `adaptadores/notificacoes`, `seguranca/autenticacao`, `seguranca/criptografia`, `seguranca/integridade` e `seguranca/isolamento` (**⚪ ESQUELETO**). A pasta de perfil em `src/` contém dados que parecem pessoais fora do local padrão de dados. Seu conteúdo foi deliberadamente ignorado. Como o Git bloqueou a inspeção, não é possível afirmar se esses arquivos estão rastreados. Isso merece revisão prioritária por um operador com acesso Git apropriado.

Há diretórios temporários de pytest e de execução descartável na raiz, além dos diretórios usuais de cache/ambiente. Não foram enumerados seus conteúdos; a limpeza não foi solicitada.

### Inventário estático resumido dos módulos

| Área / módulos | Propósito, interface pública e consumidor | Testes associados / estado |
|---|---|---|
| `nucleo/provedor_llm.py`, `nucleo/agente/agente.py`, `roteador_rapido.py` | Contratos de mensagens/eventos, chamadas ao LLM, orquestração de ferramenta e atalhos conservadores. `Agente.responder(...)` é usado pelo ciclo de voz; `SessaoConversa` é a interface de texto | `test_ollama.py`, `test_voz.py`, `test_resultado_ferramenta.py`; 🟠 ligado em código; testes atuais não executados |
| `nucleo/politicas/{honestidade,verificador_alegacoes,confirmacao,fontes,atualidade,capacidades}.py` | Regras de honestidade, procedência, confirmação, marcador de busca sem correspondência/contradição, atualidade e manifesto de ferramentas | `test_verificador_alegacoes.py`, `test_fontes.py`, `test_confirmacao` coberto em `test_voz.py`, `test_atualidade.py`, `test_capacidades.py`; 🟠 |
| `adaptadores/llm/ollama.py` | `ProvedorOllama` implementa chamadas locais, streaming, cancelamento, aquecimento e ferramentas no contrato Ollama | `test_ollama.py`; 🟠. Ollama real não foi consultado nesta auditoria |
| `adaptadores/voz/captura_audio.py`, `vad.py`, `stt.py` | `CapturaAudio`, `DetectorDeVoz`, `TranscritorLocal`; frames de microfone, detecção e transcrição | `test_voz.py`, `test_inicio_voz.py`; 🟠. Sem prova acústica ao vivo |
| `adaptadores/voz/tts.py`, `tts_voicestudio.py`, `texto_voz.py`, `palavra_de_ativacao.py` | `SintetizadorPiper`, `SintetizadorVoiceStudio`, normalização/pronúncia e contrato de detector de palavra | `test_tts_voicestudio.py`, `test_pronuncias.py`, `test_voz.py`; 🟠. Comparação perceptiva não realizada |
| `ferramentas/registro.py`, `resultado.py`, `nativas/*` | Registro de esquema e resultado tipado; ferramentas listadas na seção 3. O agente recebe os esquemas do registro | `test_resultado_ferramenta.py`, `test_ferramentas_arquivos.py`, `test_ler_arquivo.py`, `test_usar_arquivo_perfil.py`, `test_caminhos_ferramentas.py`; 🟠 |
| `memoria/perfil/carregador.py`, `montador_prompt.py`, `pessoas.py` | Carrega três documentos de perfil, monta prompt e mantém perfis locais de pessoas. `SessaoConversa` chama o carregador e seleciona contexto de pessoas mencionadas | `test_carregador_perfil.py`, `test_montador_prompt.py`, `test_pessoas_repositorio.py`, `test_sessao_conversa.py`; 🟠. Arquivos reais não inspecionados |
| `memoria/armazenamento/{conexao,migracao,banco_relacional,metricas}.py` | Conexões SQLCipher, migrações transacionais, operações tipadas e retenção de métricas | `test_bancos_relacionais.py`, `test_cli_armazenamento.py`, `test_metricas.py`, suíte `testes/memoria`; 🟠. Nenhum banco real aberto |
| `memoria/armazenamento/{embeddings,repositorio_vetorial,vetorial_chroma,reindexacao,rag}.py` | Embeddings Ollama, contrato Chroma, busca/reconciliação, indexação administrativa e automática de conversas | `test_embeddings.py`, `test_repositorio_vetorial_chroma.py`, `test_recuperacao.py`; persistência automática depende de chave e modelo de embeddings locais; 🟠 |
| `memoria/esquecimento`, `memoria/resumidores` | Diretórios preparados, sem serviço de ciclo de vida nem gerador hierárquico | Vários testes de requisito marcados como ignorados; ⚪ |
| `seguranca/chaves/{provedores,derivacao}.py`, `seguranca/auditoria/registro.py` | Fonte de chave por ambiente/keyring/entrada oculta, HKDF-SHA256 e cadeia auditável com âncora | `test_chaves_bancos.py`, `test_auditoria.py`, testes de persistência; 🟠 |
| `interfaces/cli/{app,armazenamento}.py` | Sessão textual e comandos operacionais dos bancos. `SessaoConversa`, `executar`, `main`, `construir_parser` | `test_sessao_conversa.py`, `test_cli_armazenamento.py`; 🟠 |
| `interfaces/web/app.py`, `ui/*` | Servidor HTTP local, endpoints de chat/voz/configuração e UI. JavaScript chama `/api/chat`, status, confirmação e controles de voz | Sem teste específico de navegador/HTTP listado; testes de sessão e de adaptador não verificam experiência completa; 🟠 |
| `interfaces/ciclo_de_voz/{app,orquestrador}.py` | Monta os componentes, mantém ciclo assíncrono de áudio, confirmações, interrupções e reprodução | `test_voz.py`, `test_inicio_voz.py`; 🟠 |
| `interfaces/configuracao_voz/app.py` | Aplicação desktop Tk para catálogo, prévia e persistência de ajustes | Cobertura unitária específica não localizada; 🟠 |
| `interfaces/api`, `nucleo/eventos`, `nucleo/modelos`, `nucleo/proatividade`, diretórios de segurança vazios | Áreas reservadas sem comportamento executável localizado | ⚪ ESQUELETO |
| `configuracao/configuracao.py`, `configuracao/pronuncias.toml`, `carregador.py` | Configuração, precedência de ambiente e entrada de pacote | `test_configuracao.py`; ⚠️ teste arrisca ler preferência real, por isso suíte não foi iniciada |

`api`, eventos, modelos e proatividade não têm interfaces públicas implementadas. Assinaturas representativas ligadas ao fluxo: `SessaoConversa.responder(texto)`, `ProvedorOllama.conversar(...)`, `Agente.responder(...)`, `ServicoRAG.recuperar(consulta)`, `BancoRelacional.inserir_evento(...)`, `RepositorioVetorial.buscar(...)`, `CapturaAudio.iniciar()`, `TranscritorLocal.transcrever(audio)`, `SintetizadorVoiceStudio.sintetizar(texto)` e `OrquestradorDeVoz.executar()`.

### Ferramentas registradas

| Ferramenta | Comportamento real no código | Estado |
|---|---|---|
| `consultar_hora` | Retorna hora local | Implementada e registrada; teste funcional não reexecutado |
| `controlar_luz` | Retorna confirmação de **simulação**; não controla dispositivo | Simulada e identificada como tal |
| `criar_lembrete` | Retorna confirmação de **simulação**; não agenda nem notifica | Simulada e identificada como tal |
| `tocar_musica` | Retorna confirmação de **simulação**; não toca áudio | Simulada e identificada como tal |
| `ligar_para` | Retorna confirmação de **simulação**; não telefonará; marcada sensível e não reversível | Simulada e exige confirmação |
| `criar_arquivo` | Cria `.md`/`.txt` sob pasta confinada, com limite, gravação atômica e sem sobrescrita | Ação real local; exige consentimento via pedido e validação de argumentos |
| `ler_arquivo` | Lê Markdown da pasta confinada, após confirmação | Ação real e sensível |
| `usar_arquivo_perfil` | Lista/consulta sem confirmação; escrita só após confirmação e checagem de versão | Ação real; operações confinadas à pasta de pessoas |

`RegistroDeFerramentas` marca simulações nos resultados para o modelo. Argumentos têm esquema estrito, limites de tamanho e rejeição de propriedades adicionais. Caminhos comuns são validados contra traversal, links simbólicos/junctions e nomes reservados do Windows (`ferramentas/nativas/_caminhos.py`). O número de telefone ou contato não é usado por uma integração de telefonia.

## 3. Como inicia e funciona

### Inicialização do painel

`iniciar_alfred_visual.bat` muda para a pasta do projeto, exige `.venv\Scripts\python.exe` e executa `scripts/iniciar_dependencias_locais.ps1`. O script tenta verificar Ollama em `127.0.0.1:11434` e VoiceStudio em `127.0.0.1:3900`; se não respondem, tenta abrir os aplicativos instalados/atalhos do Menu Iniciar e espera até 30 tentativas de 2 segundos por serviço. Se não respondem, avisa e continua. Não instala dependências, não baixa o modelo Ollama e não garante que o motor TTS esteja carregado.

O `.bat` tenta reaproveitar uma resposta HTTP na porta 8765; se já houver servidor, abre `http://127.0.0.1:8765/#cli` e termina. Caso contrário, abre o navegador e executa `python -m alfred.interfaces.web.app`, que fica em primeiro plano até interrupção. O servidor é `ThreadingHTTPServer` vinculado somente a `127.0.0.1:8765`. Não inicia uma sessão de microfone automaticamente.

### Turno de texto

1. `ui/app.js` envia texto para `POST /api/chat`.
2. `interfaces/web/app.py` limita o corpo HTTP a 200.000 bytes e o texto de chat a 4.000 caracteres, então chama `_sessao()` de forma preguiçosa.
3. `interfaces/cli/app.py` constrói `carregar_configuracao()`, `carregar_perfil()`, `montar_prompt_sistema()` e `criar_rag()`; com chave local não interativa, o serviço cria o banco principal cifrado e prepara o Chroma usando embeddings locais.
4. `SessaoConversa.responder()` acrescenta contexto de pessoas mencionadas, contexto RAG, marcador de atualidade e possíveis contradições; mantém histórico em memória e chama `ProvedorOllama` com ferramentas. Turnos concluídos são gravados no SQLCipher e indexados.
5. `RegistroDeFerramentas` valida a chamada. Operações sensíveis passam pela confirmação do código; o envelope de resultado distingue sucesso, simulação, cancelamento e falha.
6. A interface devolve a resposta ao navegador. Turnos concluídos são inseridos em `eventos` por `SessaoConversa` e indexados para recuperação futura.

### Turno de voz

1. UI envia modo `conversa`, `apertar` ou `palavra` para `/api/voice/start`.
2. O painel lança subprocesso `python -m alfred.interfaces.ciclo_de_voz --modo ...`, sem janela de console e com saída padrão e erros redirecionados para `DEVNULL`.
3. O ciclo monta agente, captura mono a 16 kHz, Silero VAD, Parakeet TDT v3 via sherpa-onnx e `SintetizadorVoiceStudio`; há progresso no CLI próprio, mas o painel suprime o stdout/stderr do subprocesso.
4. Frames são processados, voz detectada e fim de fala definido por VAD; STT transcreve português; o agente local consulta Ollama; a resposta é dividida em frases; VoiceStudio produz PCM e sounddevice reproduz. O código oferece interrupção por voz (barge-in), mute e confirmação de ferramentas.
5. Estado é exposto em arquivo temporário do sistema para polling da UI. Parar a sessão termina o subprocesso e remove arquivos de controle temporários.

Não há captura pelo `getUserMedia` do navegador; o dispositivo de áudio é aberto por `sounddevice` no processo local. Fechar apenas a aba não executa rota de parada: a sessão continua até ser encerrada no painel ou até o servidor terminar; o `finally` do servidor chama `parar_voz()` quando seu processo encerra.

### Ordem dos blocos do prompt de sistema

`montador_prompt.py` concatena nesta ordem: identidade/idioma; instruções essenciais de honestidade; procedência; acesso e hierarquia do contexto pessoal; blocos de perfil; regras fixas de conversa; estilo de resposta e uso seguro de ferramentas; data/hora local ao final. Preferências e fatores estáveis têm limites de palavras; o documento de conhecimento abrangente é incluído por inteiro. Contexto de pessoas, RAG e atualidade são acrescentados por turno depois do prompt base. Conversas anteriores ficam disponíveis após gravação e indexação automáticas, desde que a chave e o modelo local estejam disponíveis. O tamanho do prompt com perfil real é **NÃO CALCULADO**; não foi substituído por estimativa baseada em dados privados.

## 4. Memória e bancos — matriz do ciclo

| Capacidade | Estado | Evidência e ligação |
|---|---|---|
| Guardar turnos automaticamente | 🟢 LIGADO COM PRÉ-REQUISITOS | CLI e voz gravam cada turno concluído no banco SQLCipher quando a chave local está disponível; falhas de gravação não interrompem a conversa |
| Criar nota/memória por pedido | ⚪ ESQUELETO | `/lembrar` não aparece em `executar_comando`; teste de requisito em `testes/memoria/test_criacao.py` é skip “não implementado” |
| Indexar embeddings/Chroma | 🟢 LIGADO COM PRÉ-REQUISITOS | Turnos são indexados automaticamente quando o serviço local de embeddings está disponível; falhas deixam registros pendentes para retomada na próxima sessão |
| RAG a cada turno | 🟡 LIGADO COM PRÉ-REQUISITOS | CLI e voz consultam o RAG e registram turnos; depende de chave configurada e modelo de embeddings local disponível |
| Montar bloco RAG no prompt | 🟢 LIGADO COM PRÉ-REQUISITOS | Ordena relevância, recência, importância e frequência; limita cinco itens e 5.000 caracteres, remove duplicatas e inclui metadados de fonte. O bloco é escapado como JSON e instruído como dado sem autoridade |
| `/fontes` | 🟢 LIGADO | CLI lista fonte, tipo, papel, identificador e data do último contexto sem exibir seu conteúdo |
| `/memorias`, `/fixar`, `/esquecer`, `/manutencao` | ⚪ AUSENTES NO CLI | Não aparecem no dispatcher de comandos; sem serviço conversacional conectado |
| Resumos hierárquicos | 🟡 IMPLEMENTADO, NÃO LIGADO | Migração possui níveis dia/semana/mês/ano e relação de itens; `memoria/resumidores/` vazio; testes de criação automática de resumos ignorados |
| Padrões observados e proposta/consentimento | 🟡 IMPLEMENTADO, NÃO LIGADO | Esquema `padroes` e ocorrências; teste de detector/proposta marcado como não implementado |
| Esquecimento por ciclo de vida/cascata | 🟡 IMPLEMENTADO, NÃO LIGADO | SQL tem campos de estado/fixado e primitivas de alteração/remoção; pasta de serviço de esquecimento vazia. Testes de ciclo completo, vetores, resumos e auditoria estão ignorados |
| Reconciliação SQL/Chroma | 🟠 PARCIAL | Método `RepositorioVetorialChroma.reconciliar()` e testes de contrato; não há serviço de ciclo de vida ligado automaticamente |
| Auditoria de mutações de memória | 🟡 IMPLEMENTADO, NÃO LIGADO | Registro de cadeia auditável existe; os skips identificam que não está vinculado a cada operação do serviço de memória |
| Métricas da recuperação | 🟢 LIGADO | Cada busca grava duração, itens e tokens estimados por interface em banco cifrado separado, sem consulta ou conteúdo; retenção de 90 dias |
| Marcador “sem registro” e contradições | 🟠 PARCIAL | `fontes.py` e `SessaoConversa` criam marcadores; lógica é heurística/textual, não prova de qualidade semântica. Há testes unitários associados |

### Plano de implementação em partes

1. **Persistência automática** — concluída: gravar cada turno cifrado e retomar embeddings pendentes.
2. **Recuperação entre sessões** — concluída: buscar e ranquear memórias/conversas; mostrar proveniência e indicar claramente quando o histórico não está disponível ou não encontra resultado.
3. **Contexto controlado e segurança** — concluída: deduplicação, diversidade, limite de cinco itens/5.000 caracteres e serialização JSON para tratar memórias como dados sem autoridade.
4. **Observabilidade** — concluída: guardar latência, itens e estimativa de tokens (caracteres/4) sem texto de conversa.
5. **Isolamento multi-persona** — concluído por diretório de perfil: o perfil padrão preserva o banco existente; cada caminho de perfil alternativo recebe diretório de bancos e índice próprio, nomeado por hash do caminho canônico. CLI e voz usam a mesma resolução.

Limites de privacidade/retenção do Chroma e o ciclo completo de esquecimento continuam em pendências separadas.

### Esquema e estado físico

Migrações do banco principal chegam à versão 3. Tabelas do esquema: `meta`, `sessoes`, `resumos`, `eventos`, `resumo_itens`, `arquivo`, `padroes`, `padroes_ocorrencias`, `lembretes`, `avisos` e `categorias_aviso`. As migrações de métricas criam tabelas de latência, uso de recursos e volume/tempo da recuperação. O perfil padrão mantém os bancos em `dados/bancos`; perfis alternativos usam diretórios separados sob a pasta `bancos` do perfil pai.

SQLCipher é usado nos bancos principais; cada finalidade recebe subchave HKDF-SHA256 distinta. A âncora/cadeia de auditoria usa HMAC e validação própria. Chroma é persistido como armazenamento local próprio; a implementação valida ID, dimensão, modelo e metadados, mas o conteúdo/vetores do diretório Chroma não são protegidos por SQLCipher. O corpo dos perfis Markdown de pessoas e dos arquivos criados também fica em texto claro. Migrações e tabelas descrevem o esquema; nenhum banco real foi aberto para confirmar versão, tabelas ou integridade.

O modelo configurado para embeddings é `qwen3-embedding:0.6b`; dimensão não está fixada na configuração e é lida dos metadados do banco. O teste de memória usa dimensão artificial 8. Modelo real, dimensão real e qualidade de recuperação **NÃO VERIFICADOS**. Não inferir modelo Ollama instalado a partir da configuração.

## 5. Voz

Pipeline implementado: captura `sounddevice` em blocos mono de 16 kHz; VAD Silero; transcrição Parakeet TDT v3 via sherpa-onnx na CPU; agente Ollama com streaming e raciocínio desativado; TTS pelo perfil local VoiceStudio `66b001cc`, criado da referência original, com Piper Faber como fallback. O perfil VoiceStudio `66ca3722` contém uma amostra do Piper Faber; não foi treinado para imitar a gravação original. O perfil TTS tem instruções de estilo desativadas por padrão.

Se VoiceStudio falhar, o ciclo não troca para outro timbre; a resposta não terá áudio naquela tentativa. O adaptador usa timeout de conexão e leitura, nova tentativa limitada e reativação para uma chamada futura; segundo o registro de validação no ADR 0005, ainda não há timeout curto/backoff exponencial.

### Medições que já existem

- ADR 0004 registra cinco chamadas sintéticas ao Ollama: mediana quente de aproximadamente 2,18 s até primeiro token; a primeira chamada fria elevou o pior caso para cerca de 12,3 s. Era medição só do Ollama, não de voz ponta a ponta. Um prompt sintético caiu de 1.268 para 1.151 tokens; não era perfil real.
- O adendo do ADR 0005 registra, para dez pedidos HTTP locais após aquecimento, TTFB mediana/p95 de 1,665/1,877 s sem `instructions` e 1,798/2,612 s com `instructions`. Tempo total mediano/p95: 2,174/2,493 s sem e 2,327/3,203 s com estilo. Sem reprodução ou gravação. Não atingiu a meta documentada de TTFB ~400 ms.
- O ADR 0004 registra uso histórico de VRAM de 1.949 MiB numa observação, sem atribuição a processo. O ADR 0005 registra 8.192 MiB totais; esta auditoria observou 8.192 MiB totais e 674 MiB usados. Medidas são instantes diferentes, sem profiling por componente. RAM histórica é 15,8 GB; atual **NÃO MEDIDA**.
- Latência completa de microfone a primeiro áudio, WER real, qualidade/naturalidade, barge-in e consumo de VRAM por processo: **NÃO MEDIDOS nesta auditoria**. `scripts/medir_voz.py` e `scripts/comparar_vozes.py` são ferramentas disponíveis, não foram executadas.

VoiceStudio esperado é desktop local, API em loopback na porta 3900. O painel consulta `/health` no script de início; catálogo consulta `/v1/models`, `/v1/audio/voices` e `/profiles`; TTS usa `POST /v1/audio/speech`. O perfil usado pelo Alfred é `66b001cc`, clone da referência original; `66ca3722` guarda uma amostra Piper Faber. O cliente restringe host local e não segue redirecionamentos. A versão 0.5.6 aparece em observação histórica; perfil criado nesta sessão com essa versão. Retenção interna, telemetria e demais dados próprios do VoiceStudio não foram auditados.

## 6. Segurança e privacidade

### Superfície do painel

- Escuta em `127.0.0.1:8765`; Ollama e VoiceStudio também são configurados para loopback. Não foi localizado WebSocket.
- `origem_local()` verifica `Host` e `Origin` nas rotas GET/POST. Não existe token de sessão, cookie de autenticação ou autenticação de usuário. Requisições sem `Origin` são aceitas se vierem com Host local; outro processo local pode chamar os endpoints.
- Rotas que mudam estado: `POST /api/chat`, `/api/voice/start`, `/api/voice/stop`, `/api/voice/mute`, `/api/voice/settings`, `/api/voice/preview` e `/api/confirm`. JSON tem limite de 200.000 bytes; chat até 4.000 caracteres. `/api/voice/settings` valida faixas e disponibilidade de modelos/perfis antes de gravar preferências.
- `X-Content-Type-Options: nosniff` é enviado para arquivos estáticos; respostas JSON usam `Cache-Control: no-store`. Não foram localizados CSP, `frame-ancestors`, Permissions Policy ou cabeçalhos de segurança equivalentes. Não há WebSocket ou fluxo de autenticação para avaliar.
- Fechar a aba não para a sessão de voz. Encerrar o servidor chama a parada da sessão no `finally`. Estado e comandos temporários de mute usam arquivos no diretório temporário do sistema.
- Arquivos criados são limitados a nomes simples/extensões `.md` e `.txt`, confinados e sem sobrescrita. Leitura é restrita a Markdown e exige confirmação. Perfis de pessoas são limitados/normalizados e escritas exigem confirmação com versão concorrente.

### Chaves, criptografia, logs e retenção

O provedor de chave tenta ambiente, keyring e entrada interativa conforme a disponibilidade/configuração. Chave deve ter 32 bytes; HKDF-SHA256 deriva rótulos próprios para banco, auditoria, métricas e HMAC. SQLCipher protege os bancos que passam por `abrir_conexao`; erro de abertura não deve criar banco plaintext. Nenhum valor de chave foi lido ou incluído.

Limite relevante: ADR 0001 decide cifrar perfil e memórias sensíveis, mas os três documentos Markdown de perfil e perfis de pessoas continuam sendo arquivos, não tabelas SQLCipher. Não há diretório preenchido de criptografia de arquivos, assinatura ou integridade para os perfis Markdown. Chroma persiste separadamente e não recebe cifragem SQLCipher. Caches/modelos locais e o armazenamento do VoiceStudio estão fora dessa proteção do Alfred.

O código de ferramentas registra metadados, como operação, quantidade de bytes, tipo de erro e hash curto; voice logs registram progresso/tempos/erros. O código do painel registra requisições HTTP e pode registrar stack trace para exceção inesperada; não foi feita prova dinâmica de que todos os erros jamais incluam conteúdo. Nenhum log real foi aberto. Chroma, cache de modelos e logs não foram inspecionados; não atribuir cifragem ou política de retenção sem verificar.

Não há autenticação implementada em `seguranca/autenticacao/`. Registro de auditoria tem encadeamento e âncora, mas sua integração com todas as mutações de memória é lacuna declarada nos testes. A honestidade e confirmação ficam parcialmente no código (`nucleo/politicas`), mas o modelo ainda pode produzir resposta incorreta; os testes não foram executados agora.

Dependências que podem acessar rede em tempo de execução: download do Parakeet TDT v3 e de modelos do OpenWakeWord na primeira carga; chamadas da aplicação a APIs loopback de Ollama e VoiceStudio. A aplicação não realiza pesquisa externa no turno. O próprio VoiceStudio pode consultar atualizações ou baixar modelos, conforme ADR 0005; esse tráfego não foi iniciado nem verificado nesta auditoria.

### Riscos abertos, por gravidade

1. **Alto — dados de perfil no diretório de código.** Três arquivos Markdown com nomes pessoais aparecem sob `src/alfred/memoria/perfil/`; conteúdo não aberto, nomes omitidos e rastreamento Git **NÃO VERIFICADO** devido ao bloqueio Git.
2. **Alto — arquivos pessoais em texto claro.** `carregador.py` e `pessoas.py` carregam/gravam Markdown sem cifra; divergência da intenção do ADR 0001, que se refere a SQLCipher.
3. **Alto — testes podem ler preferências reais.** `carregar_configuracao()` verifica e abre preferência de voz sob `dados/`; `test_carrega_padroes_e_resolve_perfil_na_raiz` chama esse carregador sem redirecionar esse caminho. Por isso `pytest -q` não foi executado.
4. **Médio/alto — painel sem autenticação.** `interfaces/web/app.py`, `origem_local()` e `do_POST()`; loopback reduz exposição à rede, mas não isola processos locais.
5. **Médio — armazenamento vetorial e caches sem a cifra de SQLCipher.** `vetorial_chroma.py`, caminhos de cache de modelos e dados próprios do VoiceStudio. Retenção e cifragem efetivas não foram verificadas.
6. **Médio — processo de voz invisível no painel.** `PainelAlfred.iniciar_voz()` descarta stdout/stderr. Erros de dependência/modelo podem encerrar subprocesso sem diagnóstico direto visível no painel.
7. **Médio — memória depende de pré-requisitos locais.** A chave-mestra e o modelo de embeddings precisam estar disponíveis localmente; sem eles, o fluxo segue sem persistência ou recuperação naquela sessão.
8. **Médio — sem CSP e sem parada ao fechar aba.** Rotas state-changing e processo de voz permanecem ativos até parada explícita ou término do servidor.
9. **Baixo/médio — testes e configuração divergentes.** ADR 0005 registra duas falhas da execução padrão em validação anterior; uma referente a expectativa de perfil STT e outra à normalização de sigla. Ver seção 8.

## 7. Testes

**Suíte completa executada em 2026-10-23:** `python -m pytest --basetemp .codex-pytest-complete-all -m "not ao_vivo" -q` — **298 aprovados, 14 ignorados, 0 falhas**. Esse filtro inclui testes `integracao` e `lento`; testes `ao_vivo` ficam excluídos. O cenário Chroma anteriormente desmarcado também foi executado separadamente: **1 aprovado**.

O registro histórico no adendo de 2026-10-22 do ADR 0005 diz: 273 aprovados, 2 falhas, 21 ignorados e 3 desmarcados. Esse número é evidência documental de outra execução, não resultado desta auditoria. O mesmo registro atribui uma falha a divergência entre a expectativa de perfil STT do teste e a configuração documentada, e outra a `KeyError` no tratamento da lista de siglas do normalizador; não foram reproduzidas. O registro histórico também nota que a suíte então executada verificava se o arquivo pessoal existia e o abriria caso estivesse presente.

Contagem estática atual: 252 funções `test_*`; 13 declarações `@pytest.mark.skip`; três testes marcados em categorias filtráveis: dois `integracao` e um `lento`. A suíte acima incluiu todas essas categorias e excluiu `ao_vivo`.

Cobertura localizada inclui configuração, perfis, CLI, ferramentas, chaves, bancos, embeddings, Chroma, auditoria, métricas, Ollama, VoiceStudio e voz. Módulos sem teste específico localizado incluem painel web HTTP/browser, configurador Tk, carregador de pacote, política de esquecimento completa, geração de resumo e autenticação/criptografia de arquivos ausentes. Testes não demonstram execução em hardware/microfone, qualidade de voz ou Ollama real.

Marcadores: `lento`, `integracao`, `ao_vivo`. Scripts localizados: `auditar_memoria.py`, `avaliar_conversa.py`, `avaliar_honestidade.py`, `comparar_vozes.py`, `medir_voz.py`, `preparar_modelo_stt.py` e `iniciar_dependencias_locais.ps1`. Nenhum foi executado.

Validação focada da implementação em 2026-10-23: **101 aprovados, 1 desmarcado**, cobrindo RAG, distinção entre histórico indisponível e sem correspondência no CLI/voz, métricas, comandos de armazenamento, fontes, bancos, ranking e isolamento entre diretórios de perfil. A validação completa acima incluiu o teste de integração Chroma.

## 8. Decisões e documentação

| ADR | Decisão em resumo | Estado aparente |
|---|---|---|
| 0001 — criptografia do perfil e memórias sensíveis | SQLCipher para dados sensíveis em repouso; chave externa, backups cifrados. Arquivos Markdown observados não cumprem ainda a cobertura integral prometida | Vigente, implementação parcial |
| 0002 — perfis locais de pessoas | Markdown confinado, versão concorrente, normalização, escrita confirmada e contexto seletivo | Vigente, implementação ligada a ferramentas |
| 0003 — honestidade e procedência controladas pelo código | Regras essenciais antecedem perfil; ferramentas simuladas/falhas não contam como sucesso | Vigente, não é garantia absoluta |
| 0004 — voz natural e redução de latência | Ajustes de prompt, VAD, streaming, normalização e perfis STT; métricas sintéticas e metas explicitamente limitadas | Vigente, validação acústica pendente |
| 0005 — VoiceStudio como motor local | API local OpenAI-compatible, PCM e streaming; integração opcional com retentativa e fallback texto; estilo corrigido para `instructions` | Vigente, comparação perceptiva e confiabilidade pendentes |
| 0006 — operação dos armazenamentos locais | Fonte/derivação de chave, separação de finalidades, métricas e administração via CLI | Vigente, parte da memória conversacional não está conectada |

Títulos de seções do README: Desenvolvimento; Painel visual FUI; Administração dos bancos; Ollama e embeddings; Voz; Início rápido: assistente de voz; Instalação e modelos; Uso; Latência e memória; Exemplos informais; Criação de arquivos; Pessoas; Melhorias futuras; Honestidade e procedência; Avaliação com Ollama local; Voz natural: desempenho, ajustes e medição; Ajustes; Medição sintética; Vozes candidatas; Motor de voz VoiceStudio.

Divergências relevantes: o ADR 0001 é mais amplo que a proteção real dos arquivos de perfil; `pyproject.toml` inclui Piper no extra `voz`, mas o ciclo web de voz exige VoiceStudio; a captura automática usa o banco SQLCipher e o índice local quando a chave e o modelo estão disponíveis; o README e testes de memória descrevem uma suíte isolada, mas o teste de configuração pode abrir preferência real se presente. A documentação de voz traz resultados históricos e limitações, não prova que o VoiceStudio ou hardware estejam ativos agora.

## 9. Lacunas, dívidas e próximos passos

- **Não implementado:** serviço de resumidores, ciclo de esquecimento, autenticação, endpoints em `interfaces/api`, eventos/proatividade e detecção operacional de padrões.
- **Não implementado:** ciclo de esquecimento, comandos `/lembrar`, `/memorias`, `/fixar`, `/esquecer` e auditoria associada a cada alteração.
- **Operação confusa:** o iniciador tenta abrir Ollama e VoiceStudio, mas prossegue mesmo indisponíveis; não instala modelos. O painel descarta stdout/stderr do processo de voz.
- **Apresentação de respostas:** `ui/app.js` insere a resposta do Alfred como texto simples (`textContent`), por isso sintaxe Markdown aparece literal no balão. A solicitação para renderizar Markdown está registrada como pendência; não alterei a interface porque o escopo da auditoria permite criar somente este relatório.
- **Divergência de armazenamento:** Markdown sensível e Chroma ficam fora da cobertura SQLCipher; caches e retenção do VoiceStudio são independentes.
- **Módulos vazios:** diretórios de API, esquecimento, resumidores, proatividade, autenticação, criptografia, integridade e isolamento, além de fontes/notificações e eventos/modelos.
- **Arquivos de perfil sob código:** três Markdown com nomes pessoais em `src/alfred/memoria/perfil/`; conteúdo não lido, nomes omitidos. A relação com o carregador e o estado de rastreamento devem ser verificados sem incluir conteúdo em commits/logs.
- **TODO/FIXME:** busca estática não localizou marcadores `TODO`, `FIXME` ou `XXX` nos módulos Python e scripts consultados. Isso não exclui dívida documentada.
- **Git e trabalhos pendentes:** branch, histórico, diferenças e alterações pendentes são **NÃO VERIFICADOS** porque Git barrou as consultas. Não é possível deduzir tarefa interrompida por commits nesta auditoria.

Próximos passos técnicos sugeridos: tornar os testes de configuração isoláveis sem consultar dados reais; executar pytest apenas depois que essa leitura estiver isolada; decidir migração cifrada do perfil; remover/permanentemente excluir do diretório-fonte arquivos de perfil pessoais e revisar o índice Git; implementar gravação e comandos de memória com confirmação, auditoria e remoção em cascata; proteger endpoints com uma fronteira de sessão local; criar um caminho para logs visíveis de erros da sessão de voz.

## 10. O que esta auditoria não consegue saber

- Conteúdo, nomes de arquivos, integridade ou chaves de qualquer item sob `dados/`; nada foi aberto. Só metadados agregados da tabela da seção 1.
- Se o único arquivo sob `dados/bancos` é algum dos bancos esperados, seu esquema, sua integridade, número de registros, presença de Chroma ou se os componentes reais já foram inicializados.
- Valores reais de preferências, perfis, pessoas, documentos, logs, backups ou modelo de voz; conteúdo de `.env` e chave.
- Se Ollama/VoiceStudio estão ativos agora, modelos baixados ou versão atual dos aplicativos. Nenhum serviço foi consultado ou iniciado.
- Resultado atual de `pytest -q`; execução evitada pelo risco de leitura de dado real. Os números do ADR são apenas históricos.
- Estado Git, arquivos rastreados, branch, commits e alterações locais, pois Git bloqueou a consulta.
- RAM atual, latência de ponta a ponta, qualidade/Naturalidade, WER, falso acionamento, desempenho do microfone, barge-in ou VRAM por processo.
- Retenção interna, telemetria e cifragem dos dados próprios do VoiceStudio e dos caches de modelo.
- Tamanho do prompt com perfil real, comportamento de modelo real e qualidade semântica do RAG.

## 11. Varredura de sigilo

Relatório revisado para cadeias base64/hex longas, valores de segredo/configuração, contatos e documentos, credenciais em URL, caminhos com nome de usuário Windows, identificadores de perfil de voz e nomes próprios de pessoa. Nenhum conteúdo de perfil/dados foi incorporado. **Varredura de sigilo: concluída, 0 itens redigidos.**
