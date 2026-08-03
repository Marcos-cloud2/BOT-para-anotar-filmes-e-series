import html
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from datetime import time as dt_time
from io import BytesIO

from google import genai
from google.genai import types as genai_types
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "filmes.db")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

RESPONSE_FORMAT = (
    "Responda EXATAMENTE nesse formato, com cada campo em uma linha, sem markdown "
    "e sem texto extra antes ou depois:\n"
    "TITULO: <titulo oficial do filme, serie ou anime>\n"
    "TIPO: <exatamente uma das opcoes: Filme, Serie ou Anime>\n"
    "GENERO: <1 a 3 generos principais, separados por virgula, ex: Acao, Comedia>\n"
    "NOTA: <nota media do publico/critica, ex: 7.3/10, buscando em fontes como "
    "IMDb ou Rotten Tomatoes; se nao encontrar, escreva 'Nao encontrado'>\n"
    "SINOPSE: <resumo em portugues, no maximo 3 frases curtas>\n"
    "ONDE_ASSISTIR: <plataformas de streaming legais onde da pra assistir no "
    "Brasil agora (ex: Netflix, Prime Video, Max, Disney+, Globoplay, "
    "Paramount+, Star+, Apple TV+, Mubi, Crunchyroll), separadas por virgula. "
    "Pesquise ativamente antes de desistir: quase todo titulo conhecido esta "
    "em alguma dessas plataformas ou disponivel para aluguel/compra. So "
    "escreva 'Nao encontrado' se realmente nao existir nenhuma opcao legal.>"
)

ANALYSIS_PROMPT = (
    "Esta imagem e um print de rede social (Instagram, TikTok, etc) divulgando "
    "um filme, serie ou anime.\n"
    "Use a busca do Google para confirmar informacoes atuais.\n\n"
    f"{RESPONSE_FORMAT}\n\n"
    "Se a imagem nao mostrar nenhum filme, serie ou anime identificavel, "
    "responda exatamente:\nTITULO: DESCONHECIDO"
)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            media_type TEXT,
            genre TEXT,
            rating TEXT,
            synopsis TEXT,
            where_to_watch TEXT,
            raw_text TEXT,
            status TEXT NOT NULL DEFAULT 'para assistir',
            created_at TEXT NOT NULL
        )
        """
    )
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    for col in ("media_type", "genre", "rating", "synopsis", "where_to_watch", "watched_at"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()


HELP_TEXT = (
    "🎬 <b>Bot de Filmes, Series e Animes</b>\n\n"
    "Me manda um print divulgando um titulo (ou so o nome por texto) que eu "
    "identifico tipo, genero, nota, sinopse e onde assistir, e anoto na sua "
    "lista.\n\n"
    "<b>Comandos</b>\n"
    "/lista - navegar pelo que falta assistir (escolhe por plataforma ou "
    "por genero, depois vai afunilando ate o titulo)\n"
    "/assistidos - navegar pelo que ja foi assistido\n"
    "/todos - lista simples com tudo (genero e status na frente de cada "
    "titulo), toque pra ver a sinopse\n"
    "/historico - ver itens removidos e restaurar se quiser\n"
    "/stats - estatisticas da sua lista (total, genero mais comum, "
    "assistidos no mes)\n"
    "/detalhes &lt;numero&gt; - ver todos os detalhes de um item\n"
    "/marcar &lt;numero&gt; - marcar como assistido\n"
    "/desmarcar &lt;numero&gt; - voltar pra lista de assistir\n"
    "/renomear &lt;numero&gt; &lt;nome certo&gt; - corrigir o titulo\n"
    "/genero &lt;numero&gt; &lt;novo genero&gt; - corrigir o genero\n"
    "/plataforma &lt;numero&gt; &lt;nova plataforma&gt; - corrigir onde assistir\n"
    "/remover &lt;numero&gt; - remover (vai pro /historico, nao apaga de vez)\n"
    "/limpartudo - remove todos os itens da lista de uma vez (pede "
    "confirmacao, vai pro /historico)\n"
    "/adicionar &lt;nome&gt; - adicionar um titulo por texto (funciona em "
    "grupos)\n"
    "/recomendar &lt;descricao&gt; - pede uma recomendacao (ex: "
    "/recomendar filme de acao na Netflix). Busca na internet, prioriza o "
    "que esta em alta e nunca repete algo que voce ja assistiu\n\n"
    "Voce tambem pode so perguntar direto ('me recomenda uma serie de "
    "comedia', 'sugere um anime pra assistir') em vez de usar o comando — "
    "funciona em conversa privada, ou em grupo respondendo a uma mensagem "
    "do bot.\n\n"
    "Tambem da pra marcar, desmarcar e remover direto pelos botoes que "
    "aparecem no /lista e no /assistidos — marcar como assistido e remover "
    "sempre pedem confirmacao antes de executar.\n\n"
    "O numero de cada item (o que aparece como #N) e sempre a posicao dele "
    "entre os titulos ativos da sua lista — nao e um codigo fixo. Ou seja, "
    "se voce remove um item ou limpa a lista toda, os numeros se "
    "reorganizam sozinhos, sem buracos.\n\n"
    "<b>Em grupos:</b> por padrao o Telegram so deixa o bot ver mensagens "
    "que sao comandos. Prints funcionam normalmente assim que voce "
    "desativar o Modo Privacidade no @BotFather. Ja texto solto (sem "
    "comando) so e tratado como titulo se for uma resposta direta a uma "
    "mensagem do bot — assim conversa do grupo nao vira item da lista por "
    "engano. Pra adicionar por texto num grupo, use /adicionar."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


def parse_analysis(text: str) -> dict:
    result = {
        "title": "",
        "media_type": "",
        "genre": "",
        "rating": "",
        "synopsis": "",
        "where_to_watch": "",
    }
    patterns = {
        "title": re.compile(r"^TITULO\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        "media_type": re.compile(r"^TIPO\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        "genre": re.compile(r"^GENERO\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        "rating": re.compile(r"^NOTA\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        "synopsis": re.compile(r"^SINOPSE\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
        "where_to_watch": re.compile(
            r"^ONDE_ASSISTIR\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
        ),
    }
    for key, pattern in patterns.items():
        match = pattern.search(text)
        if match:
            result[key] = match.group(1).strip()
    return result


def gemini_search_config() -> genai_types.GenerateContentConfig:
    return genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
    )


async def analyze_image(buf: BytesIO) -> dict:
    image = Image.open(buf)
    image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="JPEG")
    image_bytes = out.getvalue()

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            ANALYSIS_PROMPT,
            genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        ],
        config=gemini_search_config(),
    )
    return parse_analysis((response.text or "").strip())


async def lookup_by_title(title: str) -> dict:
    prompt = (
        f"O usuario quer anotar o filme, serie ou anime chamado '{title}'.\n"
        "Use a busca do Google para confirmar informacoes atuais.\n\n"
        f"{RESPONSE_FORMAT}"
    )
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=[prompt], config=gemini_search_config()
    )
    return parse_analysis((response.text or "").strip())


def watched_titles(chat_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT title FROM items WHERE chat_id = ? AND status = 'assistido'", (chat_id,)
    ).fetchall()
    conn.close()
    return [r["title"] for r in rows]


_MIN_RATING_PATTERN = re.compile(
    r"(?:nota|avalia[cç][aã]o)?\s*"
    r"(?:>=|≥|>|acima de|maior (?:ou igual )?que|pelo menos|no m[íi]nimo|m[íi]nim[oa](?: de)?)"
    r"\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def extract_min_rating(text: str) -> float | None:
    match = _MIN_RATING_PATTERN.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_rating_value(rating_str: str) -> float | None:
    match = re.match(r"(\d+(?:[.,]\d+)?)", (rating_str or "").strip())
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


RECOMMEND_COUNT = 3


async def build_recommendations(
    chat_id: int, query_text: str, min_rating: float | None = None
) -> list:
    excluded = watched_titles(chat_id)
    excluded_text = ", ".join(excluded) if excluded else "nenhum ainda"
    rating_constraint = (
        f"A nota de cada titulo deve ser {min_rating} ou mais (numa escala de 0 a 10).\n"
        if min_rating is not None
        else ""
    )
    prompt = (
        f"O usuario pediu recomendacoes de filme, serie ou anime assim: "
        f"\"{query_text}\".\n"
        "Use a busca do Google pra saber o que esta em alta ou bem avaliado "
        "agora, de acordo com o pedido (genero, plataforma, etc, se "
        "mencionados).\n"
        f"De ate {RECOMMEND_COUNT} opcoes DIFERENTES entre si que atendam ao "
        "pedido, estejam atualmente populares ou bem avaliadas, e estejam "
        "disponiveis numa das plataformas mencionadas pelo usuario (se ele "
        "mencionou alguma).\n"
        f"{rating_constraint}"
        f"NAO inclua nenhum destes titulos, que o usuario ja assistiu: "
        f"{excluded_text}\n\n"
        f"Responda EXATAMENTE nesse formato, repetindo o bloco pra cada "
        f"opcao (se nao achar {RECOMMEND_COUNT}, retorne quantas conseguir, "
        "pode ser so 1 ou 2), sem markdown e sem texto extra:\n\n"
        "OPCAO 1\n"
        f"{RESPONSE_FORMAT}\n\n"
        "OPCAO 2\n"
        "(mesmo formato acima)\n\n"
        "OPCAO 3\n"
        "(mesmo formato acima)\n\n"
        "Se nao conseguir achar nenhuma opcao boa pro pedido, responda "
        "exatamente:\nOPCAO 1\nTITULO: DESCONHECIDO"
    )
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=[prompt], config=gemini_search_config()
    )
    text = (response.text or "").strip()
    blocks = re.split(r"OPCAO\s*\d+", text, flags=re.IGNORECASE)
    results = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        data = parse_analysis(block)
        if data.get("title") and data["title"].strip().upper() != "DESCONHECIDO":
            results.append(data)
    return results[:RECOMMEND_COUNT]


_recommend_cache: dict = {}
_recommend_next_id = 0


def cache_recommendation(chat_id: int, title: str, data: dict) -> str:
    global _recommend_next_id
    token = str(_recommend_next_id)
    _recommend_next_id += 1
    _recommend_cache[token] = {"chat_id": chat_id, "title": title, "data": data}
    if len(_recommend_cache) > 200:
        _recommend_cache.pop(next(iter(_recommend_cache)), None)
    return token


def format_option_block(idx: int, title: str, data: dict) -> str:
    lines = [f"<b>{idx}. {html.escape(title)}</b>"]
    tags = [t for t in [data.get("media_type", ""), data.get("genre", "")] if t]
    if tags:
        lines.append("🏷 " + html.escape(" · ".join(tags)))
    rating = data.get("rating", "")
    if rating and rating.lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"⭐ Nota: {html.escape(rating)}")
    synopsis = data.get("synopsis", "")
    if synopsis:
        lines.append(f"📖 {html.escape(synopsis)}")
    where = data.get("where_to_watch", "")
    if where and where.lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"📺 <b>Onde assistir:</b> {html.escape(where)}")
    return "\n".join(lines)


async def handle_recommend(update: Update, chat_id: int, query_text: str) -> None:
    if not gemini_client:
        await update.message.reply_text(
            "GEMINI_API_KEY nao configurada no bot. Peça pro admin configurar."
        )
        return

    min_rating = extract_min_rating(query_text)

    await update.message.chat.send_action("typing")
    try:
        options = await build_recommendations(chat_id, query_text, min_rating)
    except Exception:
        logger.exception("Erro ao buscar recomendacao")
        await update.message.reply_text(
            "Nao consegui buscar uma recomendacao agora. Tenta de novo daqui a pouco?"
        )
        return

    seen_titles = set()
    picked = []
    for data in options:
        title = data.get("title", "").strip()
        if not title:
            continue
        normalized = normalize_title(title)
        if normalized in seen_titles:
            continue
        got_rating = parse_rating_value(data.get("rating", ""))
        if min_rating is not None and got_rating is not None and got_rating < min_rating:
            continue  # a IA nao respeitou o filtro, descarta essa opcao
        seen_titles.add(normalized)
        picked.append((title, data))

    if not picked:
        msg = "Nao encontrei uma recomendacao boa pra esse pedido."
        if min_rating is not None:
            msg += f" Nada com nota {min_rating}+ apareceu pra esse genero/plataforma."
        msg += " Tenta descrever de outro jeito (genero, plataforma)?"
        await update.message.reply_text(msg)
        return

    blocks = []
    buttons = []
    for i, (title, data) in enumerate(picked, start=1):
        blocks.append(format_option_block(i, title, data))
        token = cache_recommendation(chat_id, title, data)
        buttons.append(InlineKeyboardButton(f"➕ {i}", callback_data=f"radd|{token}"))

    title_word = "Recomendacao" if len(picked) == 1 else "Recomendacoes"
    text = f"🎯 <b>{title_word}</b>\n\n" + "\n\n".join(blocks)
    keyboard = InlineKeyboardMarkup([buttons])
    await update.message.reply_html(text, reply_markup=keyboard)


# --- Numeracao exibida ao usuario -------------------------------------------
#
# O id real do banco (chave primaria) nunca muda e nunca e reaproveitado —
# isso e o que garante que os botoes continuem funcionando mesmo depois de
# marcar/remover itens. Mas isso faz o numero exibido ("#79") continuar
# subindo pra sempre, mesmo depois de limpar a lista toda.
#
# Pra resolver isso, o numero que o usuario VE e digita (nos comandos e nas
# mensagens) e calculado na hora, como a posicao do item entre os itens
# ativos (nao removidos) daquele chat, ordenados pelo id real. Isso faz os
# numeros sempre ficarem sem buracos: 1, 2, 3... e depois de zerar a lista,
# o proximo item cadastrado volta a ser o #1 automaticamente.


def active_order_map(chat_id: int) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM items WHERE chat_id = ? AND status != 'removido' ORDER BY id ASC",
        (chat_id,),
    ).fetchall()
    conn.close()
    return {r["id"]: i + 1 for i, r in enumerate(rows)}


def get_display_number(chat_id: int, real_id: int) -> int | None:
    return active_order_map(chat_id).get(real_id)


def resolve_display_number(chat_id: int, display_number: int) -> int | None:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM items WHERE chat_id = ? AND status != 'removido' ORDER BY id ASC",
        (chat_id,),
    ).fetchall()
    conn.close()
    if display_number < 1 or display_number > len(rows):
        return None
    return rows[display_number - 1]["id"]


def item_number(row: sqlite3.Row, order_map: dict | None = None) -> int:
    if row["status"] == "removido":
        return row["id"]
    if order_map is not None:
        return order_map.get(row["id"], row["id"])
    num = get_display_number(row["chat_id"], row["id"])
    return num if num is not None else row["id"]


# --- Normalizacao de campos para agrupamento --------------------------------

MEDIA_TYPE_ICON = {"Filme": "🎬", "Série": "📺", "Anime": "🈴"}
UNKNOWN_PLATFORM = "Plataforma não encontrada"
UNKNOWN_GENRE = "Sem gênero"


def platform_of(row: sqlite3.Row) -> str:
    wtw = (row["where_to_watch"] or "").strip()
    if not wtw or wtw.lower() == "nao encontrado" or wtw.lower() == "não encontrado":
        return UNKNOWN_PLATFORM
    first = wtw.split(",")[0].strip()
    return first or UNKNOWN_PLATFORM


def category_of(row: sqlite3.Row) -> str:
    raw = (row["media_type"] or "").strip().lower()
    if raw.startswith("ser"):
        return "Série"
    if raw.startswith("anim"):
        return "Anime"
    return "Filme"


def genres_of(row: sqlite3.Row) -> list:
    raw = (row["genre"] or "").strip()
    if not raw:
        return [UNKNOWN_GENRE]
    return [g.strip() for g in raw.split(",") if g.strip()]


def unique_sorted(values) -> list:
    return sorted(set(values), key=lambda s: s.lower())


def rating_prefix(row: sqlite3.Row) -> str:
    rating = (row["rating"] or "").strip()
    if not rating or rating.lower() in ("nao encontrado", "não encontrado"):
        return ""
    number = rating.split("/")[0].strip()
    return f"⭐{number}"


def item_button_label(row: sqlite3.Row) -> str:
    prefix = rating_prefix(row)
    label = f"{prefix} {row['title']}".strip() if prefix else row["title"]
    if len(label) > 60:
        label = label[:57] + "..."
    return label


def all_items_button_label(row: sqlite3.Row, order_map: dict | None = None) -> str:
    # Telegram nao deixa colorir o texto do botao; usamos um circulo colorido
    # como aproximacao visual: verde = assistido, amarelo = pendente.
    status_icon = "🟢" if row["status"] == "assistido" else "🟡"
    genre_list = genres_of(row)
    genre = genre_list[0] if genre_list and genre_list[0] != UNKNOWN_GENRE else ""
    label = f"#{item_number(row, order_map)} {status_icon} {row['title']}"
    if genre:
        label += f" ({genre})"
    if len(label) > 60:
        label = label[:57] + "..."
    return label


def format_new_item_message(item_id: int, title: str, data: dict) -> str:
    genre = data.get("genre", "")
    rating = data.get("rating", "")
    synopsis = data.get("synopsis", "")
    where = data.get("where_to_watch", "")
    media_type = data.get("media_type", "") or "Filme"

    lines = [f"✅ <b>Anotado</b> #{item_id}: <b>{html.escape(title)}</b>"]
    tags = [t for t in [media_type, genre] if t]
    if tags:
        lines.append("🏷 " + html.escape(" · ".join(tags)))
    if rating and rating.lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"⭐ Nota: {html.escape(rating)}")
    if synopsis:
        lines.append(f"\n📖 {html.escape(synopsis)}")
    if where and where.lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"\n📺 <b>Onde assistir:</b> {html.escape(where)}")
    lines.append(f"\n<i>Titulo errado? Corrija com</i> /renomear {item_id} Nome Certo")
    return "\n".join(lines)


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w]+", "", title.strip().lower())


def find_duplicate(chat_id: int, title: str):
    normalized = normalize_title(title)
    if not normalized:
        return None
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND status != 'removido'", (chat_id,)
    ).fetchall()
    conn.close()
    for row in rows:
        if normalize_title(row["title"]) == normalized:
            return row
    return None


async def warn_duplicate(update: Update, chat_id: int, row: sqlite3.Row) -> None:
    status_label = "assistido ✅" if row["status"] == "assistido" else "na sua lista pra assistir 🍿"
    text = (
        f"⚠️ <b>{html.escape(row['title'])}</b> ja esta {status_label} (#{item_number(row)}). "
        f"Nao adicionei de novo pra evitar duplicar."
    )
    path = resolve_path_for_row(chat_id, row)
    _, keyboard = build_detail_view(row, path)
    await update.message.reply_html(text, reply_markup=keyboard)


def insert_new_item(chat_id: int, title: str, data: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO items "
        "(chat_id, title, media_type, genre, rating, synopsis, where_to_watch, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            chat_id,
            title[:200],
            (data.get("media_type") or "Filme")[:20],
            (data.get("genre") or "")[:150] or None,
            (data.get("rating") or "")[:20] or None,
            (data.get("synopsis") or "")[:1000] or None,
            (data.get("where_to_watch") or "")[:300] or None,
            "para assistir",
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


async def save_item(update: Update, chat_id: int, title: str, data: dict) -> None:
    duplicate = find_duplicate(chat_id, title)
    if duplicate:
        await warn_duplicate(update, chat_id, duplicate)
        return

    item_id = insert_new_item(chat_id, title, data)
    number = get_display_number(chat_id, item_id) or item_id
    await update.message.reply_html(format_new_item_message(number, title, data))


async def save_item_from_image(update: Update, chat_id: int, buf: BytesIO) -> None:
    if not gemini_client:
        await update.message.reply_text(
            "GEMINI_API_KEY nao configurada no bot. Peça pro admin configurar, "
            "ou me manda o nome do filme/serie direto por texto."
        )
        return

    await update.message.chat.send_action("typing")

    try:
        data = await analyze_image(buf)
    except Exception:
        logger.exception("Erro ao identificar imagem com Gemini")
        await update.message.reply_text(
            "Nao consegui analisar essa imagem agora. Voce pode me mandar o nome direto?"
        )
        return

    title = data.get("title", "").strip()
    if not title or title.upper() == "DESCONHECIDO":
        await update.message.reply_text(
            "Nao consegui identificar nenhum filme, serie ou anime nessa imagem. "
            "Me manda o nome direto por texto?"
        )
        return

    await save_item(update, chat_id, title, data)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    buf = BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    await save_item_from_image(update, chat_id, buf)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if not document.mime_type or not document.mime_type.startswith("image/"):
        return

    chat_id = update.effective_chat.id
    file = await context.bot.get_file(document.file_id)
    buf = BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    await save_item_from_image(update, chat_id, buf)


async def process_title_text(update: Update, chat_id: int, title: str) -> None:
    title = title.strip()
    if not title:
        return

    data = {}
    if gemini_client:
        await update.message.chat.send_action("typing")
        try:
            data = await lookup_by_title(title)
            if data.get("title"):
                title = data["title"]
        except Exception:
            logger.exception("Erro ao buscar informacoes do titulo")

    await save_item(update, chat_id, title, data)


_RECOMMEND_TRIGGERS = re.compile(
    r"\b(recomend\w*|indic\w*|sugest\w*|sugir\w*|sugere\w*)\b", re.IGNORECASE
)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Em grupos/canais, so tratamos texto solto se for resposta direta a
    # uma mensagem do proprio bot (evita anotar conversa alheia como se
    # fosse nome de filme). Em conversa privada, funciona sempre.
    if update.effective_chat.type != "private":
        replied = update.message.reply_to_message
        is_reply_to_bot = bool(
            replied and replied.from_user and replied.from_user.id == context.bot.id
        )
        if not is_reply_to_bot:
            return

    chat_id = update.effective_chat.id
    text = update.message.text or ""

    if _RECOMMEND_TRIGGERS.search(text):
        await handle_recommend(update, chat_id, text)
        return

    await process_title_text(update, chat_id, text)


async def adicionar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /adicionar <nome do filme, serie ou anime>")
        return
    chat_id = update.effective_chat.id
    title = " ".join(context.args)
    await process_title_text(update, chat_id, title)


async def recomendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Uso: /recomendar <descricao>\n"
            "Ex: /recomendar filme de acao na Netflix"
        )
        return
    chat_id = update.effective_chat.id
    query_text = " ".join(context.args)
    await handle_recommend(update, chat_id, query_text)


# --- Navegacao interativa: por Plataforma ou por Genero --------------------
#
# O usuario escolhe primeiro o modo (plataforma ou genero) e depois vai
# afunilando por botoes ate chegar no titulo. Cada modo percorre as mesmas
# 3 dimensoes (plataforma, categoria, genero) em ordens diferentes:
#   modo "f" (plataforma primeiro): plataforma -> categoria -> genero
#   modo "g" (genero primeiro):     genero -> categoria -> plataforma

STATUS_BY_KEY = {"p": "para assistir", "a": "assistido", "r": "removido"}
KEY_BY_STATUS = {v: k for k, v in STATUS_BY_KEY.items()}
LIST_TITLES = {"p": "🍿 Para assistir", "a": "✅ Ja assistidos", "r": "🗑 Historico de removidos"}

DIM_ORDER = {"f": ["plat", "cat", "genre"], "g": ["genre", "cat", "plat"], "t": []}
DIM_ICON = {"plat": "📺", "cat": None, "genre": "🏷"}  # cat usa MEDIA_TYPE_ICON
DIM_LABEL = {"plat": "plataforma", "cat": "categoria", "genre": "genero"}
MODE_LABEL = {"f": "Por plataforma", "g": "Por genero", "t": "📋 Todos os titulos"}


def fetch_rows(chat_id: int, status_key: str) -> list:
    if status_key == "t":
        return fetch_all_rows(chat_id)
    status = STATUS_BY_KEY[status_key]
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND status = ? ORDER BY id",
        (chat_id, status),
    ).fetchall()
    conn.close()
    return rows


def fetch_all_rows(chat_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND status != 'removido' ORDER BY id ASC",
        (chat_id,),
    ).fetchall()
    conn.close()
    return rows


def dim_values(dim: str, rows: list) -> list:
    if dim == "plat":
        return unique_sorted(platform_of(r) for r in rows)
    if dim == "cat":
        return unique_sorted(category_of(r) for r in rows)
    genres = set()
    for r in rows:
        genres.update(genres_of(r))
    return unique_sorted(genres)


def dim_filter(dim: str, value: str, rows: list) -> list:
    if dim == "plat":
        return [r for r in rows if platform_of(r) == value]
    if dim == "cat":
        return [r for r in rows if category_of(r) == value]
    return [r for r in rows if value in genres_of(r)]


def dim_icon(dim: str, value: str) -> str:
    if dim == "cat":
        return MEDIA_TYPE_ICON.get(value, "🎞")
    return DIM_ICON[dim]


class NavError(Exception):
    pass


def resolve_nav(rows: list, mode: str, indices: list):
    """Aplica os filtros das dimensoes ja escolhidas. Retorna (breadcrumb, rows_filtradas)."""
    dims = DIM_ORDER[mode]
    breadcrumb = []
    current = rows
    for dim, idx in zip(dims, indices):
        values = dim_values(dim, current)
        if idx < 0 or idx >= len(values):
            raise NavError()
        value = values[idx]
        breadcrumb.append((dim, value))
        current = dim_filter(dim, value, current)
    return breadcrumb, current


def nav_callback(status_key: str, mode: str, indices: list) -> str:
    parts = ["n", status_key, mode] + [str(i) for i in indices]
    return "|".join(parts)


def kb_root(status_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📺 Por plataforma", callback_data=f"n|{status_key}|f")],
            [InlineKeyboardButton("🏷 Por genero", callback_data=f"n|{status_key}|g")],
        ]
    )


def kb_dim_options(status_key: str, mode: str, indices: list, rows: list) -> InlineKeyboardMarkup:
    dims = DIM_ORDER[mode]
    dim = dims[len(indices)]
    values = dim_values(dim, rows)
    buttons = [
        [
            InlineKeyboardButton(
                f"{dim_icon(dim, v)} {v}",
                callback_data=nav_callback(status_key, mode, indices + [i]),
            )
        ]
        for i, v in enumerate(values)
    ]
    back_cb = f"root|{status_key}" if not indices else nav_callback(status_key, mode, indices[:-1])
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=back_cb)])
    return InlineKeyboardMarkup(buttons)


TODOS_PAGE_SIZE = 10


def kb_items(status_key: str, mode: str, indices: list, rows: list) -> InlineKeyboardMarkup:
    if mode == "t":
        page = indices[0] if indices else 0
        start = page * TODOS_PAGE_SIZE
        page_rows = rows[start : start + TODOS_PAGE_SIZE]
        order_map = active_order_map(rows[0]["chat_id"]) if rows else {}
        buttons = [
            [
                InlineKeyboardButton(
                    all_items_button_label(r, order_map),
                    callback_data=f"v|{r['id']}|{status_key}|{mode}|{page}",
                )
            ]
            for r in page_rows
        ]
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"todos|{page - 1}"))
        if start + TODOS_PAGE_SIZE < len(rows):
            nav_row.append(InlineKeyboardButton("Proxima ➡️", callback_data=f"todos|{page + 1}"))
        if nav_row:
            buttons.append(nav_row)
        return InlineKeyboardMarkup(buttons)

    buttons = [
        [
            InlineKeyboardButton(
                item_button_label(r),
                callback_data="|".join(["v", str(r["id"]), status_key, mode] + [str(i) for i in indices]),
            )
        ]
        for r in rows
    ]
    back_cb = nav_callback(status_key, mode, indices[:-1])
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=back_cb)])
    return InlineKeyboardMarkup(buttons)


def breadcrumb_text(breadcrumb: list) -> str:
    return " · ".join(f"{dim_icon(d, v)} {html.escape(v)}" for d, v in breadcrumb)


STATUS_LABEL = {
    "para assistir": "Para assistir 🍿",
    "assistido": "Assistido ✅",
    "removido": "Removido 🗑",
}


def item_detail_text(row: sqlite3.Row) -> str:
    date_str = row["created_at"][:10] if row["created_at"] else "?"
    lines = [f"🎬 <b>{html.escape(row['title'])}</b> (#{item_number(row)})"]
    tags = [t for t in [category_of(row), row["genre"]] if t]
    if tags:
        lines.append("🏷 " + html.escape(" · ".join(tags)))
    if row["rating"] and row["rating"].lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"⭐ Nota: {html.escape(row['rating'])}")
    lines.append(f"Status: {STATUS_LABEL.get(row['status'], row['status'])}")
    lines.append(f"Adicionado em: {date_str}")
    if row["synopsis"]:
        lines.append(f"\n📖 {html.escape(row['synopsis'])}")
    if row["where_to_watch"] and row["where_to_watch"].lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"\n📺 <b>Onde assistir:</b> {html.escape(row['where_to_watch'])}")
    return "\n".join(lines)


def build_detail_view(row: sqlite3.Row, path: tuple):
    status_key, mode, indices = path
    text = item_detail_text(row)

    suffix = "|".join([str(row["id"]), status_key, mode] + [str(i) for i in indices])
    if mode == "t":
        back_cb = f"todos|{indices[0]}" if indices else "todos"
    else:
        back_cb = nav_callback(status_key, mode, indices)
    back_button = InlineKeyboardButton("⬅️ Voltar", callback_data=back_cb)

    if row["status"] == "assistido":
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("↩️ Desmarcar", callback_data=f"u|{suffix}")],
                [InlineKeyboardButton("🗑 Remover", callback_data=f"cx|{suffix}")],
                [back_button],
            ]
        )
    elif row["status"] == "removido":
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("♻️ Restaurar", callback_data=f"dr|{suffix}")],
                [back_button],
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Marcar como assistido", callback_data=f"cm|{suffix}")],
                [InlineKeyboardButton("🗑 Remover", callback_data=f"cx|{suffix}")],
                [back_button],
            ]
        )
    return text, keyboard


def build_confirm_view(row: sqlite3.Row, action: str, suffix: str):
    if action == "m":
        question = f"Confirma marcar <b>{html.escape(row['title'])}</b> como assistido?"
        yes_label, yes_cb = "✅ Sim, marcar", f"dm|{suffix}"
    else:
        question = (
            f"Confirma remover <b>{html.escape(row['title'])}</b> da lista?\n"
            f"<i>Fica guardado no /historico, da pra restaurar depois.</i>"
        )
        yes_label, yes_cb = "🗑 Sim, remover", f"dx|{suffix}"

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(yes_label, callback_data=yes_cb)],
            [InlineKeyboardButton("↩️ Cancelar", callback_data=f"v|{suffix}")],
        ]
    )
    return f"⚠️ {question}", keyboard


async def send_list(update: Update, chat_id: int, status_key: str) -> None:
    rows = fetch_rows(chat_id, status_key)
    title = LIST_TITLES[status_key]
    if not rows:
        await update.message.reply_html(f"{title}\n\n<i>Vazio por aqui.</i>")
        return
    await update.message.reply_html(
        f"{title}\n\nVoce gostaria de assistir por plataforma ou por genero?",
        reply_markup=kb_root(status_key),
    )


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_list(update, update.effective_chat.id, "p")


async def assistidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_list(update, update.effective_chat.id, "a")


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_list(update, update.effective_chat.id, "r")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND status != 'removido'", (chat_id,)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_html("📊 <b>Estatisticas</b>\n\n<i>Sua lista esta vazia.</i>")
        return

    total = len(rows)
    watched_rows = [r for r in rows if r["status"] == "assistido"]
    pending = total - len(watched_rows)

    by_category: dict = {}
    genre_counts: dict = {}
    for r in rows:
        cat = category_of(r)
        by_category[cat] = by_category.get(cat, 0) + 1
        for g in genres_of(r):
            if g == UNKNOWN_GENRE:
                continue
            genre_counts[g] = genre_counts.get(g, 0) + 1

    now = datetime.utcnow()
    watched_this_month = 0
    for r in watched_rows:
        wa = r["watched_at"]
        if not wa:
            continue
        try:
            dt = datetime.fromisoformat(wa)
        except ValueError:
            continue
        if dt.year == now.year and dt.month == now.month:
            watched_this_month += 1

    lines = ["📊 <b>Estatisticas</b>", ""]
    lines.append(f"Total na lista: <b>{total}</b>")
    lines.append(f"✅ Assistidos: {len(watched_rows)}   🍿 Para assistir: {pending}")

    if by_category:
        cat_parts = [
            f"{MEDIA_TYPE_ICON.get(c, '')} {c}: {n}"
            for c, n in sorted(by_category.items(), key=lambda kv: -kv[1])
        ]
        lines.append(" · ".join(cat_parts))

    if genre_counts:
        top_genre, top_count = max(genre_counts.items(), key=lambda kv: kv[1])
        lines.append(f"🏷 Genero mais comum: {html.escape(top_genre)} ({top_count}x)")

    lines.append(f"📅 Assistidos esse mes: {watched_this_month}")

    await update.message.reply_html("\n".join(lines))


def todos_header(rows: list, page: int) -> tuple:
    total_pages = max(1, (len(rows) + TODOS_PAGE_SIZE - 1) // TODOS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    header = MODE_LABEL["t"]
    if total_pages > 1:
        header += f" (pagina {page + 1}/{total_pages})"
    return header, page


async def todos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    rows = fetch_rows(chat_id, "t")
    if not rows:
        await update.message.reply_html(f"{MODE_LABEL['t']}\n\n<i>Vazio por aqui.</i>")
        return
    header, page = todos_header(rows, 0)
    await update.message.reply_html(
        f"{header}\n\nToque num titulo:",
        reply_markup=kb_items("t", "t", [page], rows),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat.id
    parts = query.data.split("|")
    action = parts[0]

    try:
        if action == "cwipecancel":
            await query.answer("Cancelado")
            await query.edit_message_text("Ok, nada foi removido.")
            return

        if action == "dwipe":
            conn = get_conn()
            cur = conn.execute(
                "UPDATE items SET status = 'removido' WHERE chat_id = ? AND status != 'removido'",
                (chat_id,),
            )
            conn.commit()
            count = cur.rowcount
            conn.close()
            await query.answer("Lista limpa 🗑")
            await query.edit_message_text(
                f"🗑 {count} item(ns) removido(s). Todos ficaram guardados no /historico, "
                f"da pra restaurar um por um se precisar."
            )
            return

        if action == "radd":
            token = parts[1]
            entry = _recommend_cache.pop(token, None)
            await query.answer()
            if not entry:
                await query.edit_message_text(
                    "Essa recomendacao expirou. Peça uma nova com /recomendar."
                )
                return
            r_chat_id, title, data = entry["chat_id"], entry["title"], entry["data"]
            duplicate = find_duplicate(r_chat_id, title)
            if duplicate:
                status_label = (
                    "assistido ✅" if duplicate["status"] == "assistido" else "na sua lista pra assistir 🍿"
                )
                await query.edit_message_text(
                    f"⚠️ <b>{html.escape(title)}</b> ja esta {status_label} "
                    f"(#{item_number(duplicate)}).",
                    parse_mode="HTML",
                )
                return
            item_id = insert_new_item(r_chat_id, title, data)
            number = get_display_number(r_chat_id, item_id) or item_id
            await query.edit_message_text(
                format_new_item_message(number, title, data), parse_mode="HTML"
            )
            return

        if action == "todos":
            page = int(parts[1]) if len(parts) > 1 else 0
            rows = fetch_rows(chat_id, "t")
            await query.answer()
            if not rows:
                await query.edit_message_text(f"{MODE_LABEL['t']}\n\nVazio por aqui.")
                return
            header, page = todos_header(rows, page)
            await query.edit_message_text(
                f"{header}\n\nToque num titulo:",
                reply_markup=kb_items("t", "t", [page], rows),
            )
            return

        if action == "root":
            status_key = parts[1]
            rows = fetch_rows(chat_id, status_key)
            await query.answer()
            if not rows:
                await query.edit_message_text(f"{LIST_TITLES[status_key]}\n\nVazio por aqui.")
                return
            await query.edit_message_text(
                f"{LIST_TITLES[status_key]}\n\nVoce gostaria de assistir por plataforma ou por genero?",
                reply_markup=kb_root(status_key),
            )
            return

        if action == "n":
            status_key, mode = parts[1], parts[2]
            indices = [int(p) for p in parts[3:]]
            rows = fetch_rows(chat_id, status_key)
            breadcrumb, current_rows = resolve_nav(rows, mode, indices)
            await query.answer()

            header = f"{MODE_LABEL[mode]}"
            if breadcrumb:
                header = breadcrumb_text(breadcrumb)

            if len(indices) < 3:
                next_dim = DIM_ORDER[mode][len(indices)]
                await query.edit_message_text(
                    f"{header}\n\nEscolha {DIM_LABEL[next_dim]}:",
                    parse_mode="HTML",
                    reply_markup=kb_dim_options(status_key, mode, indices, current_rows),
                )
            else:
                await query.edit_message_text(
                    f"{header}\n\nToque num titulo:",
                    parse_mode="HTML",
                    reply_markup=kb_items(status_key, mode, indices, current_rows),
                )
            return

        if action == "v":
            item_id = int(parts[1])
            status_key, mode = parts[2], parts[3]
            indices = [int(p) for p in parts[4:]]
            conn = get_conn()
            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
            ).fetchone()
            conn.close()
            await query.answer()
            if not row:
                await query.edit_message_text("Nao achei esse item (pode ter sido removido).")
                return
            text, keyboard = build_detail_view(row, (status_key, mode, indices))
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        if action in ("cm", "cx"):
            item_id = int(parts[1])
            suffix = "|".join(parts[1:])
            conn = get_conn()
            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
            ).fetchone()
            conn.close()
            await query.answer()
            if not row:
                await query.edit_message_text("Nao achei esse item (pode ter sido removido).")
                return
            confirm_action = "m" if action == "cm" else "x"
            text, keyboard = build_confirm_view(row, confirm_action, suffix)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        if action in ("dm", "u", "dx", "dr"):
            item_id = int(parts[1])
            status_key, mode = parts[2], parts[3]
            indices = [int(p) for p in parts[4:]]

            conn = get_conn()
            if action == "dm":
                conn.execute(
                    "UPDATE items SET status = 'assistido', watched_at = ? WHERE id = ? AND chat_id = ?",
                    (datetime.utcnow().isoformat(), item_id, chat_id),
                )
                conn.commit()
                await query.answer("Marcado como assistido ✅")
            elif action == "u":
                conn.execute(
                    "UPDATE items SET status = 'para assistir', watched_at = NULL WHERE id = ? AND chat_id = ?",
                    (item_id, chat_id),
                )
                conn.commit()
                await query.answer("Voltou pra lista de assistir 🍿")
            elif action == "dx":
                conn.execute(
                    "UPDATE items SET status = 'removido' WHERE id = ? AND chat_id = ?",
                    (item_id, chat_id),
                )
                conn.commit()
                await query.answer("Removido 🗑")
            else:  # dr - restaurar do historico
                conn.execute(
                    "UPDATE items SET status = 'para assistir' WHERE id = ? AND chat_id = ?",
                    (item_id, chat_id),
                )
                conn.commit()
                await query.answer("Restaurado ♻️")

            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
            ).fetchone()
            conn.close()
            # A acao pode mudar o status do item pra fora da lista onde ele estava
            # (ex: removido some do "p"/"a"); manda pra tela de detalhes do novo status.
            new_status_key = KEY_BY_STATUS.get(row["status"], status_key)
            path = (new_status_key, mode, indices) if new_status_key == status_key else resolve_path_for_row(chat_id, row, mode)
            text, keyboard = build_detail_view(row, path)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        await query.answer()
    except NavError:
        await query.answer()
        await query.edit_message_text(
            "Essa lista mudou desde que voce abriu. Manda /lista ou /assistidos de novo."
        )


def resolve_path_for_row(chat_id: int, row: sqlite3.Row, mode: str = "f") -> tuple:
    status_key = KEY_BY_STATUS.get(row["status"], "p")
    if mode == "t":
        return status_key, "t", [0]
    rows = fetch_rows(chat_id, status_key)
    dims = DIM_ORDER[mode]
    row_value_of = {"plat": platform_of(row), "cat": category_of(row), "genre": (genres_of(row) or [UNKNOWN_GENRE])[0]}

    indices = []
    current = rows
    for dim in dims:
        values = dim_values(dim, current)
        target = row_value_of[dim]
        idx = values.index(target) if target in values else 0
        indices.append(idx)
        value = values[idx] if values else target
        current = dim_filter(dim, value, current)
    return status_key, mode, indices


async def detalhes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /detalhes <numero>")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numero invalido.")
        return

    item_id = resolve_display_number(chat_id, number)
    if item_id is None:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
    ).fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    path = resolve_path_for_row(chat_id, row)
    text, keyboard = build_detail_view(row, path)
    await update.message.reply_html(text, reply_markup=keyboard)


async def marcar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_status(update, context, "assistido", "Marcado como assistido ✅")


async def desmarcar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_status(update, context, "para assistir", "Voltou pra lista de assistir 🍿")


async def set_status(update, context, status, ok_msg):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /marcar <numero>")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numero invalido.")
        return

    item_id = resolve_display_number(chat_id, number)
    if item_id is None:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    watched_at = datetime.utcnow().isoformat() if status == "assistido" else None
    conn = get_conn()
    conn.execute(
        "UPDATE items SET status = ?, watched_at = ? WHERE id = ? AND chat_id = ?",
        (status, watched_at, item_id, chat_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{ok_msg}: #{number}")


async def renomear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /renomear <numero> <novo nome>")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numero invalido.")
        return
    new_title = " ".join(context.args[1:])

    item_id = resolve_display_number(chat_id, number)
    if item_id is None:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    conn = get_conn()
    conn.execute(
        "UPDATE items SET title = ? WHERE id = ? AND chat_id = ?",
        (new_title, item_id, chat_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Renomeado #{number} para: {new_title}")


async def set_field(update, context, column: str, label: str, usage: str) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(usage)
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numero invalido.")
        return
    new_value = " ".join(context.args[1:])

    item_id = resolve_display_number(chat_id, number)
    if item_id is None:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    conn = get_conn()
    conn.execute(
        f"UPDATE items SET {column} = ? WHERE id = ? AND chat_id = ?",
        (new_value, item_id, chat_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{label} de #{number} atualizado(a) para: {new_value}")


async def genero(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_field(update, context, "genre", "Genero", "Uso: /genero <numero> <novo genero>")


async def plataforma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_field(
        update, context, "where_to_watch", "Plataforma",
        "Uso: /plataforma <numero> <nova(s) plataforma(s)>",
    )


async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /remover <numero>")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numero invalido.")
        return

    item_id = resolve_display_number(chat_id, number)
    if item_id is None:
        await update.message.reply_text("Nao achei esse numero na sua lista.")
        return

    conn = get_conn()
    conn.execute(
        "UPDATE items SET status = 'removido' WHERE id = ? AND chat_id = ? AND status != 'removido'",
        (item_id, chat_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"Removido #{number} 🗑 (fica guardado no /historico, da pra restaurar depois)"
    )


async def limpartudo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM items WHERE chat_id = ? AND status != 'removido'",
        (chat_id,),
    ).fetchone()["cnt"]
    conn.close()

    if not total:
        await update.message.reply_text("Sua lista ja esta vazia.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🗑 Sim, limpar os {total} itens", callback_data="dwipe")],
            [InlineKeyboardButton("↩️ Cancelar", callback_data="cwipecancel")],
        ]
    )
    await update.message.reply_html(
        f"⚠️ Confirma remover <b>todos os {total} itens</b> da sua lista?\n"
        f"<i>Ficam guardados no /historico, da pra restaurar um por um se precisar.</i>",
        reply_markup=keyboard,
    )


REMINDER_STALE_DAYS = 30
REMINDER_HOUR_UTC = 21  # ~18h no horario de Brasilia (UTC-3)


async def send_stale_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    cutoff = (datetime.utcnow() - timedelta(days=REMINDER_STALE_DAYS)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT chat_id, COUNT(*) as cnt FROM items "
        "WHERE status = 'para assistir' AND created_at < ? "
        "GROUP BY chat_id",
        (cutoff,),
    ).fetchall()
    conn.close()

    for row in rows:
        chat_id, count = row["chat_id"], row["cnt"]
        try:
            await context.bot.send_message(
                chat_id,
                f"📌 Voce tem {count} titulo(s) parado(s) ha mais de "
                f"{REMINDER_STALE_DAYS} dias na lista. Bora assistir algum? "
                f"Da uma olhada no /todos",
            )
        except Exception:
            logger.exception("Erro ao enviar lembrete pro chat %s", chat_id)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Defina a variavel de ambiente TELEGRAM_BOT_TOKEN")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("assistidos", assistidos))
    app.add_handler(CommandHandler("historico", historico))
    app.add_handler(CommandHandler("todos", todos))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("adicionar", adicionar))
    app.add_handler(CommandHandler("recomendar", recomendar))
    app.add_handler(CommandHandler("detalhes", detalhes))
    app.add_handler(CommandHandler("marcar", marcar))
    app.add_handler(CommandHandler("desmarcar", desmarcar))
    app.add_handler(CommandHandler("renomear", renomear))
    app.add_handler(CommandHandler("genero", genero))
    app.add_handler(CommandHandler("plataforma", plataforma))
    app.add_handler(CommandHandler("remover", remover))
    app.add_handler(CommandHandler("limpartudo", limpartudo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if app.job_queue:
        app.job_queue.run_daily(
            send_stale_reminders, time=dt_time(hour=REMINDER_HOUR_UTC, minute=0)
        )
    else:
        logger.warning(
            "JobQueue indisponivel (falta a extra [job-queue]) — lembrete diario desativado."
        )

    logger.info("Bot iniciado, aguardando mensagens...")
    app.run_polling()


if __name__ == "__main__":
    main()
