# Relatório de auditoria do projeto Alfred

Auditoria estática e execução de diagnóstico em 27/10/2026. Raiz analisada: `alfred-fix/` (a pasta de trabalho externa contém apenas lançadores e não é a raiz Git). Não foram alterados arquivos do projeto além deste relatório. Os diretórios locais `dados/` e `projetos/` não foram inspecionados em conteúdo; são dados potencialmente sensíveis e estão ignorados pelo Git.

## 1. Resumo executivo

O Alfred é um assistente local relativamente completo, com camadas de interface, núcleo, adaptadores, segurança e armazenamento cifrado. A documentação é extensa e descreve bem os limites de privacidade e integrações locais. O principal risco operacional concreto é o Redis do Compose publicado sem autenticação e sem uso aparente no código. A suíte padrão concluiu com **4 falhas e 361 testes aprovados**, em especial expectativas de migração/configuração aparentemente defasadas em relação à implementação atual. **Nota: 6,5/10**, reduzida pelos testes falhos, pela porta Redis exposta e pela ausência de lockfile. Não foi confirmada vulnerabilidade de dependência nesta execução.

## 2. Stack e como rodar

### Tecnologias

- **Linguagens:** Python 3.11+ (ambiente diagnosticado: 3.14.7), JavaScript, HTML, CSS, SQL, PowerShell e arquivos batch do Windows.
- **Frameworks:** não há framework web Python; o painel usa `http.server` da biblioteca padrão. Interface web JavaScript sem framework.
- **Bibliotecas principais:** SQLCipher (`sqlcipher3>=0.6.4`), PyYAML (`>=6.0`), zstandard (`>=0.22`), keyring (`>=25`); pytest (`>=8`) e Ruff (`>=0.14`) no extra `dev`; ChromaDB (`==1.5.9`) no extra `memoria`; no extra `voz`: NumPy (`>=2.1`), sounddevice (`>=0.5.6`), Silero VAD (`>=6.2.3`), PyTorch (`>=2.10`), ONNX Runtime (`>=1.31`), OpenWakeWord (`>=0.6.0`), sherpa-onnx (`>=1.12.0`), faster-whisper (`>=1.2.0`) e Piper TTS (`>=1.8.0`). O navegador inclui MapLibre GL **5.6.0** em `ui/vendor/maplibre-gl/manifesto.json`.
- **Gerenciador/empacotamento:** pip + setuptools, configurados em `pyproject.toml`; não há `package.json`, lockfile Python ou lockfile JavaScript identificado.
- **Banco:** SQLCipher/SQLite para dados sensíveis e relacionais; ChromaDB persistente opcional para índice vetorial. `docker-compose.yml` declara Redis 7, mas não encontrei uso de Redis no código Python.
- **Serviços e APIs:** Ollama local (`localhost:11434`) para LLM e embeddings; VoiceStudio local (`127.0.0.1:3900`) para TTS; SMTP configurável para e-mail; APIs HTTP locais do painel. A preparação de modelos/mapas pode baixar artefatos de GitHub/npm quando executada explicitamente. A URL de mapa de satélite é opcional e está vazia na configuração padrão. Não encontrei chamadas do Alfred a serviços de IA hospedados na nuvem.

### Instalação e comandos

Na raiz `alfred-fix/`, com Python 3.11+:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[voz,dev,memoria]"
python -m pytest
python -m alfred.interfaces.cli
python -m alfred.interfaces.web.app
python -m alfred.interfaces.ciclo_de_voz --modo conversa
```

`pip install -e .` instala o pacote e dependências básicas; os extras são opcionais. `README.md` também documenta scripts Windows, administração SQLCipher, avaliação de voz e configuração do Ollama. Os scripts de console definidos em `pyproject.toml` são `alfred`, `alfred-armazenamento` e `alfred-painel`. A configuração pytest exclui por padrão marcadores `lento`, `integracao` e `ao_vivo`. Ruff está configurado (`python -m ruff check src testes scripts`), mas não estava instalado neste ambiente; não há configuração/ferramenta de type-check declarada. Não há script de build explícito; o projeto usa setuptools via `pyproject.toml`.

## 3. Arquitetura e estrutura

### Fluxo e módulos

As interfaces CLI, web e voz montam a sessão e encaminham entrada ao agente em `nucleo/agente`. O agente aplica políticas e coordena ferramentas, memória e adaptador LLM. O adaptador Ollama usa HTTP local e pode transmitir tokens. A memória persiste dados relacionais cifrados via SQLCipher e pode indexar/recuperar conteúdo pelo contrato vetorial com implementação Chroma. Na voz, captura de microfone → VAD → STT → agente/LLM → TTS → saída de áudio. O painel HTTP serve `ui/`, oferece endpoints locais e controla sessões CLI/voz. Configuração tipada e variáveis `ALFRED_*` ficam em `configuracao`; chaves, auditoria e outros controles ficam em `seguranca`.

Pontos de entrada principais: `src/alfred/interfaces/cli/app.py`, `src/alfred/interfaces/web/app.py`, `src/alfred/interfaces/ciclo_de_voz/app.py`, `src/alfred/interfaces/configuracao_voz/app.py` e `src/alfred/interfaces/cli/armazenamento.py`. `src/alfred/__main__.py` é entrada adicional. O fluxo e a direção arquitetural estão documentados em `docs/ESTRUTURA_DO_PROJETO.md`.

### Árvore até três níveis

```text
.
├── docs/                         Documentação, decisões e notas de teste
│   ├── adr/                      Decisões de arquitetura
│   └── testes/                   Procedimentos e resultados de testes documentados
├── prompts/                      Prompt de sistema
├── scripts/                      Avaliação, preparação de modelos/mapas e utilitários
├── src/alfred/                   Código Python do pacote
│   ├── adaptadores/              Integrações com LLM, voz, fontes e notificações
│   │   ├── fontes/               Adaptadores de fontes de informação
│   │   ├── llm/                  Adaptador Ollama
│   │   ├── notificacoes/         Adaptadores de notificação
│   │   └── voz/                  Captura, VAD, STT e TTS
│   ├── blueprint/                Detecção, geração e templates de blueprints
│   ├── configuracao/             Configuração tipada e pronúncias
│   ├── ferramentas/              Registro e ferramentas disponíveis ao agente
│   │   └── nativas/              Ferramentas locais de arquivos, e-mail etc.
│   ├── interfaces/               Entradas e aplicações de usuário
│   │   ├── api/                  Interface API
│   │   ├── cli/                  CLI e armazenamento administrativo
│   │   ├── ciclo_de_voz/         Aplicação e orquestração de voz
│   │   ├── configuracao_voz/     Configurador local de voz
│   │   └── web/                  Painel HTTP, mapa e lugares
│   ├── memoria/                  Perfil, recuperação e armazenamento
│   │   ├── armazenamento/        SQLCipher, Chroma, RAG e migrações
│   │   ├── esquecimento/         Políticas/rotinas de esquecimento
│   │   ├── perfil/               Perfis, pessoas e montagem de prompts
│   │   └── resumidores/          Resumos de memória/conversa
│   ├── nucleo/                   Agente, modelos, eventos e políticas
│   │   ├── agente/               Conversa, roteamento e streaming
│   │   ├── eventos/              Eventos de domínio
│   │   ├── modelos/              Modelos de domínio
│   │   ├── politicas/            Segurança comportamental e atualidade
│   │   └── proatividade/         Componentes de proatividade
│   └── seguranca/                Controles transversais de segurança
│       ├── auditoria/            Registro e auditoria
│       ├── autenticacao/         Autenticação
│       ├── chaves/               Provedores e derivação de chaves
│       ├── criptografia/         Operações criptográficas
│       ├── integridade/          Verificações de integridade
│       └── isolamento/           Isolamento de execução/dados
├── testes/                       Testes automatizados
│   ├── cenarios/                 Cenários de comportamento
│   ├── integracao/               Testes entre componentes
│   ├── memoria/                  Testes da memória e persistência
│   └── unitarios/                Testes de módulos isolados
├── ui/                           Interface web estática
│   ├── mapa/                     Código JavaScript do mapa
│   ├── styles/                   CSS por área/tema
│   └── vendor/maplibre-gl/       MapLibre empacotado localmente
├── dados/                        Dados locais ignorados pelo Git (conteúdo não inspecionado)
└── projetos/                     Diretório local ignorado pelo Git
```

## 4. Problemas encontrados

| ID | Severidade | Categoria | Arquivo:linha | Resumo |
|---|---|---|---|---|
| P-01 | ALTO | segurança | `docker-compose.yml:1-7` | Redis sem autenticação é publicado na porta do host sem limitar interface; código não aparenta precisar dele. |
| P-02 | MÉDIO | testes | `testes/unitarios/test_bancos_relacionais.py:46-55,61-89`; `testes/unitarios/test_configuracao.py:49-52` | Testes falham por expectativas de versão de migração/modelo padrão divergentes da implementação atual. |
| P-03 | MÉDIO | dependências | `pyproject.toml:10-30`; `requirements.txt:1-9` | Dependências usam principalmente limites mínimos sem arquivo de travamento, reduzindo reprodutibilidade. |
| P-04 | BAIXO | arquitetura | `src/alfred/interfaces/web/app.py:212-242,253-350,581-614` | Um handler concentra validação HTTP, roteamento, operações de sessão/memória e mutações de lugares. |

## 5. Detalhamento

### P-01 — Redis exposto sem autenticação

- **Arquivo/linhas:** `docker-compose.yml:1-7`
- **Severidade/categoria:** ALTO — segurança.
- **Descrição:** o serviço Redis usa imagem padrão e publica `6379:6379`, sem senha nem bind explícito ao loopback. O mapeamento Docker normalmente publica em todas as interfaces do host. Não encontrei referência ao Redis no código Python. Se o Compose for iniciado em uma máquina acessível por rede, o serviço pode ficar disponível a outros dispositivos sem controle de acesso.
- **Trecho relevante:**

  ```yaml
  services:
    redis:
      image: redis:7-alpine
      ports:
        - "6379:6379"
      volumes:
        - redis_data:/data
  ```

- **Sugestão:** remover esse serviço se não houver consumidor; se necessário, restringir a publicação a `127.0.0.1`, configurar autenticação/ACL e documentar o uso. A severidade é condicional ao uso do Compose.

### P-02 — Suíte padrão com quatro testes falhos

- **Arquivos/linhas:** `testes/unitarios/test_bancos_relacionais.py:46-55,61-89`; `testes/unitarios/test_configuracao.py:49-52`; implementação em `src/alfred/memoria/armazenamento/migracao.py:64-69` e `src/alfred/configuracao/configuracao.py:339-344`.
- **Severidade/categoria:** MÉDIO — testes.
- **Descrição:** os testes esperam que a migração termine na versão 4 e que o modelo padrão seja `qwen3.5:9b`. O código atual lista migrações até `0005_lugares.sql`, logo a versão final é 5, e o padrão configurado é `qwen3.5:4b`. Isso causou três falhas relacionadas a migrações e uma falha de configuração. Nos testes de migração, a fixture também cria `0005_falha.sql`, em conflito com a migração real `0005_lugares.sql`, produzindo erro de numeração duplicada antes do cenário de rollback pretendido. As falhas apontam expectativas/fixtures antigas; por si só, não demonstram defeito no comportamento atual da aplicação.
- **Trecho relevante:**

  ```python
  # testes/unitarios/test_bancos_relacionais.py
  assert aplicar_migracoes(caminho, chave) == 4
  ...
  assert conexao.execute("PRAGMA user_version").fetchone()[0] == 4
  ```

  ```python
  # testes/unitarios/test_configuracao.py
  assert configuracao.modelo == "qwen3.5:9b"
  ```

- **Sugestão:** alinhar expectativas à migração 5 e ao padrão `4b`, ou restaurar o comportamento anterior caso esses valores representem uma regressão não intencional. Renomear a migração artificial de falha para um número livre no diretório da fixture e revisar o cenário de rollback.

### P-03 — Resolução de dependências não travada

- **Arquivo/linhas:** `pyproject.toml:10-30`; `requirements.txt:1-9`.
- **Severidade/categoria:** MÉDIO — dependências.
- **Descrição:** a maioria das bibliotecas declara somente versões mínimas (`>=`), enquanto não existe lockfile identificado. Instalações em datas/ambientes diferentes podem resolver versões incompatíveis entre si ou com o código. ChromaDB está fixado, mas os demais extras de voz e dependências principais não. A auditoria não confirmou se há dependências vulneráveis: Ruff e ferramenta de auditoria de CVEs não estavam disponíveis e não foi feita instalação/consulta de rede.
- **Trecho relevante:**

  ```toml
  requires-python = ">=3.11"
  dependencies = ["sqlcipher3>=0.6.4", "PyYAML>=6.0", "zstandard>=0.22", "keyring>=25"]
  ...
  memoria = ["chromadb==1.5.9"]
  voz = ["numpy>=2.1", "sounddevice>=0.5.6", "silero-vad>=6.2.3", ...]
  ```

- **Sugestão:** gerar e manter um lockfile por plataforma/alvo ou travar versões testadas em arquivos de constraints, especialmente para os extras de áudio/ML; automatizar revisão periódica de vulnerabilidades no CI.

### P-04 — Handler HTTP com múltiplas responsabilidades

- **Arquivo/linhas:** `src/alfred/interfaces/web/app.py:212-242,253-350,581-614`.
- **Severidade/categoria:** BAIXO — arquitetura.
- **Descrição:** a classe do handler concentra validação de origem/corpo, roteamento, chamadas de sessão, status de serviços, operações de mapa e mutações de lugares com confirmações. Isso aumenta o acoplamento e torna mais difícil testar casos HTTP isoladamente; parte do código também usa instruções compactadas em uma linha nas rotas de mutação. Não foi observado bug específico derivado disso.
- **Trecho relevante:**

  ```python
  def do_DELETE(self) -> None:
      if urlsplit(self.path).path.startswith("/api/mapa/lugares/"):
          self._alterar_lugar("DELETE")
      else: self._metodo_mapa_nao_permitido()
  ```

- **Sugestão:** extrair roteamento/endpoints e lógica de aplicação para serviços separados, preservar o handler como camada HTTP fina e formatar os blocos de rota de modo uniforme.

### Verificações de segurança, qualidade e interface

- Não encontrei credenciais reais nos arquivos de configuração examinados; `.env.exemplo` contém valores locais de exemplo e `.gitignore:1` ignora `.env`. A chave SQLCipher é documentada como armazenada no cofre do sistema ou fornecida em entrada oculta.
- O painel valida origem/Host em `src/alfred/interfaces/web/app.py:244-251`, limita corpo JSON a 200.000 bytes em `235-242` e opera no loopback conforme documentação. O renderizador de markdown usa nós de texto e restringe links a HTTP/HTTPS em `ui/app.js:260-297`; não identifiquei XSS no trecho examinado.
- Queries SQL observadas usam placeholders para valores. A atualização de lugares constrói nomes de colunas dinamicamente em `src/alfred/interfaces/web/lugares.py:69-75`, mas os campos são montados pelo endpoint a partir da lista fechada `nome`, `lat`, `lon` (`app.py:601-605`); não classifiquei como SQL injection.
- Não identifiquei TODO/FIXME de produção ou dependências Python duplicadas declaradas. Não foi possível fazer verificação completa de pacotes não usados/vulnerabilidades sem auditor de dependências e resolução de versão de referência.
- Há CSS separado para responsividade (`ui/styles/responsive.css`) e atributos ARIA na interface. Não existe suíte automatizada de browser/a11y identificada, portanto responsividade e acessibilidade visual não foram validadas em execução.
- Há documentação extensa de variáveis em `.env.exemplo` e `README.md`. O Compose Redis não aparece como requisito funcional documentado; sua finalidade não foi determinada.

## 6. Resultado de lint, testes e build

- **Testes:** `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp <TEMP> -q` — **361 passaram, 4 falharam, 4 foram excluídos**, em 75,20 s. As falhas foram `test_migracoes_idempotentes_e_esquema`, `test_migracao_recusa_banco_de_versao_mais_nova`, `test_falha_de_migracao_restaura_copia_cifrada` e `test_carrega_padroes_e_resolve_perfil_na_raiz`; razões detalhadas em P-02. Os quatro excluídos seguem os marcadores configurados (lento/integração/ao vivo).
- **Lint:** não executado; `ruff` está declarado no extra `dev`, mas `python -m ruff` retornou `No module named ruff`. Não foi instalado nada.
- **Type-check:** não há ferramenta ou comando configurado no `pyproject.toml`.
- **Dependências instaladas:** `pip check` terminou com `No broken requirements found.` Ambiente: Python 3.14.7; entre os pacotes presentes: sqlcipher3 0.6.4, PyYAML 6.0.3, keyring 25.7.0, pytest 9.1.1, ChromaDB 1.5.9, NumPy 2.5.4, sounddevice 0.5.6, Silero VAD 6.2.3, PyTorch 2.14.1, ONNX Runtime 1.31.0, sherpa-onnx 1.12.0, OpenWakeWord 0.6.0, faster-whisper 1.2.1 e Piper TTS 1.8.0. Ruff não instalado. `pip check` valida consistência declarada, não vulnerabilidades.
- **Build:** não executado; não há comando de build do projeto documentado e não foi instalado `build`. O backend configurado é setuptools.

## 7. Plano de correção priorizado

### Fazer agora

1. Revisar `docker-compose.yml`: remover o Redis sem consumidor ou limitar a exposição ao loopback e habilitar controle de acesso antes de qualquer uso compartilhado.
2. Atualizar os testes de migração/configuração para refletirem a versão de esquema e os valores padrão intencionais; corrigir a fixture do teste de rollback para evitar colisão com `0005_lugares.sql`.
3. Reexecutar a suíte padrão e depois os testes de integração/lentos quando houver ambiente adequado.

### Fazer em seguida

1. Adotar lockfile/constraints reproduzíveis e política automatizada de atualização e auditoria de dependências.
2. Separar responsabilidades do handler web e adicionar testes de endpoints, origem, limite de payload e confirmação concorrente.
3. Instalar extras de desenvolvimento apenas no ambiente de CI e executar Ruff e verificações de tipos se uma ferramenta for escolhida.

### Melhorias futuras

1. Acrescentar testes de acessibilidade/responsividade no navegador e testes de segurança de dependências.
2. Clarificar no README/Compose se Redis é necessário e qual componente o consome.
3. Definir um comando de build reproduzível e validá-lo em CI em Python 3.11 e na versão Windows suportada.

## 8. Dúvidas e limites da auditoria

- Não foi possível determinar se Redis é legado, preparação futura ou dependência pretendida; nenhuma referência de uso foi encontrada no código analisado.
- A execução padrão não inclui testes lentos, de integração ou ao vivo; APIs e dispositivos reais (Ollama, VoiceStudio, microfone, SMTP e mapa empacotado) não foram exercitados.
- Não foi feita consulta a avisos atuais de vulnerabilidade das dependências. Os intervalos de versão registrados não permitem inferir que uma dependência seja vulnerável ou segura.
- Dados em `dados/` e `projetos/` não foram lidos; qualquer avaliação desses conteúdos está fora do escopo deste relatório.
- O diretório `.git` não apresentou arquivos rastreados no `git status`; por isso não foi possível comparar as fontes com um commit-base confiável durante esta auditoria.
