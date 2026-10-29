# ADR 0004: Voz natural e redução de latência

- Estado: aceito
- Data: 2026-10-16

## Contexto

A interface de voz precisava reduzir pausas, responder melhor a hesitações e produzir fala mais natural sem remover as proteções do agente. A avaliação desta etapa foi limitada ao código, testes sintéticos e chamadas locais ao Ollama com frases fictícias. Não foram usados microfone, áudio real, reprodução de áudio ou dados de `dados/`.

O ambiente expôs uma GeForce RTX 3070 Laptop com 8192 MiB de VRAM; a ferramenta do sistema indicou 1949 MiB em uso na primeira observação. Não foi possível obter a RAM total do sistema, nem atribuir o uso da GPU a cada processo/componente. A configuração existente do Whisper é `base`, CPU, `int8`; Piper está configurado para `pt_BR-faber-medium`.

## Medições

Cinco chamadas locais ao Ollama, usando somente prompt sintético, apresentaram primeiro token em 12258, 2179, 2249, 2161 e 2152 ms. A mediana foi 2179 ms e o pior caso 12258 ms. Com `num_ctx=8192`, `num_predict=144` e `keep_alive=30m`, os valores foram 12303, 2176, 2237, 2142 e 2166 ms: mediana 2176 ms e pior caso 12303 ms. A primeira chamada fria domina o pior caso; a mediana quente permaneceu em torno de 2,18 s. Isso mede somente o Ollama, não o caminho completo de voz, e a meta de primeiro áudio abaixo de 1 s não foi atingida.

O prompt sintético usado para comparar a compactação caiu de 1268 para 1151 tokens (5388 para 4852 caracteres), aproximadamente 9,2%. Isso não representa uma contagem do perfil privado nem de uma conversa real. Não foi possível medir WER com Whisper, latência do Piper, qualidade acústica, primeiro áudio real ou VRAM por componente: os modelos locais não foram carregados para esse teste.

## Decisão

- Manter o processamento local e o provedor Ollama atual. Configurar `keep_alive=30m`, `num_ctx=8192` e `num_predict=144`, todos ajustáveis por ambiente. `num_ctx=8192` é um ponto inicial conservador, não um valor validado para todos os modelos.
- Aquecer o modelo com uma mensagem fictícia curta depois da inicialização dos modelos de voz e antes de iniciar captura.
- Compactar instruções repetitivas do prompt e deixar data/hora volátil ao fim do prompt de sistema, preservando regras de honestidade, confirmação e validação de ferramentas.
- Aplicar estilo oral apenas na interface de voz. Adicionar reconhecimento rápido somente para padrões conservadores e ferramentas não sensíveis; os caminhos rápidos continuam sujeitos à mesma política de confirmação, validação e verificação.
- Usar VAD adaptativo: silêncio mais curto para fala completa e pausa maior em hesitações ou frases incompletas. Exigir evidência mais forte para interromper o TTS. Esses parâmetros são iniciais e ainda precisam de avaliação em uso consentido.
- Normalizar números, datas, horários, moeda, unidades, siglas e URLs antes de sintetizar. Manter uma única saída de áudio aberta e preparar a próxima frase enquanto a atual é reproduzida.
- Manter perfis de STT `rápido`, `equilibrado` e `preciso`, sem condicionar a transcrição ao texto anterior. Vocabulário privado é carregado em memória e não é registrado.
- Disponibilizar medições e avaliações sintéticas que não abrem microfone, alto-falante ou rede e não salvam transcrição.

## Alternativas de voz

Nenhuma alternativa foi baixada, instalada ou ouvida. Tamanhos abaixo são dos arquivos de checkpoint consultados; tempo de inferência, qualidade percebida e VRAM não foram medidos neste computador.

| Opção | Evidência disponível | Licença consultada | Decisão |
|---|---|---|---|
| Piper `pt_BR-faber-medium` | ONNX de 63,2 MB; voz brasileira disponível | Arquivo MIT; mecanismo Piper GPL-3.0-or-later | Manter como configuração atual |
| Piper `pt_BR-edresson-low` | ONNX de 63,1 MB; amostragem de 16 kHz indicada na configuração | Arquivo MIT; mecanismo Piper GPL-3.0-or-later | Alternativa leve a avaliar; qualidade não comparada |
| Kokoro 82M | Checkpoint de 327 MB; catálogo inclui vozes `pt_BR` | Apache-2.0 | Candidato para comparação futura; maior arquivo não implica maior qualidade ou latência |
| MeloTTS | A lista oficial de idiomas consultada não inclui português | Projeto MIT | Não selecionado para pt-BR |

Fontes oficiais: [catálogo e licenças de vozes Piper](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md), [checkpoint Piper Faber](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx), [checkpoint Piper Edresson](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/edresson/low/pt_BR-edresson-low.onnx), [repositório Kokoro](https://github.com/hexgrad/kokoro), [catálogo de vozes Kokoro](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) e [idiomas MeloTTS](https://github.com/myshell-ai/MeloTTS).

## Consequências e limites

As mudanças reduzem trabalho repetido e permitem ajuste por ambiente, mas não demonstram ainda a experiência acústica completa. A latência de ponta a ponta, WER, falso corte, tempo de espera e qualidade natural precisam ser medidos com modelos já presentes localmente e frases fictícias; qualquer avaliação com fala de uma pessoa exigirá consentimento e não deve ser registrada. A meta abaixo de um segundo permanece não alcançada na medição quente do LLM. Não foi adicionada dependência nem alterado o modelo de conversa ou a voz instalada.
