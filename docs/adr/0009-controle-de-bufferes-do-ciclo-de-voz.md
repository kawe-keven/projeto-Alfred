# ADR 0009: Limites e contrapressão no ciclo de voz

- **Estado:** buffers e reprodução progressiva implementados; validação acústica ao vivo pendente.
- **Data:** 2026-10-27.

## Contexto

A inspeção estática do fluxo identificou dois buffers sem limite efetivo: os eventos do iterador síncrono do Ollama eram entregues a uma fila asyncio sem capacidade máxima, e a captura mantinha todos os frames até o VAD encerrar a fala. Uma resposta de áudio mais lenta que a geração ou uma fala muito longa podia acumular memória.

## Decisão

- Limitar o buffer no callback de captura e agendar uma única drenagem no event loop. A fila de captura existente continua limitada e descarta os frames mais antigos sob sobrecarga; a quantidade descartada passa a ser registrada ao fechar a captura.
- Limitar a fila entre Ollama e agente a quatro eventos e bloquear o produtor quando o consumidor não acompanhar. Isso propaga contrapressão ao iterador síncrono e evita acumular tokens durante a síntese/reprodução.
- Dividir automaticamente uma fala contínua em turnos de até 120 segundos. O VAD é reiniciado ao fechar o turno, e a captura continua para reconhecer o áudio seguinte.
- Ativar por padrão instruções de síntese para português brasileiro conversacional, com pausas e entonação sutis. A pausa entre frases também passa de 160 ms para 220 ms; ambos os ajustes devem ser avaliados com áudio real porque o efeito depende do VoiceStudio e do perfil de voz.
- Orientar o agente a preferir brevidade sem impor sempre uma ou duas frases, e permitir confirmações naturais ocasionais sem bordões repetidos. A identidade continua explicitamente de assistente de IA.

## Limites conhecidos

- O caminho de fala reproduz o PCM conforme chega, depois de um pré-buffer de cerca de 171 ms; os blocos de saída têm cerca de 85 ms. Uma fila limitada de 16 blocos mantém contrapressão e permite iniciar a síntese da frase seguinte durante a reprodução atual. O PCM enfileirado ocupa no máximo cerca de 1,4 s de áudio, além do pré-buffer, do montador e do áudio já entregue ao dispositivo.
- Se a conexão falhar depois de o áudio começar, o Alfred descarta o stream, ativa o fallback e tenta reproduzir a frase completa por ele. A pessoa pode ouvir o início repetido nessa recuperação; sem fallback configurado, a frase fica incompleta e o Alfred registra a falha.
- Os 120 segundos são um limite fixo e não configurável. O turno pode ser dividido no meio de uma frase longa.
- Não foram executados testes nem medições com microfone, Ollama, VoiceStudio ou modelos reais nesta alteração. Latência e qualidade acústica permanecem por medir no equipamento alvo.
