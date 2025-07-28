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
    MessageHandler,
    filters,
    ContextTypes,
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


def limpiar_nombre_archivo(nombre):
    nombre = re.sub(r'[\\/*?:"<>|]', "", nombre)
    nombre = nombre.strip()
    if len(nombre) > 100:
        nombre = nombre[:100]
    return nombre


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
    message = EmailMessage()
    message["From"] = formataddr(("Tu Bot", EMAIL_SENDER))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Adjunto archivo para tu Kindle.")

    with open(file_path, "rb") as f:
        file_data = f.read()
        file_name = os.path.basename(file_path)
        message.add_attachment(
            file_data, maintype="application", subtype="epub+zip", filename=file_name
        )

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_SENDER,
            password=EMAIL_PASSWORD,
        )
        return True
    except Exception as e:
        print(f"Error enviando email: {e}")
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
        "Hola 👋 este bot genera diariamente un EPUB con noticias de México.\n"
        "Puedes configurar tu email Kindle con /sendtokindle tu_email@kindle.com\n"
        "Y recibir noticias manualmente con /generar\n"
        "Para actualizar el bot desde GitHub usa /update"
    )


async def send_to_kindle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Por favor usa: /sendtokindle tu_email_kindle")
        return

    email = context.args[0]
    try:
        validate_email(email)
        context.user_data["kindle_email"] = email
        global KINDLE_EMAIL
        KINDLE_EMAIL = email
        await update.message.reply_text(f"Email Kindle configurado a: {email}")
    except EmailNotValidError:
        await update.message.reply_text("Email inválido, intenta de nuevo.")


async def generar_noticias_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generando noticias ahora...")
    await tarea_diaria(context.application)


async def update_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Actualizando código desde GitHub...")
    try:
        result = subprocess.run(
            ["git", "pull"], cwd=os.getcwd(), capture_output=True, text=True
        )
        salida = result.stdout + "\n" + result.stderr
        await update.message.reply_text(f"Resultado de git pull:\n{salida}")

        result_restart = subprocess.run(
            ["sudo", "systemctl", "restart", "telegrambot"],
            capture_output=True,
            text=True,
        )
        salida_restart = result_restart.stdout + "\n" + result_restart.stderr
        await update.message.reply_text(f"Servicio reiniciado.\n{salida_restart}")

    except Exception as e:
        await update.message.reply_text(f"Error al actualizar: {e}")


async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sendtokindle", send_to_kindle))
    app.add_handler(CommandHandler("generar", generar_noticias_manual))
    app.add_handler(CommandHandler("update", update_bot))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(tarea_diaria, "cron", hour=7, minute=0, args=[app])
    scheduler.start()

    print("Bot corriendo con scheduler para tarea diaria a las 7:00 am...")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
