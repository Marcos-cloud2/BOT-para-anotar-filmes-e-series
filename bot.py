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
from telegram import Update
from telegram.ext import (
    Application,
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

ANALYSIS_PROMPT = (
    "Esta imagem e um print de rede social (Instagram, TikTok, etc) divulgando "
    "um filme ou serie.\n"
    "Use a busca do Google para confirmar informacoes atuais quando precisar.\n\n"
    "Responda EXATAMENTE nesse formato, com cada campo em uma linha, sem markdown "
    "e sem texto extra antes ou depois:\n"
    "TITULO: <titulo oficial do filme ou serie>\n"
    "SINOPSE: <resumo em portugues, no maximo 3 frases curtas>\n"
    "ONDE_ASSISTIR: <plataformas de streaming legais disponiveis no Brasil, "
    "separadas por virgula; se nao souber, escreva 'Nao encontrado'>\n\n"
    "Se a imagem nao mostrar nenhum filme ou serie identificavel, responda "
    "exatamente:\nTITULO: DESCONHECIDO"
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
            synopsis TEXT,
            where_to_watch TEXT,
            raw_text TEXT,
            status TEXT NOT NULL DEFAULT 'para assistir',
            created_at TEXT NOT NULL
        )
        """
    )
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    if "synopsis" not in existing_cols:
        conn.execute("ALTER TABLE items ADD COLUMN synopsis TEXT")
    if "where_to_watch" not in existing_cols:
        conn.execute("ALTER TABLE items ADD COLUMN where_to_watch TEXT")
    conn.commit()
    conn.close()


HELP_TEXT = (
    "🎬 <b>Bot de Filmes e Series</b>\n\n"
    "Me manda um print divulgando um filme/serie que eu identifico, busco a "
    "sinopse e onde assistir, e anoto na sua lista.\n\n"
    "<b>Comandos</b>\n"
    "/lista - o que falta assistir\n"
    "/assistidos - o que ja foi assistido\n"
    "/detalhes &lt;id&gt; - ver sinopse, onde assistir e data\n"
    "/marcar &lt;id&gt; - marcar como assistido\n"
    "/desmarcar &lt;id&gt; - voltar pra lista\n"
    "/renomear &lt;id&gt; &lt;nome certo&gt; - corrigir o titulo\n"
    "/remover &lt;id&gt; - apagar da lista"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


def parse_analysis(text: str) -> dict:
    result = {"title": "", "synopsis": "", "where_to_watch": ""}
    patterns = {
        "title": re.compile(r"^TITULO\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
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


async def analyze_image(buf: BytesIO) -> dict:
    image = Image.open(buf)
    image = image.convert("RGB")
    out = BytesIO()
    image.save(out, format="JPEG")
    image_bytes = out.getvalue()

    config = genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
    )
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            ANALYSIS_PROMPT,
            genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        ],
        config=config,
    )
    return parse_analysis((response.text or "").strip())


def format_new_item_message(item_id: int, title: str, synopsis: str, where: str) -> str:
    lines = [f"✅ <b>Anotado</b> #{item_id}: <b>{html.escape(title)}</b>"]
    if synopsis:
        lines.append(f"\n📖 {html.escape(synopsis)}")
    if where and where.lower() != "nao encontrado":
        lines.append(f"\n📺 <b>Onde assistir:</b> {html.escape(where)}")
    lines.append(
        f"\n<i>Titulo errado? Corrija com</i> /renomear {item_id} Nome Certo"
    )
    return "\n".join(lines)


async def save_item(
    update: Update,
    chat_id: int,
    title: str,
    synopsis: str = "",
    where_to_watch: str = "",
    raw_text: str = None,
) -> None:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO items (chat_id, title, synopsis, where_to_watch, raw_text, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            chat_id,
            title[:200],
            synopsis[:1000] if synopsis else None,
            where_to_watch[:300] if where_to_watch else None,
            raw_text,
            "para assistir",
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()

    await update.message.reply_html(
        format_new_item_message(item_id, title, synopsis, where_to_watch)
    )


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
            "Nao consegui identificar nenhum filme ou serie nessa imagem. "
            "Me manda o nome direto por texto?"
        )
        return

    await save_item(
        update,
        chat_id,
        title,
        synopsis=data.get("synopsis", ""),
        where_to_watch=data.get("where_to_watch", ""),
    )


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


async def lookup_by_title(title: str) -> dict:
    prompt = (
        f"O usuario quer anotar o filme ou serie chamado '{title}'.\n"
        "Use a busca do Google se precisar confirmar informacoes atuais.\n\n"
        "Responda EXATAMENTE nesse formato, sem markdown e sem texto extra:\n"
        "TITULO: <titulo oficial>\n"
        "SINOPSE: <resumo em portugues, no maximo 3 frases curtas>\n"
        "ONDE_ASSISTIR: <plataformas de streaming legais disponiveis no Brasil, "
        "separadas por virgula; se nao souber, escreva 'Nao encontrado'>"
    )
    config = genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
    )
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=[prompt], config=config
    )
    return parse_analysis((response.text or "").strip())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    title = update.message.text.strip()
    if not title:
        return

    synopsis, where_to_watch = "", ""
    if gemini_client:
        await update.message.chat.send_action("typing")
        try:
            data = await lookup_by_title(title)
            if data.get("title"):
                title = data["title"]
            synopsis = data.get("synopsis", "")
            where_to_watch = data.get("where_to_watch", "")
        except Exception:
            logger.exception("Erro ao buscar informacoes do titulo")

    await save_item(update, chat_id, title, synopsis, where_to_watch)


def format_list(rows) -> str:
    if not rows:
        return "<i>Vazio por aqui.</i>"
    lines = []
    for r in rows:
        date_str = r["created_at"][:10] if r["created_at"] else "?"
        lines.append(f"#{r['id']} - <b>{html.escape(r['title'])}</b> (adicionado {date_str})")
    return "\n".join(lines)


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, created_at FROM items WHERE chat_id = ? AND status = 'para assistir' ORDER BY id",
        (chat_id,),
    ).fetchall()
    conn.close()
    await update.message.reply_html("🍿 <b>Para assistir</b>\n\n" + format_list(rows))


async def assistidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, created_at FROM items WHERE chat_id = ? AND status = 'assistido' ORDER BY id",
        (chat_id,),
    ).fetchall()
    conn.close()
    await update.message.reply_html("✅ <b>Ja assistidos</b>\n\n" + format_list(rows))


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

    date_str = row["created_at"][:10] if row["created_at"] else "?"
    status_label = "Assistido ✅" if row["status"] == "assistido" else "Para assistir 🍿"
    lines = [
        f"🎬 <b>{html.escape(row['title'])}</b> (#{row['id']})",
        f"Status: {status_label}",
        f"Adicionado em: {date_str}",
    ]
    if row["synopsis"]:
        lines.append(f"\n📖 {html.escape(row['synopsis'])}")
    if row["where_to_watch"]:
        lines.append(f"\n📺 <b>Onde assistir:</b> {html.escape(row['where_to_watch'])}")

    await update.message.reply_html("\n".join(lines))


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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot iniciado, aguardando mensagens...")
    app.run_polling()


if __name__ == "__main__":
    main()
