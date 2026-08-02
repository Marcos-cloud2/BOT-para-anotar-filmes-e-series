import html
import logging
import os
import re
import sqlite3
from datetime import datetime
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
    for col in ("media_type", "genre", "rating", "synopsis", "where_to_watch"):
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
    "/lista - navegar pelo que falta assistir (plataforma → categoria → "
    "genero → titulo)\n"
    "/assistidos - navegar pelo que ja foi assistido\n"
    "/detalhes &lt;id&gt; - ver todos os detalhes de um item pelo numero\n"
    "/marcar &lt;id&gt; - marcar como assistido\n"
    "/desmarcar &lt;id&gt; - voltar pra lista de assistir\n"
    "/renomear &lt;id&gt; &lt;nome certo&gt; - corrigir o titulo\n"
    "/remover &lt;id&gt; - apagar da lista\n\n"
    "Tambem da pra marcar, desmarcar e remover direto pelos botoes que "
    "aparecem no /lista e no /assistidos."
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


async def save_item(update: Update, chat_id: int, title: str, data: dict) -> None:
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

    await update.message.reply_html(format_new_item_message(item_id, title, data))


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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    title = update.message.text.strip()
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


# --- Navegacao interativa: Plataforma -> Categoria -> Genero -> Titulo -----

STATUS_BY_KEY = {"p": "para assistir", "a": "assistido"}
KEY_BY_STATUS = {v: k for k, v in STATUS_BY_KEY.items()}
LIST_TITLES = {"p": "🍿 Para assistir", "a": "✅ Ja assistidos"}


def fetch_rows(chat_id: int, status_key: str) -> list:
    status = STATUS_BY_KEY[status_key]
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND status = ? ORDER BY id",
        (chat_id, status),
    ).fetchall()
    conn.close()
    return rows


def rows_in_platform(rows: list, platform: str) -> list:
    return [r for r in rows if platform_of(r) == platform]


def rows_in_category(rows: list, category: str) -> list:
    return [r for r in rows if category_of(r) == category]


def rows_in_genre(rows: list, genre: str) -> list:
    return [r for r in rows if genre in genres_of(r)]


class NavError(Exception):
    pass


def resolve_platform(rows: list, pidx: int):
    platforms = unique_sorted(platform_of(r) for r in rows)
    if pidx < 0 or pidx >= len(platforms):
        raise NavError()
    platform = platforms[pidx]
    return platform, rows_in_platform(rows, platform)


def resolve_category(rows: list, cidx: int):
    categories = unique_sorted(category_of(r) for r in rows)
    if cidx < 0 or cidx >= len(categories):
        raise NavError()
    category = categories[cidx]
    return category, rows_in_category(rows, category)


def resolve_genre(rows: list, gidx: int):
    genres = set()
    for r in rows:
        genres.update(genres_of(r))
    genres = unique_sorted(genres)
    if gidx < 0 or gidx >= len(genres):
        raise NavError()
    genre = genres[gidx]
    return genre, rows_in_genre(rows, genre)


def kb_platforms(status_key: str, rows: list) -> InlineKeyboardMarkup:
    platforms = unique_sorted(platform_of(r) for r in rows)
    buttons = [
        [InlineKeyboardButton(f"📺 {p}", callback_data=f"lc|{status_key}|{i}")]
        for i, p in enumerate(platforms)
    ]
    return InlineKeyboardMarkup(buttons)


def kb_categories(status_key: str, pidx: int, rows: list) -> InlineKeyboardMarkup:
    categories = unique_sorted(category_of(r) for r in rows)
    buttons = [
        [
            InlineKeyboardButton(
                f"{MEDIA_TYPE_ICON.get(c, '🎞')} {c}", callback_data=f"lg|{status_key}|{pidx}|{i}"
            )
        ]
        for i, c in enumerate(categories)
    ]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"lp|{status_key}")])
    return InlineKeyboardMarkup(buttons)


def kb_genres(status_key: str, pidx: int, cidx: int, rows: list) -> InlineKeyboardMarkup:
    genres = set()
    for r in rows:
        genres.update(genres_of(r))
    genres = unique_sorted(genres)
    buttons = [
        [InlineKeyboardButton(f"🏷 {g}", callback_data=f"li|{status_key}|{pidx}|{cidx}|{i}")]
        for i, g in enumerate(genres)
    ]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"lc|{status_key}|{pidx}")])
    return InlineKeyboardMarkup(buttons)


def kb_items(status_key: str, pidx: int, cidx: int, gidx: int, rows: list) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                item_button_label(r), callback_data=f"v|{r['id']}|{status_key}|{pidx}|{cidx}|{gidx}"
            )
        ]
        for r in rows
    ]
    buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"lg|{status_key}|{pidx}|{cidx}")])
    return InlineKeyboardMarkup(buttons)


def build_detail_view(row: sqlite3.Row, path: tuple):
    status_key, pidx, cidx, gidx = path
    date_str = row["created_at"][:10] if row["created_at"] else "?"
    status_label = "Assistido ✅" if row["status"] == "assistido" else "Para assistir 🍿"

    lines = [f"🎬 <b>{html.escape(row['title'])}</b> (#{row['id']})"]
    tags = [t for t in [category_of(row), row["genre"]] if t]
    if tags:
        lines.append("🏷 " + html.escape(" · ".join(tags)))
    if row["rating"] and row["rating"].lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"⭐ Nota: {html.escape(row['rating'])}")
    lines.append(f"Status: {status_label}")
    lines.append(f"Adicionado em: {date_str}")
    if row["synopsis"]:
        lines.append(f"\n📖 {html.escape(row['synopsis'])}")
    if row["where_to_watch"] and row["where_to_watch"].lower() not in ("nao encontrado", "não encontrado"):
        lines.append(f"\n📺 <b>Onde assistir:</b> {html.escape(row['where_to_watch'])}")
    text = "\n".join(lines)

    suffix = f"{row['id']}|{status_key}|{pidx}|{cidx}|{gidx}"
    toggle_button = (
        InlineKeyboardButton("↩️ Desmarcar", callback_data=f"u|{suffix}")
        if row["status"] == "assistido"
        else InlineKeyboardButton("✅ Marcar como assistido", callback_data=f"m|{suffix}")
    )
    keyboard = InlineKeyboardMarkup(
        [
            [toggle_button],
            [InlineKeyboardButton("🗑 Remover", callback_data=f"x|{suffix}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"li|{status_key}|{pidx}|{cidx}|{gidx}")],
        ]
    )
    return text, keyboard


async def send_list(update: Update, chat_id: int, status_key: str) -> None:
    rows = fetch_rows(chat_id, status_key)
    title = LIST_TITLES[status_key]
    if not rows:
        await update.message.reply_html(f"{title}\n\n<i>Vazio por aqui.</i>")
        return
    await update.message.reply_html(
        f"{title}\n\nEscolha a plataforma:",
        reply_markup=kb_platforms(status_key, rows),
    )


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_list(update, update.effective_chat.id, "p")


async def assistidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_list(update, update.effective_chat.id, "a")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat.id
    parts = query.data.split("|")
    action = parts[0]

    try:
        if action == "lp":
            status_key = parts[1]
            rows = fetch_rows(chat_id, status_key)
            await query.answer()
            if not rows:
                await query.edit_message_text(f"{LIST_TITLES[status_key]}\n\nVazio por aqui.")
                return
            await query.edit_message_text(
                f"{LIST_TITLES[status_key]}\n\nEscolha a plataforma:",
                reply_markup=kb_platforms(status_key, rows),
            )
            return

        if action == "lc":
            status_key, pidx = parts[1], int(parts[2])
            rows = fetch_rows(chat_id, status_key)
            platform, prows = resolve_platform(rows, pidx)
            await query.answer()
            await query.edit_message_text(
                f"📺 <b>{html.escape(platform)}</b>\n\nEscolha a categoria:",
                parse_mode="HTML",
                reply_markup=kb_categories(status_key, pidx, prows),
            )
            return

        if action == "lg":
            status_key, pidx, cidx = parts[1], int(parts[2]), int(parts[3])
            rows = fetch_rows(chat_id, status_key)
            platform, prows = resolve_platform(rows, pidx)
            category, crows = resolve_category(prows, cidx)
            await query.answer()
            await query.edit_message_text(
                f"📺 {html.escape(platform)} · {MEDIA_TYPE_ICON.get(category, '')} "
                f"<b>{html.escape(category)}</b>\n\nEscolha o genero:",
                parse_mode="HTML",
                reply_markup=kb_genres(status_key, pidx, cidx, crows),
            )
            return

        if action == "li":
            status_key, pidx, cidx, gidx = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
            rows = fetch_rows(chat_id, status_key)
            platform, prows = resolve_platform(rows, pidx)
            category, crows = resolve_category(prows, cidx)
            genre, grows = resolve_genre(crows, gidx)
            await query.answer()
            await query.edit_message_text(
                f"📺 {html.escape(platform)} · {html.escape(category)} · "
                f"🏷 <b>{html.escape(genre)}</b>\n\nToque num titulo:",
                parse_mode="HTML",
                reply_markup=kb_items(status_key, pidx, cidx, gidx, grows),
            )
            return

        if action == "v":
            item_id = int(parts[1])
            status_key, pidx, cidx, gidx = parts[2], int(parts[3]), int(parts[4]), int(parts[5])
            conn = get_conn()
            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
            ).fetchone()
            conn.close()
            await query.answer()
            if not row:
                await query.edit_message_text("Nao achei esse item (pode ter sido removido).")
                return
            text, keyboard = build_detail_view(row, (status_key, pidx, cidx, gidx))
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        if action in ("m", "u", "x"):
            item_id = int(parts[1])
            status_key, pidx, cidx, gidx = parts[2], int(parts[3]), int(parts[4]), int(parts[5])

            conn = get_conn()
            if action == "m":
                conn.execute(
                    "UPDATE items SET status = 'assistido' WHERE id = ? AND chat_id = ?",
                    (item_id, chat_id),
                )
                conn.commit()
                await query.answer("Marcado como assistido ✅")
            elif action == "u":
                conn.execute(
                    "UPDATE items SET status = 'para assistir' WHERE id = ? AND chat_id = ?",
                    (item_id, chat_id),
                )
                conn.commit()
                await query.answer("Voltou pra lista de assistir 🍿")
            else:
                conn.execute(
                    "DELETE FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
                )
                conn.commit()
                conn.close()
                await query.answer("Removido 🗑")
                await query.edit_message_text("🗑 Item removido da lista.")
                return

            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
            ).fetchone()
            conn.close()
            text, keyboard = build_detail_view(row, (status_key, pidx, cidx, gidx))
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
            return

        await query.answer()
    except NavError:
        await query.answer()
        await query.edit_message_text(
            "Essa lista mudou desde que voce abriu. Manda /lista ou /assistidos de novo."
        )


async def detalhes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /detalhes <id>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID invalido.")
        return

    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
    ).fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Nao achei esse ID na sua lista.")
        return

    status_key = KEY_BY_STATUS.get(row["status"], "p")
    rows = fetch_rows(chat_id, status_key)
    platform = platform_of(row)
    category = category_of(row)
    platforms = unique_sorted(platform_of(r) for r in rows)
    pidx = platforms.index(platform) if platform in platforms else 0
    prows = rows_in_platform(rows, platform)
    categories = unique_sorted(category_of(r) for r in prows)
    cidx = categories.index(category) if category in categories else 0
    crows = rows_in_category(prows, category)
    row_genres = genres_of(row)
    genres = sorted(set().union(*[genres_of(r) for r in crows]), key=lambda s: s.lower())
    genre = row_genres[0] if row_genres else UNKNOWN_GENRE
    gidx = genres.index(genre) if genre in genres else 0

    text, keyboard = build_detail_view(row, (status_key, pidx, cidx, gidx))
    await update.message.reply_html(text, reply_markup=keyboard)


async def marcar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_status(update, context, "assistido", "Marcado como assistido ✅")


async def desmarcar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await set_status(update, context, "para assistir", "Voltou pra lista de assistir 🍿")


async def set_status(update, context, status, ok_msg):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /marcar <id>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID invalido.")
        return

    conn = get_conn()
    cur = conn.execute(
        "UPDATE items SET status = ? WHERE id = ? AND chat_id = ?",
        (status, item_id, chat_id),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed:
        await update.message.reply_text(f"{ok_msg}: #{item_id}")
    else:
        await update.message.reply_text("Nao achei esse ID na sua lista.")


async def renomear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /renomear <id> <novo nome>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID invalido.")
        return
    new_title = " ".join(context.args[1:])

    conn = get_conn()
    cur = conn.execute(
        "UPDATE items SET title = ? WHERE id = ? AND chat_id = ?",
        (new_title, item_id, chat_id),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed:
        await update.message.reply_text(f"Renomeado #{item_id} para: {new_title}")
    else:
        await update.message.reply_text("Nao achei esse ID na sua lista.")


async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /remover <id>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID invalido.")
        return

    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed:
        await update.message.reply_text(f"Removido #{item_id}")
    else:
        await update.message.reply_text("Nao achei esse ID na sua lista.")


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Defina a variavel de ambiente TELEGRAM_BOT_TOKEN")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("assistidos", assistidos))
    app.add_handler(CommandHandler("detalhes", detalhes))
    app.add_handler(CommandHandler("marcar", marcar))
    app.add_handler(CommandHandler("desmarcar", desmarcar))
    app.add_handler(CommandHandler("renomear", renomear))
    app.add_handler(CommandHandler("remover", remover))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot iniciado, aguardando mensagens...")
    app.run_polling()


if __name__ == "__main__":
    main()
