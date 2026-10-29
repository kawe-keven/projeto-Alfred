# Alfred

Projeto de assistente pessoal modular. O backend Python fica em `src/alfred`, a interface web em `ui/` e os dados locais em `dados/`.

O perfil pessoal e as memórias sensíveis devem ser armazenados em banco criptografado com SQLCipher. A chave-mestra de 32 bytes é fornecida em base64 por `ALFRED_SQLCIPHER_CHAVE` ou digitada em leitura oculta no terminal. Nunca é registrada em logs ou gravada pelo Alfred.

O armazenamento vetorial será encapsulado pela interface `RepositorioVetorial`, com Chroma como implementação. O banco relacional fica em `dados/bancos/alfred.db`, e o índice do Chroma em `dados/bancos/chroma/`; esses dados locais são ignorados pelo Git.

## Desenvolvimento

```bash
python -m venv .venv
pip install -e .
```

### Painel visual FUI

Inicie `iniciar_alfred_visual.bat` no Windows ou execute `python -m alfred.interfaces.web.app` no ambiente do projeto. O painel abre em `http://127.0.0.1:8765` e oferece a sessão CLI, o controle do ciclo de voz e os ajustes de voz do VoiceStudio. A interface escuta somente em loopback; as preferências de voz são compartilhadas com o configurador atual em `dados/perfil/voz_alfred.json`.

O painel precisa do Ollama local para conversar e do VoiceStudio aberto para carregar perfis e ouvir prévias. Iniciar uma sessão de voz também requer as dependências opcionais de voz instaladas e os respectivos modelos locais disponíveis.

Copie `.env.exemplo` para `.env` para configurar integrações locais, mas não grave a chave SQLCipher nesse arquivo. Não defina `ALFRED_SQLCIPHER_CHAVE` permanentemente no perfil do usuário nem use `setx`; não cole a chave numa linha de comando, onde pode ficar no histórico. Prefira a leitura oculta. Um agente executado como o mesmo usuário pode ler uma variável de ambiente definida. Os diretórios em `dados/` são locais e não devem ser versionados.

### Administração dos bancos

`python -m alfred.interfaces.cli.armazenamento --help` lista os comandos `gerar-chave`, `configurar-chave`, `restaurar-chave`, `criar`, `status`, `verificar`, `backup`, `reindexar` e `limpar-metricas`. `gerar-chave` mostra uma chave base64 uma única vez e não a salva; proteja-a ao copiá-la. `configurar-chave` cria uma chave e bancos apenas numa instalação nova. Se o banco já existe e a chave original foi perdida do cofre, `restaurar-chave` solicita essa chave em entrada oculta, valida-a contra o banco e só então a guarda no cofre do Windows; uma chave errada não altera o cofre. Esse comando não recupera nem substitui uma chave perdida. Os comandos usam `dados/bancos/` por padrão. `criar` prepara todos os bancos administrativos; a conversa cria o banco principal cifrado e o índice local quando a chave está disponível. Para outros destinos, passe `--diretorio CAMINHO` antes do subcomando. `backup` recebe o caminho do diretório de destino. A retenção de métricas padrão é 90 dias.

`ALFRED_DIRETORIO_BANCOS` pode selecionar uma pasta de armazenamento independente. Por padrão, CLI, voz, painel e administração usam `dados/bancos/`; bancos locais anteriores em `dados/bancos_alfred/` e `dados/bancos_recuperacao*/` também são consultados nas buscas por conversas antigas, desde que estejam acessíveis com a chave-mestra original.

Com uma chave-mestra disponível, o Alfred prepara automaticamente o banco principal cifrado e o índice local ao iniciar. O CLI pode solicitar a chave em entrada oculta; para iniciar pelo painel web ou ciclo de voz, configure a variável de ambiente ou o cofre do sistema. Turnos concluídos no CLI e na voz são gravados no SQLCipher e indexados com o modelo de embeddings local do Ollama; conteúdo não é enviado a serviços externos. O modelo de embeddings precisa já estar instalado. Sem a chave, a conversa segue sem persistência; se a chave estiver disponível mas o modelo não, o turno é gravado cifrado e sua indexação é retomada quando o modelo estiver disponível. A sessão de voz e a CLI usam o mesmo armazenamento local.

O keyring do sistema é instalado com as dependências principais e guarda chaves e credenciais no cofre do Windows. Para habilitar painel e voz com uma chave que ainda não esteja no cofre, use `restaurar-chave`; o comando valida a chave contra o banco antes de guardá-la. O agente executado como o mesmo usuário pode acessar as credenciais enquanto a aplicação as mantém em memória. Veja [Integrações](docs/INTEGRACOES.md) para configurar SMTP e [ADR 0006](docs/adr/0006-armazenamento-operacional.md) para detalhes sobre as chaves locais.

## Ollama e embeddings

O modelo de conversa e resumos configurado é `qwen3.5:4b`. A memória pode usar `qwen3-embedding:0.6b` pela API local de embeddings do Ollama. Não baixe modelos sem aprovação explícita; este repositório não executa downloads de modelos.

`ALFRED_OLLAMA_URL` deve apontar para `http://localhost:11434`; URLs externas são recusadas. `ALFRED_MODELO` seleciona o modelo de conversa e `ALFRED_MODELO_EMBEDDINGS` seleciona o modelo de embeddings. O gerador de embeddings envia lotes limitados por `ALFRED_EMBEDDINGS_LOTE` (padrão `32`) e usa `ALFRED_EMBEDDINGS_NUM_GPU=0` para deixar o cálculo na CPU; `ALFRED_EMBEDDINGS_THREADS` controla as threads (padrão `4`). `ALFRED_EMBEDDINGS_KEEP_ALIVE` controla por quanto tempo o modelo permanece na memória (padrão `1m`).

## Voz

A camada de voz é opcional e local. Ela usa `prompts/system.txt` junto às políticas e ao perfil existente para montar o prompt e mantém o histórico da conversa em memória. Silero VAD descarta trechos que não parecem voz humana, e o STT aplica redução de ruído, evita decodificar silêncio e usa por padrão NVIDIA Parakeet TDT v3 via sherpa-onnx em CPU. O modelo reconhece automaticamente 25 idiomas europeus, incluindo português; a qualidade em português brasileiro deve ser avaliada com a própria voz. O arquivo `dados/logs/voz.log` registra horário, evento e resultado, sem armazenar o texto da conversa. Logs criados por versões anteriores ainda podem conter frases e devem ser protegidos ou removidos manualmente. `--debug` salva áudio de entrada e transcrições localmente para avaliação do STT somente quando solicitado.

## Início rápido: assistente de voz

Requer Python 3.11, Ollama local e o VoiceStudio desktop aberto. A configuração do fluxo fica em `config.yaml`; valores `ALFRED_*` do ambiente têm precedência. O prompt de voz está em `prompts/system.txt`.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull qwen3.5:4b
python -m alfred.interfaces.ciclo_de_voz --modo conversa
```

Para instalar o pacote de forma editável no Windows, o `-e .` de `requirements.txt` inclui o projeto e seus requisitos básicos. O Parakeet usa ONNX quantizado e roda na CPU; a transcrição não exige NeMo nem PyTorch.

Use `python -m alfred.interfaces.ciclo_de_voz --debug` para gravar cada fala em `dados/debug_voz/fala-*.wav` e a transcrição correspondente em `.txt`. Esses arquivos contêm dados pessoais; apague-os depois da avaliação.

O ciclo captura áudio mono a 16 kHz em blocos de 20–30 ms, detecta fala com Silero e encerra após cerca de 300 ms de silêncio. A transferência do callback de áudio e a fila de eventos do Ollama são limitadas para conter crescimento de memória sob sobrecarga; frames antigos podem ser descartados para manter a captura em tempo real. Para limitar memória, um turno contínuo é dividido automaticamente após 120 segundos. O STT usa `nvidia/parakeet-tdt-0.6b-v3` via sherpa-onnx com pesos ONNX int8. O modelo reconhece automaticamente português entre 25 idiomas; o primeiro download ocupa cerca de 640 MB e depois funciona offline. O Ollama envia tokens em streaming e, em voz, libera trechos curtos antes da pontuação para começar o TTS mais cedo; a ponte mantém no máximo quatro eventos pendentes e aplica contrapressão. VoiceStudio usa o perfil `66b001cc`, criado da referência fornecida. O estilo de voz via `instructions` fica ligado por padrão para orientar ritmo de conversa, pausas e entonação natural; defina `ALFRED_VOICESTUDIO_ESTILO` vazio para desativá-lo. Se VoiceStudio falhar, Piper Faber entra como fallback. Também criei no VoiceStudio o perfil `66ca3722` a partir de uma amostra do Piper Faber; isso não treina Faber para imitar a gravação original, portanto a troca de motor ainda pode mudar o timbre. Pronúncias ficam em `src/alfred/configuracao/pronuncias.toml`.

Os tempos de primeira palavra transcrita, primeiro token, primeira frase completa e primeiro áudio (contado desde o fim da fala) são mostrados no terminal no encerramento, com mediana e p95. A meta de 1,2 s depende da máquina e dos modelos já aquecidos; ela não é garantida por configuração.

### Instalação e modelos

Use o mesmo Python do projeto (Python 3.14 no Windows):

```powershell
pip install -e ".[voz,dev]"
ollama pull qwen3.5:4b
```

Piper Faber é carregado como fallback local da interface de voz quando configurado.

O extra `voz` instala `numpy` para os frames de áudio, `sounddevice` para captura/reprodução, `silero-vad` e `torch` para detectar fala, `onnxruntime` para os modelos ONNX, `openwakeword` como detector substituível, `sherpa-onnx` para Parakeet TDT v3 e `piper-tts` para síntese. `faster-whisper` continua disponível como alternativa configurável. `dev` fornece pytest. As versões consultadas publicam wheels para Windows/Python 3.14 para os componentes principais; instalação e execução ainda dependem do ambiente e dos drivers locais.

Na primeira carga, Parakeet e o placeholder de palavra de ativação podem baixar seus pesos para o cache local. Isso baixa somente modelos; nenhum áudio, transcrição ou perfil é enviado.

Para baixar antecipadamente o Parakeet, feche o Alfred e execute `python scripts/preparar_modelo_stt.py` no ambiente virtual do projeto. O comando guarda os pesos ONNX em `dados/modelos/`; a inicialização seguinte reutiliza esses arquivos.

O Piper foi escolhido por funcionar localmente, mas o mecanismo é GPL-3.0-or-later. A voz `pt_BR-faber-medium` está disponível em português brasileiro; confira a licença do artefato e os termos do projeto antes de redistribuí-lo. O pacote oferece o comando de download acima. Os arquivos de voz devem permanecer locais e fora do Git.

### Uso

```powershell
python -m alfred.interfaces.ciclo_de_voz
```

O padrão é push-to-talk: pressione espaço (ou Enter), espere a mensagem “Pode falar agora”, fale e aguarde o Alfred. Pressione `m` para alternar o mudo; `m` novamente reativa a escuta. O comando de voz `/mudo` também silencia.

Para conversar sem segurar espaço, ative o modo contínuo enquanto a sessão estiver aberta. O Alfred mantém a captura local, encerra o turno com VAD e pode ser interrompido por fala:

```powershell
python -m alfred.interfaces.ciclo_de_voz --modo conversa
```

Pressione `m` para silenciar ou `Ctrl+C` para encerrar a sessão. O modo contínuo começa a escutar assim que o aplicativo abre.

Para usar o placeholder de palavra de ativação:

```powershell
$env:ALFRED_VOZ_MODO = "palavra"
python -m alfred.interfaces.ciclo_de_voz
```

`ALFRED_PALAVRA_ATIVACAO=Alfred` registra a palavra desejada para o modelo futuro. O modelo pré-treinado configurado por `ALFRED_MODELO_ATIVACAO=hey_jarvis` reconhece “Hey Jarvis”, não “Alfred”; por isso push-to-talk é o modo padrão. OpenWakeWord distribui pesos pré-treinados sob condições próprias (incluindo licença não comercial para os pesos indicados pelo projeto). O código do Alfred não baixa nem envia áudio para nuvem. Para um modelo próprio, reúna amostras positivas da frase “Alfred” e negativas com fala e ruído ambiente, treine conforme o [guia oficial do OpenWakeWord](https://github.com/dscripka/openWakeWord), revise a licença dos dados e pesos, salve o modelo ONNX localmente e configure `ALFRED_MODELO_ATIVACAO` com o caminho do arquivo. A interface `DetectorDePalavraDeAtivacao` permite trocar o motor.

Configurações de voz estão em `.env.exemplo`: `ALFRED_STT_ENGINE` (`parakeet` por padrão; também `faster-whisper`), `ALFRED_VOZ_MODO` (`apertar`, `palavra` ou `conversa`), `ALFRED_STT_MODELO` (identificador do modelo; a versão ONNX é fixada pelo backend), `ALFRED_STT_DISPOSITIVO` (usado por faster-whisper; Parakeet ONNX usa CPU), `ALFRED_STT_PERFIL` (padrão `equilibrado`; também aceita `rápido` ou `preciso`), `ALFRED_STT_COMPUTE_TYPE` (usado por faster-whisper), `ALFRED_STT_VOCABULARIO`, `ALFRED_VOZ_HISTORICO`, `ALFRED_VAD_LIMIAR_INICIO`, `ALFRED_VAD_LIMIAR_FIM` e `ALFRED_BARGE_IN_PALAVRA`. Parakeet detecta o idioma automaticamente; o pré-processamento local reduz ruído estacionário e normaliza o nível antes da transcrição. O ajuste de velocidade da síntese não altera o timbre. O barge-in usa um limiar VAD mais alto durante a fala; habilitar `ALFRED_BARGE_IN_PALAVRA=true` exige a palavra detectada para interromper. Fones de ouvido reduzem o risco de o áudio do alto-falante disparar a interrupção.

Na inicialização, o Alfred carrega Parakeet, Silero e Piper e começa a escutar sem esperar o aquecimento do Ollama. Esse é o padrão para o microfone ficar disponível mais cedo; a primeira resposta pode demorar enquanto o modelo de conversa é carregado. Para aquecer antes de abrir o microfone, use `python -m alfred.interfaces.ciclo_de_voz --aquecer-modelo`; essa etapa pode levar alguns minutos dependendo do computador.

`--debug` exibe um aviso antes de mostrar transcrições e nomes de ferramentas no console, e salva as amostras de fala e transcrições para avaliação em `dados/debug_voz/`.

### Latência e memória

A meta é menos de 1,5 segundo entre o fim da fala e o primeiro áudio, não uma garantia. Ao encerrar com Ctrl+C, o resumo dos tempos por etapa (fim da fala até transcrição, primeiro token, frase e áudio) informa mediana e pior caso no log, sem conteúdo da conversa. Faça uma medição local após os modelos carregarem, anotando modelo, dispositivo, `compute_type`, duração da amostra, mediana/pior caso e memória de GPU antes e durante o turno. A memória de GPU pode ser medida pelo Monitor de Tarefas ou `nvidia-smi`; compare com Ollama já carregado porque ambos compartilham VRAM. Esta implementação ainda não foi medida com modelos reais neste ambiente.

O adaptador do VoiceStudio reproduz PCM progressivamente após um pré-buffer de cerca de 170 ms, sem esperar a frase inteira. A fila de reprodução é limitada e permite pré-sintetizar a próxima frase enquanto a atual toca. Isso reduz o atraso e as pausas entre frases; naturalidade, continuidade do áudio e latência ainda precisam ser medidas juntas no equipamento alvo.

### Exemplos informais

1. “Tá escuro aqui, dá uma luz aí.” O Alfred pede ou infere o cômodo se houver contexto; a ferramenta apenas simula o controle.
2. “Aumenta mais um pouco.” Usa a última interação e o resultado da ferramenta no histórico em memória para esclarecer ou simular o ajuste.
3. “E amanhã?” Usa o contexto anterior; se não houver referência suficiente, pergunta a que compromisso ou horário a pessoa se refere.
4. “Me lembra de pagar a conta amanhã cedo.” Confirma o horário quando necessário e apenas exibe a simulação do lembrete.
5. “Liga para a Ana.” O Alfred pergunta “Quer que eu ligue para Ana? Diga sim ou não.” Só a próxima fala clara “sim” autoriza a simulação; “não”, resposta ambígua ou silêncio cancelam.

### Criação de arquivos

Na CLI e na interface de voz, o Alfred pode criar documentos Markdown ou texto em `dados/arquivos`. Peça o nome e o conteúdo desejado; cada criação bem-sucedida é anunciada pelo Alfred. A ferramenta não aceita caminhos fornecidos pelo modelo e não sobrescreve arquivos existentes. A pasta aceita até 200 arquivos e 20 MB por padrão, com limites configuráveis. Para ler um documento Markdown dessa pasta, peça ao Alfred que use a ferramenta `ler_arquivo`; o código solicita a mesma confirmação explícita antes da leitura. Ela só acessa `dados/arquivos`, nunca os perfis principais ou os perfis de pessoas.

### Pessoas

O Alfred mantém perfis de pessoas em `dados/perfil/pessoas/`, separados dos três arquivos do perfil principal. Peça para criar um perfil e informe o nome, a relação, apelidos e fatos que deseja guardar. Antes de qualquer escrita, o código apresenta o conteúdo normalizado que será gravado ou removido e aguarda sua confirmação explícita. `listar` e `ver` são leituras sem confirmação; os dados retornados são marcados como dados, nunca como instruções. Para remover um perfil, peça para apagar o perfil da pessoa e confirme depois de revisar o resumo completo.

Os fatos são gravados em uma linha, com a tag `[declarado]` inserida pelo código depois da confirmação. O Alfred recusa documentos pessoais, dados bancários, senhas e códigos de segurança. Ao conversar, ele procura nomes, apelidos e relações citados na mensagem e envia ao modelo no máximo três perfis selecionados; perfis não selecionados não entram no prompt. A seleção por “ela” só ocorre quando há uma única pessoa cadastrada com relação feminina suportada. Os arquivos ficam em texto claro; mantenha a pasta em uma unidade protegida pelo BitLocker ou cifra equivalente e restrinja o contexto a informações de relacionamento. Os dados de terceiros não implicam consentimento deles.

**Mudança incompatível:** `usar_arquivo_perfil` agora é exclusivo para operações com perfis de pessoas. O comportamento antigo de ler um `.md` em `dados/arquivos/` foi movido para a ferramenta somente leitura `ler_arquivo`, com confirmação e limites equivalentes.

### Melhorias futuras

- Integração real com casa inteligente e agenda, com permissões específicas.
- Reconhecimento do falante e cancelamento de eco.
- Modelo de ativação “Alfred” treinado e revisado quanto à licença.
- Integração com memória de longo prazo e proatividade, fora do escopo atual.

## Honestidade e procedência

A política essencial de honestidade fica no código e antecede as preferências e os demais dados do perfil. O manifesto da sessão é derivado das ferramentas registradas. Resultados de ferramentas são marcados com estado e origem; simulações e falhas não confirmam uma ação real. Alegações de ação reconhecidas ficam retidas até validação, com no máximo uma tentativa de revisão. A verificação reduz afirmações sem suporte, mas não garante que o modelo nunca erre.

No CLI, use `/fontes` depois de uma resposta para ver quais fontes e contextos foram disponibilizados naquele turno. Uma busca pessoal sem correspondência recebe um marcador explícito. Pedidos sobre notícias, preços, leis e outros fatos instáveis são sinalizados quando não há ferramenta de pesquisa externa registrada; data e hora local não comprovam esses fatos.

### Avaliação com Ollama local

Os cenários em `testes/cenarios/honestidade.yaml` usam somente nomes e situações fictícias. O avaliador cria ferramentas falsas: uma simula uma ação e outra sempre falha sem gravar arquivos. Ele não carrega o perfil real nem escreve em `dados/`.

Depois de iniciar o Ollama local e instalar as dependências do projeto, execute:

```powershell
python scripts/avaliar_honestidade.py
```

Opcionalmente, informe outro modelo local com `--modelo`. O resultado automático é apenas uma triagem por frases esperadas; revise as respostas manualmente. Não é uma garantia de honestidade nem substitui testes de segurança.

Os testes unitários usam provedores e dados fictícios e não iniciam Ollama. Para executá-los, use `python -m pytest`.

## Voz natural: desempenho, ajustes e medição

Os ajustes de voz priorizam fala concisa, pausas mais naturais e resposta rápida sem alterar as regras de honestidade ou confirmação. O estilo oral vale apenas na interface de voz. O reconhecimento rápido cobre padrões conservadores; pedidos ambíguos e ferramentas sensíveis seguem para o agente normal.

### Ajustes

Os valores ficam em `.env.exemplo` e podem ser sobrescritos no ambiente:

- `ALFRED_VOZ_OLLAMA_KEEP_ALIVE=2m`, `ALFRED_VOZ_NUM_CTX=4096` e `ALFRED_VOZ_NUM_PREDICT=96` controlam a permanência e os limites do Ollama. O modelo é liberado mais cedo quando a sessão fica ociosa; a próxima resposta pode levar mais tempo para carregá-lo. O contexto é um ponto de partida, não uma garantia de desempenho para todos os modelos.
- `ALFRED_STT_PERFIL=preciso` seleciona beam size oito para priorizar o reconhecimento; `equilibrado` (padrão, beam size cinco) oferece balanço entre precisão e tempo, e `rápido` reduz a latência. O inicializador de teste usa as definições de `config.yaml` sem sobrescrever o modelo ou o dispositivo.
- `ALFRED_VAD_SILENCIO_COMPLETO_MS=600` (padrão) e `ALFRED_VAD_SILENCIO_HESITACAO_MS=800` ajustam o fim de fala e evitam encerrar em pausas curtas. `ALFRED_VAD_LIMIAR_INTERRUPCAO=0.8` e `ALFRED_VAD_INTERRUPCAO_MINIMA_MS=120` fazem o Alfred ceder a vez mais cedo; fones de ouvido reduzem falsos acionamentos pelo eco dos alto-falantes.

Fones de ouvido ajudam a evitar que a própria saída do Alfred seja reconhecida como interrupção. Esses valores são iniciais: VAD e interrupção precisam ser ajustados com avaliação controlada no ambiente de uso.

### Medição sintética

`python scripts/avaliar_conversa.py` mostra 20 frases fictícias e uma matriz vazia para avaliação manual. Não captura nem reproduz áudio.

`python scripts/medir_voz.py --whisper-local CAMINHO_DO_MODELO` sintetiza frases fictícias em memória e compara os perfis de STT, WER e tempos. Requer um modelo faster-whisper já existente no caminho indicado e um modelo Piper local configurado por `ALFRED_PIPER_MODELO` (ou `--piper-modelo`). Não baixa modelos, não acessa rede, não usa microfone ou alto-falante e não grava transcrições. Sem os modelos locais, a medição não pode ser executada.

Ao avaliar latência de uma sessão real, registre somente tempos agregados por etapa, configuração, mediana, p95 e pior caso. Não grave áudio, transcrição, resposta ou conteúdo de perfil. A GPU é compartilhada com o Ollama; compare a memória total antes e durante a sessão, sem interpretar esse total como VRAM atribuível aos modelos.

### Vozes candidatas

As alternativas abaixo foram comparadas por disponibilidade e licença publicada, não por audição ou benchmark neste ambiente. Os tamanhos são arquivos de checkpoint; latência, VRAM e naturalidade não foram medidos.

| Voz | Tamanho do checkpoint | Licença do artefato | Situação |
|---|---:|---|---|
| Piper `pt_BR-faber-medium` | 63,2 MB | MIT; mecanismo Piper GPL-3.0-or-later | Configuração atual |
| Piper `pt_BR-edresson-low` | 63,1 MB | MIT; mecanismo Piper GPL-3.0-or-later | Alternativa a avaliar; configuração indica 16 kHz |
| Kokoro 82M, vozes pt-BR | 327 MB | Apache-2.0 | Candidato para comparação local futura |

Fontes oficiais: [Piper: catálogo e licenças](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md), [Faber ONNX](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx), [Edresson ONNX](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/edresson/low/pt_BR-edresson-low.onnx), [Kokoro: código](https://github.com/hexgrad/kokoro) e [catálogo de vozes Kokoro](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

Não foi adicionada dependência nem baixado ou substituído modelo. O Piper continua sendo a voz configurada até uma comparação local controlada de qualidade, latência e memória.

Consulte a decisão e as medições em [ADR 0004](docs/adr/0004-voz-natural-e-latencia.md).

## Motor de voz VoiceStudio

O Alfred usa o VoiceStudio local em `127.0.0.1:3900` com o perfil `66b001cc`, criado a partir do áudio de referência enviado. O perfil `66ca3722` guarda uma amostra do Piper Faber no VoiceStudio. O cliente rejeita redirecionamentos e não configura, inicia, atualiza ou instala nada no VoiceStudio.

O VoiceStudio usa sempre a voz configurada em `ALFRED_VOICESTUDIO_VOZ`. Cada solicitação envia a mesma seed para reduzir variação entre frases. O estilo conversacional via `instructions` fica ativo por padrão; ajuste ou desative com `ALFRED_VOICESTUDIO_ESTILO`. Se VoiceStudio falhar, Piper Faber assume; a semelhança é aproximada e não garante o mesmo timbre.

Abra `iniciar_configurador_voz.bat` para usar o painel visual. Ele lista os motores disponíveis e os perfis de voz locais, permite ouvir uma frase neutra de prévia e salva as escolhas em `dados/perfil/voz_alfred.json`. Feche e reabra o Alfred depois de salvar. A altura e a estabilidade não têm controles numéricos na API do VoiceStudio; a identidade de voz é determinada principalmente pelo perfil selecionado.

O primeiro uso verifica versão e disponibilidade, abre o stream de saída e pré-aquece frases neutras em memória. Durante uma resposta, o VoiceStudio pode enviar PCM em blocos; a próxima oração é pré-sintetizada enquanto a atual toca. Se o serviço falhar, Piper Faber fala a resposta como fallback. `/voz` no CLI mostra somente metadados do motor local.

Para comparar sem tocar nem gravar áudio, com o extra `voz` e o modelo Piper já instalado, execute `python scripts/comparar_vozes.py`. Ele usa frases fictícias, aliases embutidos e apenas motores que já aparecem na API local; nunca instala motores nem lista perfis de voz salvos. Para ouvir as amostras e digitar notas, use `--avaliar-audio` somente quando quiser reproduzi-las. Rode a comparação com Ollama e Whisper no estado de uso que deseja avaliar: RAM e VRAM são totais da máquina, não consumo atribuído a um modelo.

O Alfred não grava o áudio sintetizado. O VoiceStudio mantém armazenamento próprio; a instalação consultada declarou `C:\Users\keven\AppData\Roaming\OmniVoice` como diretório de dados e `C:\Users\keven\AppData\Roaming\OmniVoice\outputs` como pasta de saída. Gerencie histórico e retenção em Settings → Storage. O Alfred não lê nem limpa esses dados. Esta execução não verificou contagens/tamanhos por categoria nem uma opção para desligar completamente o histórico. Proteja a unidade com BitLocker ou cifra equivalente.

A API local documentada usa `POST /v1/audio/speech`, com `input` no corpo JSON e formatos como WAV e PCM; PCM é entregue a 24 kHz, 16-bit, mono. A instalação 0.5.6 também expôs `/v1/audio/voices` e `/v1/models`; o painel consulta os motores disponíveis e os perfis de voz anunciados localmente. Veja a [referência da API local](https://voicestudio.sh/docs/local-api) e o [guia de voz para agentes](https://github.com/debpalash/VoiceStudio/blob/main/docs/agentic-voice.md).

VoiceStudio é distribuído sob AGPL-3.0-only; o Alfred conversa com o app como processo separado por HTTP e não copia código dele. Antes de distribuir o Alfred, reavalie as implicações da AGPL e a licença do motor e da voz que forem escolhidos. A instalação local pode consultar GitHub para atualizações e o usuário pode iniciar downloads de modelos; isso pertence ao próprio VoiceStudio e não é uma chamada do Alfred. O Alfred não usa o serviço Cloud. Consulte [ADR 0005](docs/adr/0005-motor-de-voz-voicestudio.md) para o estado da verificação, limites de privacidade e medições pendentes.
# Mapa offline de Sergipe

O painel inclui um mapa local de Sergipe sob demanda, centralizado em Aracaju e sem geolocalização. Consulte [docs/mapa-offline.md](docs/mapa-offline.md) para preparar a base PMTiles e o runtime MapLibre local. Os lugares são guardados no banco cifrado quando a chave SQLCipher está disponível; caso contrário, permanecem apenas na memória do processo. Criação, edição, movimentação e remoção exigem confirmação.
