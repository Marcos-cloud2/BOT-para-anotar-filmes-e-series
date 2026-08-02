# Bot para Anotar Filmes, Séries e Animes

Eu tenho o costume de encontrar filmes e séries interessantes enquanto rolo o
feed do Instagram e do TikTok, tiro print e depois esqueço onde guardei. Fiz
esse bot pra resolver isso: mando o print (ou só digito o nome) pro bot no
Telegram, ele identifica o título usando IA, busca gênero, nota, sinopse e em
qual plataforma de streaming dá pra assistir, e anota tudo numa lista
organizada que eu consulto quando quero saber o que assistir.

Este documento explica passo a passo como colocar o bot pra funcionar do
zero, mesmo que você nunca tenha feito nada parecido antes.

## O que o bot faz

- Você manda uma foto (print de rede social divulgando um filme/série/anime)
  ou só digita o nome do título.
- O bot usa a IA do Google (Gemini) com busca no Google integrada para
  identificar o título oficial, o tipo (Filme, Série ou Anime), o(s)
  gênero(s), a nota do público/crítica, uma sinopse curta e em quais
  plataformas de streaming está disponível no Brasil.
- Tudo isso fica salvo numa lista, organizada por **plataforma → categoria →
  gênero → título**, navegável por botões direto no chat do Telegram.
- Dá pra marcar como assistido, desmarcar, corrigir o nome ou remover, tudo
  pelos botões ou por comando.

## Antes de começar

Você vai precisar de três coisas, todas gratuitas:

1. Uma conta no Telegram (pra criar o bot)
2. Uma conta Google (pra gerar a chave de acesso à IA Gemini)
3. Python instalado na sua máquina (versão 3.10 ou mais nova), ou uma conta
   no [Render](https://render.com) se quiser deixar o bot rodando na nuvem
   24 horas por dia sem depender do seu computador ligado

## Passo 1 — Criar o bot no Telegram

1. Abra o Telegram e procure pelo usuário **@BotFather** (é o bot oficial do
   Telegram para criar outros bots).
2. Envie o comando `/newbot`.
3. Escolha um nome de exibição para o bot (ex: "Meus Filmes e Séries").
4. Escolha um "username" único, que precisa terminar em `bot` (ex:
   `meusfilmesbot`).
5. O BotFather vai te devolver uma mensagem com um **token**, algo parecido
   com `123456789:ABCdefGhIJKlmNoPQRstuVWxyz`. Copie e guarde esse token —
   ele é a senha do seu bot. **Nunca compartilhe esse token com ninguém nem
   suba ele para o GitHub.**

## Passo 2 — Criar a chave de acesso ao Gemini (a IA que analisa as imagens)

1. Acesse https://aistudio.google.com/apikey usando sua conta Google.
2. Clique em **Create API Key** (ou "Criar chave de API").
3. Copie a chave gerada (começa com `AIza...`). Isso já ativa
   automaticamente uma cota gratuita de uso diário, suficiente para uso
   pessoal.
4. Guarde essa chave — assim como o token do Telegram, ela é sigilosa e não
   deve ser compartilhada nem subida para nenhum repositório público.

## Passo 3 — Baixar o projeto

Se você chegou a este repositório pelo GitHub, baixe o código na sua
máquina:

```bash
git clone https://github.com/Marcos-cloud2/BOT-para-anotar-filmes-e-series.git
cd BOT-para-anotar-filmes-e-series
```

## Passo 4 — Configurar as variáveis de ambiente

O bot lê o token do Telegram e a chave do Gemini de **variáveis de
ambiente**, nunca de dentro do código. Isso é o que garante que essas
informações sigilosas nunca acabem publicadas no GitHub.

Existe um arquivo de exemplo chamado `.env.example` no projeto, mostrando o
formato esperado:

```
TELEGRAM_BOT_TOKEN=coloque_aqui_o_token_do_botfather
GEMINI_API_KEY=coloque_aqui_sua_chave_do_google_ai_studio
```

Você não precisa necessariamente criar um arquivo `.env` — o jeito mais
simples pra rodar localmente é definir essas variáveis direto no terminal
antes de iniciar o bot, como mostrado no próximo passo.

## Passo 5 — Rodar o bot na sua máquina

Instale as dependências do projeto:

```bash
pip install -r requirements.txt
```

### No Windows (PowerShell)

```powershell
$env:TELEGRAM_BOT_TOKEN = "seu_token_do_botfather"
$env:GEMINI_API_KEY = "sua_chave_do_google_ai_studio"
python bot.py
```

### No Linux ou macOS

```bash
export TELEGRAM_BOT_TOKEN="seu_token_do_botfather"
export GEMINI_API_KEY="sua_chave_do_google_ai_studio"
python bot.py
```

Se tudo estiver certo, vai aparecer no terminal a mensagem:
`Bot iniciado, aguardando mensagens...`

Agora é só abrir o Telegram, procurar pelo bot que você criou no Passo 1, e
mandar `/start`. Enquanto esse terminal estiver aberto e rodando, o bot fica
respondendo. Se fechar o terminal, o bot para.

## Passo 6 — Colocar o bot pra rodar 24 horas por dia (opcional)

Rodar localmente é ótimo pra testar, mas o bot só responde enquanto o seu
computador estiver ligado e o script rodando. Pra deixar ele sempre ativo,
sem depender disso, você pode hospedar de graça no [Render](https://render.com):

1. Suba este projeto para um repositório seu no GitHub (as variáveis
   sigilosas ficam automaticamente de fora do repositório graças ao arquivo
   `.gitignore` incluso).
2. Crie uma conta em https://render.com e conecte com o GitHub.
3. Clique em **New > Background Worker**.
4. Selecione o repositório do bot. O Render vai detectar o `Dockerfile`
   incluso no projeto automaticamente e usar ele para montar o ambiente.
5. Na seção **Environment > Environment Variables**, adicione:
   - `TELEGRAM_BOT_TOKEN` com o token do BotFather
   - `GEMINI_API_KEY` com a chave do Google AI Studio
6. Clique em **Deploy**. Acompanhe os logs até ver a mensagem "Bot iniciado,
   aguardando mensagens...".

A partir daí, o bot roda sozinho na nuvem, 24 horas por dia, mesmo com seu
computador desligado.

### Sobre a lista salva (importante saber)

O bot guarda a lista de filmes/séries num arquivo local `filmes.db`
(um banco SQLite simples). No plano gratuito do Render, o disco do container
é apagado a cada novo deploy — ou seja, se você atualizar o código e fizer
um novo deploy, a lista salva até ali pode ser perdida.

Para uso pessoal isso raramente é um problema (você não fica fazendo deploy
toda hora), mas se quiser manter a lista permanente para sempre, existem
duas opções:
- Adicionar um **Persistent Disk** no Render (recurso pago) apontando para
  a pasta `/app`.
- Trocar o SQLite por um banco de dados externo gratuito (Postgres do
  próprio Render, ou Supabase, por exemplo).

## Como usar o bot no dia a dia

**Adicionar um item:**
- Manda uma foto/print divulgando o filme, série ou anime — o bot identifica
  sozinho.
- Ou simplesmente digita o nome do título direto no chat.

Em ambos os casos, o bot responde já com tipo, gênero, nota, sinopse e onde
assistir.

**Navegar pela lista:**
- `/lista` mostra o que falta assistir, organizado por plataforma de
  streaming. Você toca na plataforma, depois na categoria (Filme, Série ou
  Anime), depois no gênero, até chegar no título — só aparecem as opções
  que você realmente tem cadastradas.
- `/assistidos` funciona do mesmo jeito, mas para o que você já assistiu.
- Ao tocar num título, aparece a sinopse completa, a nota, onde assistir, e
  botões para marcar como assistido, desmarcar ou remover.

**Comandos diretos (sem precisar navegar pelos botões):**
- `/detalhes <id>` — mostra todos os detalhes de um item pelo número dele.
- `/marcar <id>` — marca como assistido.
- `/desmarcar <id>` — volta o item para a lista de "para assistir".
- `/renomear <id> <nome certo>` — corrige o título, caso a IA tenha
  identificado errado.
- `/remover <id>` — apaga o item de vez.

O número (`<id>`) de cada item aparece nas telas de detalhes e nas mensagens
de confirmação quando você adiciona algo novo.

## Estrutura do projeto

```
telegram-filmes-bot/
├── bot.py            # todo o codigo do bot
├── requirements.txt  # dependencias Python
├── Dockerfile         # usado pelo Render para montar o ambiente
├── .env.example       # exemplo de variaveis de ambiente (sem valores reais)
├── .gitignore         # garante que segredos e o banco de dados nao vao pro Git
└── README.md          # este arquivo
```
