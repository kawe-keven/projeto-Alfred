# Integrações do Alfred

## E-mail

O envio usa SMTP e aceita mensagens em texto simples. Antes de cada envio, Alfred mostra o destinatário, o assunto e o texto e pede confirmação. As credenciais ficam no cofre de credenciais do Windows.

Depois de atualizar o Alfred, execute `python -m pip install -e .` para instalar o acesso ao cofre.

No painel local do Alfred, envie um único comando neste formato, substituindo os campos pelos seus dados:

```text
/configuraremail remetente senha_de_app servidor_smtp porta
```

Exemplo de formato, sem credenciais reais:

```text
/configuraremail pessoa@example.com senha_sem_espacos smtp.gmail.com 587
```

O painel oculta visualmente o comando enviado. Alfred o encaminha diretamente ao cofre do Windows, sem passar pelo modelo nem pelo banco de memória. Para permitir perguntas de acompanhamento como “qual motivo?”, a conversa mantém apenas uma anotação sanitizada (`/configuraremail [credenciais ocultas]`) e a resposta do comando na janela temporária do chat. A senha nunca é adicionada ao histórico ou ao RAG. O comando precisa ter cinco partes separadas por espaços; digite a senha de app sem espaços.

`/configurar_email` também é aceito como alias. No Alfred CLI, digite somente `/configuraremail` ou `/configurar_email`; ele solicita o endereço, servidor e porta normalmente e lê a senha em campo oculto.

Para Gmail, use `smtp.gmail.com`, porta `587`, e uma senha de app da Conta Google, com a verificação em duas etapas ativada. Não use sua senha principal. Consulte [as configurações SMTP do Gmail](https://support.google.com/mail/answer/7104828?hl=pt-BR).

Para Outlook.com e Microsoft 365, servidor e autenticação variam conforme o tipo de conta. Consulte [as configurações da Microsoft](https://support.microsoft.com/pt-br/office/configura%C3%A7%C3%B5es-pop-imap-e-smtp-para-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040). Este adaptador usa autenticação SMTP por usuário e senha com STARTTLS ou SSL; contas que exigem OAuth não são compatíveis.

## WhatsApp, Instagram e outros apps

Esses apps ainda não têm adaptadores de ação conectados. Quando você pedir para usar um deles, Alfred informa os requisitos gerais de configuração, mas não deve dizer que enviou mensagem ou executou uma ação.

- **WhatsApp:** é preciso configurar um app na plataforma de desenvolvedores da Meta, habilitar WhatsApp Business Platform, registrar um número e obter credenciais e permissões apropriadas.
- **Instagram:** os requisitos dependem da ação. Em geral, é preciso uma conta profissional, um app da Meta, vínculo com os ativos necessários e permissões aprovadas para a API correspondente.
- **Outro app:** é necessário um adaptador usando a API oficial, uma credencial de escopo mínimo e as permissões exigidas pelo serviço.

Não envie credenciais de outros apps ao Alfred até que exista um adaptador específico para eles.
