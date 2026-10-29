# ADR 0007: Preservar a identidade vocal do Alfred

- Estado: implementado; comparação perceptiva e medição ao vivo pendentes.
- Data: 2026-10-23.

## Decisão

- Manter no Alfred o perfil VoiceStudio `66b001cc`, criado da referência MP3 original. O perfil `66ca3722` foi criado no VoiceStudio a partir de uma amostra do Piper Faber e fica disponível para seleção.
- Usar Piper Faber como fallback local se o VoiceStudio falhar. O timbre é aproximado, sem promessa de identidade perfeita entre motores.
- Não selecionar Piper como motor do ciclo de voz nem como fallback. Piper usa um modelo ONNX de voz independente e mudaria o timbre.
- Se VoiceStudio falhar, a resposta não será sintetizada em áudio naquela tentativa. A continuidade da identidade vocal tem prioridade sobre a disponibilidade do TTS alternativo.
- Histórico (2026-10-23): manter `instructions` vazio para favorecer latência. A preferência atual do usuário prioriza fala natural para conversas; desde 2026-10-27 o padrão orienta ritmo espontâneo, pausas e variação sutil de entonação. O valor pode ser ajustado ou esvaziado por `ALFRED_VOICESTUDIO_ESTILO`. As chamadas ao Ollama continuam com `think: false`, e a naturalidade não altera honestidade, confirmação ou validação no código.
- Registrar mediana e p95 da primeira frase completa e do primeiro áudio desde o fim da fala.

## Consequências e limites

A latência fica dependente do VoiceStudio e do perfil local; a meta de 1,0–1,5 s não está validada. O id do perfil existe na instalação local do VoiceStudio e precisa ser preservado nela. O fallback Piper da etapa anterior foi removido da interface de voz para não trocar a identidade sonora.

Um modelo Piper ONNX correspondente exigiria treinamento/exportação próprios; o perfil VoiceStudio não pode ser carregado diretamente pelo Piper. A voz do perfil e a referência precisam ser comparadas auditivamente para confirmar a qualidade do clone.
