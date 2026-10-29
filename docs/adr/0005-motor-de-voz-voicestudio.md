# ADR 0005: VoiceStudio como motor local de síntese

- **Estado:** aceito para integração opcional; comparação perceptiva pendente.
- **Data:** 2026-10-17.

## Contexto

O Alfred precisava de uma alternativa local ao Piper que pudesse entregar áudio em blocos para reduzir o tempo até a primeira fala. O VoiceStudio já estava instalado e em execução na máquina. A integração deve manter o tráfego no loopback, evitar dependências novas e não alterar o comportamento de reconhecimento, privacidade ou confirmação de ações.

## Decisão

Adicionar um adaptador HTTP independente para a API OpenAI-compatible do VoiceStudio. O adaptador aceita somente URL HTTP em loopback, não segue redirecionamentos e solicita PCM mono de 16-bit a 24 kHz. O texto é enviado apenas ao servidor local durante a síntese e não é gravado pelo adaptador. O stream alimenta o mecanismo de saída existente; a próxima oração pode ser pré-sintetizada durante a reprodução da atual.

O VoiceStudio é selecionável por `ALFRED_TTS_MOTOR=voicestudio`. A configuração de exemplo mantém Piper como fallback; `ALFRED_TTS_FALLBACK=texto` permite continuar sem áudio quando o fallback não é desejado. O motor e a voz inicial (`omnivoice` e `alloy`) são provisórios, configuráveis e ainda não foram escolhidos por comparação auditiva. O Piper permanece selecionável diretamente. Nenhum pacote foi adicionado.

## Verificação local de Stage 0

Foi consultada somente a API local em `127.0.0.1:3900`, sem iniciar, reconfigurar ou atualizar o aplicativo. O `/health` respondeu versão `0.5.6` e informou CUDA com uma NVIDIA GeForce RTX 3070 Laptop GPU. A porta estava vinculada a `127.0.0.1`. O OpenAPI local informou `POST /v1/audio/speech`, `GET /v1/models` e `GET /v1/audio/voices`; os modelos TTS observados incluíam `tts-1`, `tts-1-hd` e `gpt-4o-mini-tts`. A documentação local descreveu `stream_format=audio` e PCM bruto a 24 kHz/16-bit/mono. O cliente não consulta a rota de vozes nem lê perfis salvos.

Uma síntese sintética de smoke test foi enviada pelo MCP local antes da implementação, sem reprodução. A chamada levou aproximadamente 10,53 s; o servidor informou cerca de 2,16 s de geração e 1,96 s de áudio. A voz efetivamente usada não foi confirmada e pode ter sido a seleção padrão do VoiceStudio; por isso esse resultado não valida nem recomenda uma voz. Nenhuma outra síntese real foi feita durante a implementação.

O endpoint `/system/info` informou RAM física total de 15,8 GB e VRAM total de 8,0 GB, valores de capacidade da máquina, não consumo atribuído ao VoiceStudio. O diretório declarado pelo aplicativo foi `%APPDATA%/OmniVoice`, com saída em `%APPDATA%/OmniVoice/outputs`. Não foram lidos arquivos desses diretórios, histórico, perfis, `.env`, `dados/` ou ADRs anteriores. A consulta de configurações de armazenamento não foi concluída; contagens/tamanhos de histórico e a existência de opção para desativá-lo permanecem desconhecidos.

## Privacidade, dependências e limites

- O Alfred não captura microfone nesta integração, não grava áudio sintetizado e não envia conteúdo a serviço hospedado. Frases de pré-aquecimento e exemplos de comparação são neutros e fictícios.
- VoiceStudio tem armazenamento e histórico próprios. O usuário deve rever retenção em Settings → Storage e proteger a unidade. A política exata dessa instalação não foi inspecionada.
- A instalação pode consultar GitHub para atualizações e downloads de modelos podem buscar arquivos externos. Isso é comportamento do aplicativo, não tráfego iniciado pelo adaptador Alfred. Telemetria do aplicativo não foi auditada.
- O aplicativo VoiceStudio declara AGPL-3.0-only; o projeto upstream OmniVoice declara Apache-2.0 para seus artefatos. Piper continua sob as licenças já documentadas no projeto. Verificar separadamente motor, modelo e voz antes de redistribuir.
- O cliente limita host e redirecionamentos, mas não substitui firewall ou isolamento do próprio VoiceStudio. Tempos limite e fallback reduzem o impacto de indisponibilidade.
- A seleção de motor/voz, naturalidade, sotaque, latência sob carga concorrente, memória atribuível, retenção e comportamento de atualização precisam ser avaliados no equipamento do usuário. A comparação incluída não toca nem persiste amostras por padrão.

## Validação da integração

Os testes unitários usam servidor HTTP falso em loopback e dados sintéticos; verificam validação de URL, recusa de redirecionamento, streaming, cancelamento, fallback, configuração, pronunciamento e comando `/voz`. A suíte completa é executada após a implementação. Não se inicia o Alfred, não se reproduz áudio e não se chama a síntese real durante essa validação.

## Referências

- [API local do VoiceStudio](https://voicestudio.sh/docs/local-api)
- [Guia de voz para agentes](https://github.com/debpalash/VoiceStudio/blob/main/docs/agentic-voice.md)
- [Licença do VoiceStudio](https://github.com/debpalash/VoiceStudio/blob/main/LICENSE)
- [Escolha de motor](https://voicestudio.sh/docs/engine-choice)

## Registro de validação — 2026-10-22

Este adendo preserva as decisões e observações históricas acima; não as substitui.

### Correção do contrato de estilo

Uma síntese com a configuração padrão do Alfred foi reproduzida como HTTP 500. O adaptador enviava prosa em português no campo `instruct`; o OmniVoice rejeitou o conteúdo com `Unsupported instruct items found`. A mesma prosa no campo OpenAI-compatible `instructions` retornou HTTP 200 e PCM. Sem instruções, o pedido também retornava HTTP 200. O adaptador agora envia estilo em `instructions`; o teste de regressão confirma o campo e rejeita `instruct`.

O adaptador também tenta restabelecer disponibilidade e saída de áudio na chamada seguinte após uma falha. Um teste com servidor falso devolve dois HTTP 500, depois sucesso, e confirma que a próxima síntese recupera sem manter o fallback ativo.

### Latência HTTP local

Medição feita em `127.0.0.1:3900`, com requests HTTP diretos, PCM lido apenas em memória e sem playback ou gravação. Cada condição teve um aquecimento descartado e dez medidas; p95 usa nearest-rank. O qwen3.5:4b ficou carregado na GPU e ocioso durante a medição. Foi usado o motor `omnivoice` e o `voice_id` `db4b64aa` do `config.yaml`, sem ler `dados/`. O carregador também pode aplicar preferências de `dados/perfil/voz_alfred.json`; como esse caminho não foi acessado, os números identificam a configuração versionada do projeto, não confirmam eventual override pessoal. `instructions` ligado usou o estilo definido em `config.yaml`; desligado omitiu o campo.

| `instructions` | TTFB mediana / p95 | Tempo total mediana / p95 | Áudio mediano / p95 | Fator de tempo real mediana / p95 |
|---|---:|---:|---:|---:|
| Desligado | 1,665 / 1,877 s | 2,174 / 2,493 s | 3,880 / 3,880 s | 0,569 / 0,642 |
| Ligado | 1,798 / 2,612 s | 2,327 / 3,203 s | 3,880 / 3,880 s | 0,600 / 0,880 |

VRAM total: **8192 MiB**. O alvo de TTFB de aproximadamente 400 ms e o fator de tempo real de até 0,5 não foram atingidos em nenhuma condição. A diferença entre condições é pequena na mediana; o tempo dominante é a geração/inferência do OmniVoice no servidor local, não o transporte de loopback. Não foi feita profilagem interna da GPU para separar inferência, agendamento e contenção.

### Recuperação, fallback e privacidade dos registros

- A recuperação atual ainda **não** tem timeout curto nem espera exponencial. `timeout_conexao_s` permanece configurável (padrão 3 s), `timeout_leitura_s` é 30 s, e a repetição HTTP ocorre uma vez com espera fixa de 250 ms. `_tentar_reativar` usa os timeouts normais na próxima chamada; a chamada da fila de voz é por frase, não por resposta completa. Logo, isso não garante ausência de atraso quando o endpoint fica silencioso nem impede reativação no meio de uma resposta.
- Não há voz alternativa configurada: o fallback aceito é `texto`. A mensagem de indisponibilidade é impressa uma vez por instância e a operação falha; não é falada por outra voz. O teste existente confirma apenas a mensagem impressa uma vez.
- Um teste novo envia sentinelas fictícias tanto no texto quanto em `instructions` e faz o servidor falso ecoá-las no erro. As sentinelas não aparecem na exceção nem nos logs do adaptador. Os registros ficam limitados a metadados. Os logs internos do VoiceStudio não foram lidos ou auditados.
- A prova de recuperação existente cobre a próxima chamada de síntese após duas respostas 500. Não prova timeout curto, backoff exponencial, aviso falado por voz alternativa ou fronteira de resposta completa.

### Situação da suíte

Na suíte padrão: **273 aprovados, 2 falharam, 21 ignorados, 3 desmarcados**. Os 17 testes específicos do adaptador VoiceStudio passaram. As duas falhas restantes foram investigadas sem alterar produção nem afrouxar asserções:

1. `test_carrega_padroes_e_resolve_perfil_na_raiz` espera `rápido`, mas o dataclass, o carregador, `config.yaml`, `.env.exemplo`, README e o perfil do transcritor estabelecem `preciso`. O teste está desatualizado em relação à configuração documentada. A correção proposta é alinhar a expectativa do teste com o padrão documentado, sujeita à aprovação do responsável pelo produto.
2. `test_normaliza_texto_para_fala` espera expandir `API` para nomes de letras em português. O normalizador inclui `API` e `AI` no regex, mas não no dicionário, causando `KeyError`. A falha imediata é do código. O comentário da implementação diz que `API` e `AI` devem permanecer intactas para a pronúncia inglesa instruída ao TTS; por isso a expectativa fonética atual do teste também conflita com a intenção documentada. A correção proposta é derivar o regex somente das chaves mapeadas e tratar siglas com uma tabela explícita: manter `API`/`AI` intactas para a leitura inglesa pretendida e cobrir `IA`, `GPS`, `URL`, `SMS`, `LLM`, `GPU`, `CPU`, `TTS`, `STT`, `SQL` e `USB` com pronúncias definidas, incluindo caixa, pontuação e limites de palavra. Nenhuma dessas alterações foi feita sem aprovação.

O Git está na branch `master`, sem commits; `git log` e `git diff` não permitem datar a introdução das falhas. Pelas datas de modificação disponíveis, `test_configuracao.py` e `test_voz.py` são de 2026-10-18; `configuracao.py`, `config.yaml` e `.env.exemplo` são de 2026-10-21; `texto_voz.py` também é de 2026-10-21. Isso sugere divergência posterior dos testes, mas não determina o primeiro dia em que passaram a falhar.

Os 21 testes ignorados são lacunas já marcadas como `não implementado`: seis de criação/extração/sumarização/padrões, oito de recuperação RAG no fluxo, três de auditoria/honestidade ligada ao serviço e quatro de ciclo de esquecimento. Não há skips por hardware ou rede nesta execução. Três testes marcados para execução lenta/integração/ao vivo foram desmarcados pela configuração padrão do pytest.

**Limite de privacidade da validação:** a medição HTTP e os testes específicos do adaptador não leram `dados/`. A suíte completa também executou um teste de configuração que chama `carregar_configuracao()`; esse carregador verifica se `dados/perfil/voz_alfred.json` existe e o abriria se presente. Não foi possível determinar sem tocar nesse caminho se o arquivo estava presente durante a execução. Portanto, a suíte completa não pode ser certificada como isolada de `dados/`; novas execuções amplas devem primeiro substituir ou isolar esse acesso.
