# Bot de Filmes/Series (Telegram)

Manda um print divulgando um filme ou serie no Telegram e o bot identifica o
titulo usando IA (Gemini), busca a sinopse e onde assistir, e anota numa
lista. Depois voce consulta o que falta assistir.

## Comandos
- Manda uma **foto** (print) -> ele identifica o filme/serie, busca sinopse e
  onde assistir, e anota
- Manda um **texto** -> anota o texto como titulo e tambem busca sinopse/onde
  assistir
- `/lista` - o que falta assistir (com data que foi adicionado)
- `/assistidos` - o que ja foi assistido
- `/detalhes <id>` - ve sinopse, onde assistir, status e data completos
- `/marcar <id>` - marca como assistido
- `/desmarcar <id>` - volta pra lista de assistir
- `/renomear <id> <nome certo>` - corrige o titulo
- `/remover <id>` - apaga da lista

## 1. Criar o bot no Telegram
1. Abra o Telegram e fale com **@BotFather**
2. Envie `/newbot`, escolha um nome e um username (precisa terminar em `bot`)
3. Ele te devolve um **token** — guarde ele, e NUNCA suba ele pro Git

## 2. Criar uma chave do Gemini
1. Acesse https://aistudio.google.com/apikey
2. Clique em **Create API Key** (ja ativa o uso gratuito automaticamente)
3. Guarde a chave — NUNCA suba ela pro Git

## 3. Configurar variaveis de ambiente
Copie `.env.example` para `.env` (esse arquivo e ignorado pelo Git, veja
`.gitignore`) e preencha com seus valores:

```
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
```

## 4. Rodar local
```bash
cd telegram-filmes-bot
pip install -r requirements.txt
```

No PowerShell:
```powershell
$env:TELEGRAM_BOT_TOKEN = "SEU_TOKEN_AQUI"
$env:GEMINI_API_KEY = "SUA_CHAVE_AQUI"
python bot.py
```

Ai é so mandar um print pro seu bot no Telegram.

## 5. Deploy no Render (fica online 24/7)
1. Suba essa pasta `telegram-filmes-bot` pra um repositorio no GitHub (as
   variaveis sensiveis ficam de fora automaticamente por causa do
   `.gitignore` — elas nunca sao commitadas)
2. Em https://render.com, crie um **New > Background Worker**
3. Conecte o repositorio, ele vai detectar o `Dockerfile` automaticamente
4. Em **Environment > Environment Variables**, adicione:
   - `TELEGRAM_BOT_TOKEN` = o token do BotFather
   - `GEMINI_API_KEY` = a chave do Google AI Studio
5. Deploy. Nos logs deve aparecer "Bot iniciado, aguardando mensagens..."

### Sobre o armazenamento (importante)
O bot salva a lista num arquivo `filmes.db` (SQLite) dentro do container.
No plano **free** do Render, o disco é apagado a cada novo deploy/restart —
ou seja, sua lista pode ser perdida quando voce atualizar o codigo.

Se quiser manter a lista permanente, duas opcoes:
- Adicionar um **Persistent Disk** no Render (plano pago) montado em `/app`
- Trocar o SQLite por um banco externo gratuito (ex: Postgres free tier do
  proprio Render ou Supabase) — se quiser, eu ajusto o codigo depois

Por enquanto, pra comecar a usar e testar o fluxo, o SQLite local ja resolve.
