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
- Tudo isso fica salvo numa lista navegável por botões direto no chat do
  Telegram: você escolhe se quer navegar **por plataforma** ou **por
  gênero**, e o bot vai afunilando as opções (categoria, depois a outra
  dimensão) até chegar no título — só aparece o que você realmente tem
  cadastrado.
- Se você tentar adicionar um título que já está na lista (assistido ou
  não), o bot avisa em vez de cadastrar duplicado.
- Dá pra marcar como assistido, desmarcar, corrigir o nome ou remover, tudo
  pelos botões ou por comando.
- Dá pra pedir recomendação (`/recomendar filme de terror na Netflix`, ou
  só perguntar direto no chat). O bot busca na internet o que está bombando
  ou bem avaliado de acordo com o pedido, e nunca repete algo que você já
  marcou como assistido. Se gostar, é só tocar num botão pra já adicionar
  na lista.

## Antes de começar

Você vai precisar de três coisas, todas gratuitas:

1. Uma conta no Telegram (pra criar o bot)
2. Uma conta Google (pra gerar a chave de acesso à IA Gemini)
3. Python instalado na sua máquina (versão 3.10 ou mais nova), ou uma conta
   no [Fly.io](https://fly.io) se quiser deixar o bot rodando na nuvem
   24 horas por dia sem depender do seu computador ligado (passo 6 deste
   guia)

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
sem depender disso, o jeito que usei foi o [Fly.io](https://fly.io) — ele
tem uma cota de uso gratuita que cobre tranquilamente um bot pessoal como
esse rodando o tempo todo (o Render, que era outra opção gratuita comum,
tirou o plano free de "Background Worker" e hoje cobra a partir de
$7/mês).

**Antes de começar:** o Fly.io pede um cartão de crédito cadastrado como
verificação de conta antes de liberar qualquer deploy, mesmo pra quem vai
ficar só na cota gratuita. Ele não cobra automaticamente enquanto o uso
ficar dentro da cota — mas é bom saber disso antes de criar a conta.

1. Instale o `flyctl` (a ferramenta de linha de comando do Fly.io):
   - Windows (PowerShell): `iwr https://fly.io/install.ps1 -useb | iex`
   - Linux/macOS: `curl -L https://fly.io/install.sh | sh`
2. Feche e abra o terminal de novo (ou adicione o `flyctl` ao PATH
   manualmente), depois confirme que instalou: `flyctl version`
3. Faça login (abre o navegador pra você criar conta ou entrar):
   ```bash
   flyctl auth login
   ```
4. Dentro da pasta do projeto (`telegram-filmes-bot`), crie o app sem fazer
   deploy ainda (troque `seu-nome-aqui` por um nome único global, tipo
   `filmes-bot-seunome`):
   ```bash
   flyctl launch --name filmes-bot-seunome --region gru --no-deploy --yes
   ```
   Isso gera um arquivo `fly.toml` na pasta do projeto.
5. **Importante:** o `flyctl launch` assume por padrão que o app serve
   páginas web e adiciona um bloco `[http_service]` no `fly.toml` que
   desliga a máquina quando não há tráfego HTTP — isso mataria o bot, que
   não serve HTTP nenhum, só fica conversando com o Telegram. Abra o
   `fly.toml` gerado e apague o bloco `[http_service]` inteiro. O arquivo
   deve ficar parecido com este (que já vem pronto no repositório):
   ```toml
   app = 'filmes-bot-seunome'
   primary_region = 'gru'

   [build]

   [[vm]]
     memory = '256mb'
     cpu_kind = 'shared'
     cpus = 1
     memory_mb = 256
   ```
6. Cadastre os segredos (nunca ficam no código nem no `fly.toml`):
   ```bash
   flyctl secrets set TELEGRAM_BOT_TOKEN="seu_token_do_botfather" GEMINI_API_KEY="sua_chave_do_google_ai_studio"
   ```
7. Faça o deploy:
   ```bash
   flyctl deploy
   ```
8. Confira se subiu certo:
   ```bash
   flyctl status
   flyctl logs
   ```
   Nos logs deve aparecer "Bot iniciado, aguardando mensagens...".

**Atenção a um detalhe do `flyctl launch`:** por padrão ele cria duas
máquinas (uma principal e uma "standby" de redundância, que só liga
sozinha se o hardware do Fly falhar). Isso normalmente não é problema —
mas se você rodar `flyctl scale count 1` pra reduzir a apenas uma máquina,
ele pode derrubar a que estava ativa e deixar só a standby (que fica
desligada). Se isso acontecer, é só ligar ela de novo:
```bash
flyctl status
flyctl machine start <ID_DA_MAQUINA_QUE_APARECE_COMO_STOPPED>
```

A partir daí, o bot roda sozinho na nuvem, 24 horas por dia, mesmo com seu
computador desligado.

**Deploy automático (opcional):** o `flyctl launch` já deixa pronto um
workflow em `.github/workflows/fly-deploy.yml` que faz deploy sozinho toda
vez que você der `git push` na branch `main`. Ele só funciona se você
cadastrar um token nos segredos do repositório do GitHub (Settings >
Secrets and variables > Actions > New repository secret, nome
`FLY_API_TOKEN`, valor gerado com `flyctl tokens create deploy`). Se não
configurar isso, tudo bem — o workflow so vai falhar silenciosamente na
aba Actions, sem afetar o bot, e você continua fazendo deploy manual com
`flyctl deploy` quando quiser.

### Sobre a lista salva (importante saber)

O bot guarda a lista de filmes/séries num arquivo `filmes.db` (um banco
SQLite simples). No Fly.io, esse arquivo precisa morar num **volume
persistente** — sem isso, cada novo deploy recria a máquina do zero e
apaga tudo que foi salvo em execução. O `fly.toml` deste projeto já vem
configurado para isso (bloco `[mounts]` montando o volume em `/data`, e
`DB_PATH=/data/filmes.db`), mas o volume em si **precisa ser criado uma
vez**, manualmente, antes do primeiro deploy:

```bash
flyctl volumes create filmes_data --region gru --size 1
```

(`gru` = São Paulo; troque pela região que você usou no `flyctl launch`.
1 GB é bem mais que suficiente pra esse uso.) Depois disso, `flyctl
deploy` já anexa o volume automaticamente graças ao `fly.toml`.

Se você pulou esse passo e o `/lista` apareceu vazio depois de um deploy,
foi exatamente isso: o banco antigo ficou preso numa máquina que já não
existe mais. Crie o volume com o comando acima, rode `flyctl deploy` de
novo, e a partir daí a lista passa a sobreviver a qualquer deploy futuro.

### Backup automático e como restaurar

Todo volume do Fly.io tem **snapshot diário automático**, com retenção de
5 gerações — isso já vem ativado por padrão, não precisa configurar nada
extra. Pra confirmar que está ativo no seu app:

```bash
flyctl volumes list -a <nome-do-seu-app>
```

Procure por `Scheduled snapshots: true` na saída. Pra ver os snapshots já
existentes (o primeiro só aparece ~24h depois de criar o volume):

```bash
flyctl volumes snapshots list <volume-id> -a <nome-do-seu-app>
```

**Se precisar restaurar um snapshot** (por exemplo, se apagou algo sem
querer ou os dados corromperam), o processo cria um **volume novo** a
partir do snapshot escolhido — não sobrescreve o volume atual:

```bash
flyctl volumes create filmes_data_restaurado --snapshot-id <snapshot-id> --region gru -a <nome-do-seu-app>
```

Depois disso, edite o `fly.toml` trocando `source = 'filmes_data'` para o
nome do volume restaurado, rode `flyctl deploy`, confirme que os dados
voltaram, e só então pode apagar o volume antigo com `flyctl volumes
destroy`.

## Como usar o bot no dia a dia

**Adicionar um item:**
- Manda uma foto/print divulgando o filme, série ou anime — o bot identifica
  sozinho.
- Ou simplesmente digita o nome do título direto no chat.

Em ambos os casos, o bot responde já com tipo, gênero, nota (avaliação de
público/crítica), sinopse e onde assistir.

Se o título já estiver na sua lista (assistido ou não), o bot não cadastra
de novo — ele avisa que já existe, mostra o status atual e te dá botões
pra abrir os detalhes daquele item.

**Navegar pela lista:**
- `/todos` mostra tudo numa lista só, sem etapas — cada botão já vem com o
  número (`#id`), gênero e um marcador de status (🍿 pra assistir, ✅
  assistido) na frente do título. Toca no título e abre a sinopse
  completa, com os mesmos botões de marcar/remover das outras telas. Com
  mais de 10 itens, aparecem botões "Anterior"/"Próxima" pra navegar entre
  páginas.
- `/lista` pergunta primeiro: navegar **por plataforma** ou **por gênero**?
  - Por plataforma: você toca na plataforma de streaming, depois na
    categoria (Filme, Série ou Anime), depois no gênero, até chegar no
    título.
  - Por gênero: mesma ideia, só que começando pelo gênero, depois
    categoria, depois plataforma.
  - Em qualquer um dos dois caminhos, só aparecem as opções que você
    realmente tem cadastradas — nada de categoria ou plataforma vazia.
- `/assistidos` funciona do mesmo jeito, mas para o que você já assistiu.
- `/historico` mostra os itens removidos, com opção de restaurar.
- Ao tocar num título, aparece a sinopse completa, a nota, onde assistir, e
  botões pra marcar como assistido ou remover. **Essas duas ações sempre
  pedem confirmação antes de executar** ("Sim" / "Cancelar"), pra evitar
  toque acidental. Desmarcar não pede confirmação, já que é uma ação
  reversível e de baixo risco.
- Remover não apaga de vez: o item vai pro `/historico`, de onde dá pra
  restaurar a qualquer momento com o botão "♻️ Restaurar".

**Comandos diretos (sem precisar navegar pelos botões):**
- `/detalhes <id>` — mostra todos os detalhes de um item pelo número dele.
- `/marcar <id>` — marca como assistido.
- `/desmarcar <id>` — volta o item para a lista de "para assistir".
- `/renomear <id> <nome certo>` — corrige o título, caso a IA tenha
  identificado errado.
- `/genero <id> <novo gênero>` — corrige o gênero sem precisar remover e
  recadastrar o item.
- `/plataforma <id> <nova plataforma>` — corrige onde assistir, mesma
  ideia do `/genero`.
- `/stats` — mostra um resumo da sua lista: total, quantos assistidos vs.
  pendentes, quebra por Filme/Série/Anime, gênero mais comum e quantos
  você assistiu esse mês.
- `/remover <id>` — remove da lista (vai pro `/historico`, não apaga de vez).
  Diferente do botão, o comando direto não pede confirmação — digitar o ID
  exato já é uma ação deliberada.
- `/adicionar <nome>` — adiciona um título por texto explicitamente
  (principal jeito de adicionar por texto dentro de um grupo, veja a seção
  abaixo).
- `/recomendar <descrição>` — pede uma recomendação (ex: `/recomendar
  serie de comedia no Prime ou na Max`). Também dá pra só perguntar direto
  em linguagem natural ("me indica um anime bom", "sugere um filme de
  terror") em vez de usar o comando.

O número (`<id>`) de cada item aparece nas telas de detalhes e nas mensagens
de confirmação quando você adiciona algo novo.

## Pedindo recomendação

Quando você pede uma recomendação, o bot faz uma busca real na internet
(via Gemini com Google Search) pra saber o que está em alta ou bem avaliado
de acordo com o que você descreveu — gênero, plataforma, ou os dois. Ele
sempre evita sugerir algo que já está marcado como **assistido** na sua
lista (itens que ainda estão "para assistir" podem aparecer de novo, já
que tecnicamente você ainda não viu).

O bot busca até **3 opções diferentes** de uma vez (menos se não achar
tantas assim). Cada uma vem com sinopse, nota e onde assistir, e um botão
numerado (➕ 1, ➕ 2, ➕ 3) — toca no número da que você gostou pra
adicionar direto na lista, sem precisar digitar o nome de novo.

Duas formas de pedir:
- Comando explícito: `/recomendar <descrição>` (funciona em qualquer
  lugar, inclusive grupos)
- Linguagem natural: qualquer mensagem contendo palavras como "recomenda",
  "indica" ou "sugere" — funciona em conversa privada, ou em grupo
  respondendo a uma mensagem do bot (mesma regra do texto livre explicada
  na seção de grupos, abaixo)

**Filtro por nota mínima:** se você mencionar uma nota no pedido, o bot só
recomenda algo que atenda esse critério. Funciona com frases como:
- `/recomendar filme de acao com nota acima de 7`
- `serie de comedia nota >= 8.5`
- `anime bom, pelo menos 7,5`

Se nada disponível bater com o gênero/plataforma pedidos **e** a nota
mínima ao mesmo tempo, o bot avisa que não achou em vez de forçar uma
sugestão ruim.

## Estatísticas (`/stats`)

Mostra um resumo rápido: total de títulos, quantos assistidos vs.
pendentes, quebra por categoria (Filme/Série/Anime), o gênero que mais
aparece na sua lista, e quantos você assistiu no mês atual.

Um detalhe sobre o "assistidos esse mês": o bot só passou a guardar a
*data em que você marcou como assistido* (campo `watched_at`) a partir da
versão com esse recurso. Itens que já estavam marcados como assistidos
antes disso não têm essa data e não entram nessa contagem específica —
mas continuam contando normalmente no total geral de assistidos.

## Lembrete de itens parados

Todo dia, o bot verifica quem tem títulos na lista "para assistir" há mais
de 30 dias e manda uma mensagem tipo *"Você tem 3 título(s) parado(s) há
mais de 30 dias. Bora assistir algum?"*. O horário fixo é **21h UTC**
(~18h no horário de Brasília), configurado em `REMINDER_HOUR_UTC` no topo
da função `main()` em `bot.py` — mude esse valor se quiser outro horário.

Esse recurso depende do `JobQueue` do `python-telegram-bot`, que por sua
vez precisa do pacote `APScheduler`. Por isso o `requirements.txt` usa
`python-telegram-bot[job-queue]` em vez de só `python-telegram-bot`. Se
você instalar as dependências erradas essa parte fica desativada — mas o
resto do bot continua funcionando normal, só sem o lembrete diário.

## Usando o bot em um grupo

Bots do Telegram nascem com o **Modo Privacidade** ligado: por padrão, eles
só enxergam mensagens que são comandos (`/lista`, `/start`, etc.) dentro de
um grupo — texto solto e fotos passam batido. Pra esse bot funcionar
direito num grupo (reconhecer prints, por exemplo), você precisa desligar
isso:

1. Fale com o **@BotFather**
2. Envie `/mybots`, escolha o bot, depois **Bot Settings** → **Group
   Privacy** → **Turn off**
3. Essa mudança só vale pra grupos em que o bot for adicionado *depois*
   dela. Se o bot já estiver no grupo, remova ele e adicione de novo.

Com o Modo Privacidade desligado, **prints continuam funcionando
normalmente** em grupo, igual na conversa privada. A diferença é o texto
solto: pra evitar que qualquer mensagem da conversa do grupo vire item da
lista sem querer, texto sem comando só é tratado como título se for uma
**resposta direta a uma mensagem do próprio bot**. Pra adicionar um título
digitando o nome dentro de um grupo, use `/adicionar <nome>` — esse
comando funciona em qualquer lugar, sem exigir resposta a nada.

## Estrutura do projeto

```
telegram-filmes-bot/
├── bot.py                          # todo o codigo do bot
├── requirements.txt                # dependencias Python
├── Dockerfile                      # usado pelo Fly.io para montar o ambiente
├── fly.toml                        # configuracao do app no Fly.io
├── .github/workflows/fly-deploy.yml  # deploy automatico opcional (ver Passo 6)
├── .env.example                    # exemplo de variaveis de ambiente (sem valores reais)
├── .gitignore                      # garante que segredos e o banco de dados nao vao pro Git
└── README.md                       # este arquivo
```
