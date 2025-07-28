import os
import re
import tempfile
import requests
import feedparser
import aiosmtplib
from email.message import EmailMessage
from email.utils import formataddr
from newspaper import Article
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from ebooklib import epub
from bs4 import BeautifulSoup
from PIL import Image
from email_validator import validate_email, EmailNotValidError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
import io
import subprocess

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")
CHAT_ID = os.getenv("CHAT_ID")

if CHAT_ID is None:
    raise ValueError("CHAT_ID no está definido en las variables de entorno (.env)")

try:
    CHAT_ID = int(CHAT_ID)
except ValueError:
    raise ValueError("CHAT_ID debe ser un número entero válido")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

RSS_FEED = "https://www.milenio.com/rss/mexico.xml"
PALABRAS_CLAVE = [
    "México",
    "CDMX",
    "Cancún",
    "Guadalajara",
    "Monterrey",
    "Jalisco",
    "Nuevo León",
    "Puebla",
    "Chiapas",
    "Veracruz",
]

HISTORIAL_FILE = "urls_procesadas.json"

def cargar_historial():
    if os.path.exists(HISTORIAL_FILE):
        with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def guardar_historial(urls):
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(list(urls), f, ensure_ascii=False, indent=2)

def optimizar_imagen(imagen_bytes):
    with Image.open(io.BytesIO(imagen_bytes)) as im:
        im = im.convert("RGB")
        im.thumbnail((1200, 1200))
        salida = io.BytesIO()
        im.save(salida, format="JPEG", quality=85)
        return salida.getvalue()

def crear_epub_con_noticias(urls, archivo_salida):
    libro = epub.EpubBook()
    libro.set_identifier("noticias-diarias")
    fecha = datetime.now().strftime("%Y-%m-%d")
    libro.set_title(f"Noticias de México - {fecha}")
    libro.set_language("es")
    libro.add_author("Agregador de noticias")

    capítulos = []

    for i, url in enumerate(urls):
        try:
            article = Article(url)
            article.download()
            article.parse()

            titulo = article.title or f"Noticia {i+1}"
            texto = article.text or ""
            imagenes = list(article.images)[:1]

            html = f"<h2>{titulo}</h2>"

            for idx, img_url in enumerate(imagenes):
                try:
                    img_data_raw = requests.get(img_url, timeout=5).content
                    img_data = optimizar_imagen(img_data_raw)

                    img_filename = f"noticia{i}_img{idx}.jpg"
                    img_item = epub.EpubItem(
                        uid=img_filename,
                        file_name=f"images/{img_filename}",
                        media_type="image/jpeg",
                        content=img_data,
                    )
                    libro.add_item(img_item)
                    html += f'<div><img src="{img_item.file_name}" style="max-width:100%; margin-bottom:20px;"></div>'
                except Exception as e:
                    print(f"Error con imagen: {e}")

            html += "<div style='font-family:Arial; font-size:1em; line-height:1.6;'>" + texto.replace("\n", "<br>") + "</div>"

            soup = BeautifulSoup(html, "html.parser")
            capitulo = epub.EpubHtml(title=titulo, file_name=f"capitulo{i}.xhtml", lang="es")
            capitulo.set_content(str(soup))
            libro.add_item(capitulo)
            capítulos.append(capitulo)

        except Exception as e:
            print(f"Error procesando noticia {url}: {e}")

    libro.toc = tuple(capítulos)
    libro.spine = ["nav"] + capítulos
    libro.add_item(epub.EpubNcx())
    libro.add_item(epub.EpubNav())

    estilo = """
    body { font-family: Georgia, serif; margin: 2em; color: #333; }
    h2 { color: #0055a5; }
    img { margin: 1em 0; }
    """
    estilo_item = epub.EpubItem(
        uid="style_nav", file_name="style/style.css", media_type="text/css", content=estilo
    )
    libro.add_item(estilo_item)
    for cap in capítulos:
        cap.add_item(estilo_item)

    epub.write_epub(archivo_salida, libro)

async def enviar_email_kindle(file_path, subject, recipient):
    print(f"[LOG] Starting to send email to {recipient} with file {file_path}")
    message = EmailMessage()
    message["From"] = formataddr(("Tu Bot", EMAIL_SENDER))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Adjunto archivo para tu Kindle.")

    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)
            print(f"[LOG] Attaching file: {file_name} ({len(file_data)} bytes)")
            message.add_attachment(
                file_data, maintype="application", subtype="epub+zip", filename=file_name
            )
    except Exception as e:
        print(f"[ERROR] Could not open or attach the file: {e}")
        return False

    try:
        print(f"[LOG] Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT} as {EMAIL_SENDER}")
        response = await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_SENDER,
            password=EMAIL_PASSWORD,
        )
        print(f"[LOG] Email sent successfully. SMTP Response: {response}")
        return True
    except Exception as e:
        print(f"[ERROR] Error sending email: {e}")
        return False
        return False

async def tarea_diaria(application):
    print("Ejecutando tarea diaria para generar noticias...")

    historial = cargar_historial()

    feed = feedparser.parse(RSS_FEED)
    urls_nuevas = []
    for entry in feed.entries:
        titulo = entry.title
        link = entry.link
        if any(palabra.lower() in titulo.lower() for palabra in PALABRAS_CLAVE):
            if link not in historial:
                urls_nuevas.append(link)

    if not urls_nuevas:
        print("No hay noticias nuevas que procesar.")
        return

    urls_nuevas = urls_nuevas[:10]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp_epub:
        tmp_epub.close()
        crear_epub_con_noticias(urls_nuevas, tmp_epub.name)

        try:
            await application.bot.send_document(
                chat_id=CHAT_ID,
                document=open(tmp_epub.name, "rb"),
                filename=f"noticias_mexico_{datetime.now().strftime('%Y%m%d')}.epub",
            )
        except Exception as e:
            print(f"Error enviando EPUB a Telegram: {e}")

        try:
            exito = await enviar_email_kindle(tmp_epub.name, "Noticias México", KINDLE_EMAIL)
            if exito:
                print("EPUB enviado a Kindle con éxito.")
            else:
                print("Error al enviar EPUB a Kindle.")
        except Exception as e:
            print(f"Error enviando email a Kindle: {e}")

        os.unlink(tmp_epub.name)

    historial.update(urls_nuevas)
    guardar_historial(historial)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi 👋 this bot generates a daily EPUB with news from Mexico.\n"
        "You can set your Kindle email with /sendtokindle your_email@kindle.com\n"
        "And receive news manually with /generate\n"
        "To update the bot from GitHub use /update"
    )

async def send_to_kindle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Please use: /sendtokindle your_kindle_email")
        return

    email = context.args[0]
    try:
        validate_email(email)
        context.user_data["kindle_email"] = email
        global KINDLE_EMAIL
        KINDLE_EMAIL = email
        await update.message.reply_text(f"Kindle email set to: {email}")
    except EmailNotValidError:
        await update.message.reply_text("Invalid email, please try again.")

async def generar_noticias_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generating news now...")
    await tarea_diaria(context.application)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the general status of the bot."""
    status_lines = []
    status_lines.append("🤖 General bot status:")
    # Environment variables and config
    status_lines.append(f"- EMAIL_SENDER: {EMAIL_SENDER if EMAIL_SENDER else 'Not set'}")
    status_lines.append(f"- KINDLE_EMAIL: {KINDLE_EMAIL if KINDLE_EMAIL else 'Not set'}")
    status_lines.append(f"- CHAT_ID: {CHAT_ID}")
    status_lines.append(f"- SMTP_SERVER: {SMTP_SERVER}:{SMTP_PORT}")
    status_lines.append(f"- RSS_FEED: {RSS_FEED}")
    # File status
    epub_exists = os.path.exists('noticias.epub')
    status_lines.append(f"- noticias.epub file: {'Exists' if epub_exists else 'Does not exist'}")
    historial_exists = os.path.exists(HISTORIAL_FILE)
    status_lines.append(f"- History file: {'Exists' if historial_exists else 'Does not exist'}")
    # Last modification
    if epub_exists:
        mtime = datetime.fromtimestamp(os.path.getmtime('noticias.epub')).strftime('%Y-%m-%d %H:%M:%S')
        status_lines.append(f"- Last EPUB generation: {mtime}")
    if historial_exists:
        mtime = datetime.fromtimestamp(os.path.getmtime(HISTORIAL_FILE)).strftime('%Y-%m-%d %H:%M:%S')
        status_lines.append(f"- Last history update: {mtime}")
    # Final message
    await update.message.reply_text("\n".join(status_lines))

async def update_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Updating code from GitHub...")
    try:
        result = subprocess.run(
            ["git", "pull"], cwd=os.getcwd(), capture_output=True, text=True
        )
        salida = result.stdout + "\n" + result.stderr
        await update.message.reply_text(f"Result of git pull:\n{salida}")

        result_restart = subprocess.run(
            ["sudo", "systemctl", "restart", "telegrambot"],
            capture_output=True,
            text=True,
        )
        salida_restart = result_restart.stdout + "\n" + result_restart.stderr
        await update.message.reply_text(f"Service restarted.\n{salida_restart}")

    except Exception as e:
        await update.message.reply_text(f"Error updating: {e}")

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[DEBUG] Update received: {update}")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sendtokindle", send_to_kindle))
    app.add_handler(CommandHandler("generate", generar_noticias_manual))
    app.add_handler(CommandHandler("update", update_bot))
    app.add_handler(CommandHandler("status", status))
    # Global debug handler
    app.add_handler(MessageHandler(filters.ALL, log_all_updates))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(tarea_diaria, "cron", hour=7, minute=0, args=[app])
    scheduler.start()

    await app.initialize()
    print("About to start polling...")
    await app.start()
    print("Polling started!")
    print("Bot corriendo con scheduler para tarea diaria a las 7:00 am...")
    try:
        await asyncio.Event().wait()  # Mantener el bot vivo
    finally:
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
