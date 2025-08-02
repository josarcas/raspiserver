import os
import json
import tempfile
import requests
import feedparser
from newspaper import Article
from ebooklib import epub
from bs4 import BeautifulSoup
from PIL import Image
from email.message import EmailMessage
from email.utils import formataddr
from email_validator import validate_email, EmailNotValidError
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
)
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
import subprocess
import io
from datetime import datetime

# --- Configuración y utilidades ---
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_USER_ID")
EMAIL_ENCRYPTION_KEY = os.getenv("EMAIL_ENCRYPTION_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

EMAILS_FILE = "emails.enc"
NEWS_SOURCES_FILE = "news_sources.json"
SENT_NEWS_FILE = "sent_news.json"

if not all([TELEGRAM_TOKEN, CHAT_ID, EMAIL_ENCRYPTION_KEY, EMAIL_SENDER, EMAIL_PASSWORD]):
    raise Exception("Faltan variables de entorno requeridas en .env")

fernet = Fernet(EMAIL_ENCRYPTION_KEY.encode())

# --- Emails cifrados ---
import asyncio

def guardar_emails(emails):
    debug_msg = f"[DEBUG guardar_emails] emails = {emails} {type(emails)}"
    print(debug_msg)
    # Enviar debug por Telegram si es posible
    try:
        from telegram import Bot
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_USER_ID")
        if token and chat_id:
            bot = Bot(token=token)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(bot.send_message(chat_id=int(chat_id), text=debug_msg))
            else:
                loop.run_until_complete(bot.send_message(chat_id=int(chat_id), text=debug_msg))
    except Exception as e:
        print(f"[DEBUG guardar_emails] Error enviando debug por Telegram: {e}")
    # Validar que solo se acepten listas de strings
    if not isinstance(emails, list):
        print("[ERROR] Emails debe ser una lista de strings. Limpiando emails.enc...")
        if os.path.exists(EMAILS_FILE):
            os.remove(EMAILS_FILE)
        emails = []
    else:
        for e in emails:
            if not isinstance(e, str):
                print("[ERROR] Cada email debe ser un string. Limpiando emails.enc...")
                if os.path.exists(EMAILS_FILE):
                    os.remove(EMAILS_FILE)
                emails = []
                break
    data = json.dumps(emails).encode()
    encrypted = fernet.encrypt(data)
    with open(EMAILS_FILE, "wb") as f:
        f.write(encrypted)

def cargar_emails():
    if not os.path.exists(EMAILS_FILE):
        return []
    with open(EMAILS_FILE, "rb") as f:
        encrypted = f.read()
    try:
        data = fernet.decrypt(encrypted)
        return json.loads(data.decode())
    except Exception as e:
        print(f"[ERROR] Descifrando emails: {e}")
        return []

def guardar_fuentes(fuentes):
    debug_msg = f"[DEBUG guardar_fuentes] fuentes = {fuentes} {type(fuentes)}"
    print(debug_msg)
    try:
        from telegram import Bot
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_USER_ID")
        if token and chat_id:
            bot = Bot(token=token)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(bot.send_message(chat_id=int(chat_id), text=debug_msg))
            else:
                loop.run_until_complete(bot.send_message(chat_id=int(chat_id), text=debug_msg))
    except Exception as e:
        print(f"[DEBUG guardar_fuentes] Error enviando debug por Telegram: {e}")
    # Permitir guardar como dict o lista
    with open(NEWS_SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(fuentes, f, ensure_ascii=False, indent=2)

def cargar_fuentes():
    if not os.path.exists(NEWS_SOURCES_FILE):
        return {}
    with open(NEWS_SOURCES_FILE, "r", encoding="utf-8") as f:
        try:
            fuentes = json.load(f)
            if isinstance(fuentes, list):
                # Convertir lista a dict
                fuentes = {f"Source {i+1}": url for i, url in enumerate(fuentes)}
            return fuentes
        except Exception as e:
            print(f"[ERROR] Cargando fuentes: {e}")
            return {}

def guardar_enviadas(enviadas):
    debug_msg = f"[DEBUG guardar_enviadas] enviadas = {enviadas} {type(enviadas)}"
    print(debug_msg)
    try:
        from telegram import Bot
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_USER_ID")
        if token and chat_id:
            bot = Bot(token=token)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(bot.send_message(chat_id=int(chat_id), text=debug_msg))
            else:
                loop.run_until_complete(bot.send_message(chat_id=int(chat_id), text=debug_msg))
    except Exception as e:
        print(f"[DEBUG guardar_enviadas] Error enviando debug por Telegram: {e}")
    # Siempre guardar como lista
    with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(enviadas), f, ensure_ascii=False, indent=2)

def cargar_enviadas():
    if not os.path.exists(SENT_NEWS_FILE):
        return set()
    with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return set(data)
        except Exception as e:
            print(f"[ERROR] Cargando enviadas: {e}")
            return set()

    data = json.dumps(emails).encode()
    encrypted = fernet.encrypt(data)
    with open(EMAILS_FILE, "wb") as f:
        f.write(encrypted)

def cargar_emails():
    if not os.path.exists(EMAILS_FILE):
        return []
    with open(EMAILS_FILE, "rb") as f:
        encrypted = f.read()
        try:
            data = fernet.decrypt(encrypted)
            return json.loads(data.decode())
        except Exception as e:
            print(f"[ERROR] Error al descifrar emails: {e}")
            return []

# --- Fuentes de noticias ---
def cargar_fuentes():
    if not os.path.exists(NEWS_SOURCES_FILE):
        return []
    with open(NEWS_SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_fuentes(fuentes):
    with open(NEWS_SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(fuentes, f, ensure_ascii=False, indent=2)

# --- Noticias enviadas ---
def cargar_enviadas():
    if not os.path.exists(SENT_NEWS_FILE):
        return set()
    with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def guardar_enviadas(news):
    with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(news), f, ensure_ascii=False, indent=2)

# --- Utilidades EPUB e imágenes ---
def optimizar_imagen(imagen_bytes):
    with Image.open(io.BytesIO(imagen_bytes)) as im:
        im = im.convert("RGB")
        im.thumbnail((1200, 1200))
        salida = io.BytesIO()
        im.save(salida, format="JPEG", quality=85)
        return salida.getvalue()

def crear_epub_con_noticias(urls, archivo_salida):
    from PIL import ImageDraw, ImageFont
    libro = epub.EpubBook()
    fecha = datetime.now().strftime("%d/%m/%Y")
    titulo = f"RaspiNews México - {fecha}"
    libro.set_identifier("raspinews-diario")
    libro.set_title(titulo)
    libro.set_language("es")
    libro.add_author("RaspiNews")
    # Metadatos extra para asegurar título en carátula
    libro.add_metadata('DC', 'title', titulo)
    libro.add_metadata('DC', 'creator', "RaspiNews")
    libro.add_metadata('DC', 'language', "es")

    # --- Collage de portada ---
    portada_imgs = []
    for i, url in enumerate(urls[:4]):
        try:
            article = Article(url)
            article.download()
            article.parse()
            imagenes = list(article.images)
            if imagenes:
                img_data = requests.get(imagenes[0], timeout=5).content
                portada_imgs.append(Image.open(io.BytesIO(img_data)).convert("RGB"))
        except Exception:
            continue
    # Crear collage o fondo simple
    cover_size = (1200, 1800)
    cover = Image.new("RGB", cover_size, (230, 230, 230))
    if portada_imgs:
        # Redimensionar y pegar imágenes
        for idx, img in enumerate(portada_imgs):
            img = img.resize((cover_size[0]//2, cover_size[1]//2))
            x = (idx % 2) * (cover_size[0]//2)
            y = (idx // 2) * (cover_size[1]//2)
            cover.paste(img, (x, y))
    draw = ImageDraw.Draw(cover)
    try:
        font = ImageFont.truetype("arial.ttf", 60)
    except:
        font = ImageFont.load_default()
    draw.rectangle([(0, cover_size[1]-200), (cover_size[0], cover_size[1])], fill=(20, 20, 20, 220))
    draw.text((40, cover_size[1]-180), titulo, font=font, fill=(255,255,255))
    # Guardar portada en memoria
    portada_bytes = io.BytesIO()
    cover.save(portada_bytes, format="JPEG")
    portada_bytes.seek(0)
    portada_item = epub.EpubItem(uid="cover", file_name="images/cover.jpg", media_type="image/jpeg", content=portada_bytes.read())
    libro.add_item(portada_item)
    libro.set_cover("cover.jpg", portada_item.content)

    capitulos = []
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
            capitulos.append(capitulo)
        except Exception as e:
            print(f"Error procesando noticia {url}: {e}")
    libro.toc = tuple(capitulos)
    libro.spine = ["nav"] + capitulos
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
    for cap in capitulos:
        cap.add_item(estilo_item)
    epub.write_epub(archivo_salida, libro)

# --- Email a Kindle ---
import aiosmtplib
async def enviar_email_kindle(file_path, subject, recipient):
    print(f"[LOG] Enviando email a {recipient} con archivo {file_path}")
    message = EmailMessage()
    message["From"] = formataddr(("NewsBot", EMAIL_SENDER))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Archivo generado para tu Kindle.")
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)
            message.add_attachment(
                file_data, maintype="application", subtype="epub+zip", filename=file_name
            )
    except Exception as e:
        print(f"[ERROR] No se pudo adjuntar archivo: {e}")
        return False
    try:
        response = await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_SENDER,
            password=EMAIL_PASSWORD,
        )
        print(f"[LOG] Email enviado. SMTP: {response}")
        return True
    except Exception as e:
        print(f"[ERROR] Error enviando email: {e}")
        return False

# --- Protección de comandos ---
def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != int(CHAT_ID):
            await update.message.reply_text("No autorizado.")
            return
        return await func(update, context)
    return wrapper

# --- Comandos Telegram ---
@only_owner
async def remove_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /removeemail correo@ejemplo.com")
        return
    email = context.args[0]
    emails = cargar_emails()
    if email not in emails:
        await update.message.reply_text("Ese correo no está registrado.")
        return
    emails = [e for e in emails if e != email]
    guardar_emails(emails)
    await update.message.reply_text(f"Correo {email} eliminado.")

@only_owner
async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /removesource NombreFuente")
        return
    name = context.args[0]
    fuentes = cargar_fuentes()
    fuentes_nuevas = [f for f in fuentes if f["name"].lower() != name.lower()]
    if len(fuentes_nuevas) == len(fuentes):
        await update.message.reply_text("No se encontró esa fuente.")
        return
    guardar_fuentes(fuentes_nuevas)
    await update.message.reply_text(f"Fuente '{name}' eliminada.")

@only_owner
async def add_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /addemail correo@ejemplo.com")
        return
    email = context.args[0]
    try:
        v = validate_email(email)
        email = v.email
    except EmailNotValidError as e:
        await update.message.reply_text(f"Correo inválido: {e}")
        return
    emails = cargar_emails()
    # Forzar que emails sea lista de strings
    if not isinstance(emails, list):
        print("[ERROR] emails no es lista, limpiando...")
        emails = []
    else:
        emails = [str(e) for e in emails]
    if email in emails:
        await update.message.reply_text("Ese correo ya está registrado.")
        return
    emails.append(email)
    guardar_emails(emails)
    await update.message.reply_text(f"Correo {email} registrado.")

@only_owner
async def list_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emails = cargar_emails()
    if not emails:
        await update.message.reply_text("No hay correos registrados.")
    else:
        await update.message.reply_text("Correos registrados:\n" + "\n".join(emails))

@only_owner
async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Uso: /addsource Nombre URL_RSS")
        return
    name, url = context.args
    fuentes = cargar_fuentes()
    if any(f["rss"] == url for f in fuentes):
        await update.message.reply_text("Esa fuente ya existe.")
        return
    fuentes.append({"name": name, "rss": url})
    guardar_fuentes(fuentes)
    await update.message.reply_text(f"Fuente {name} agregada.")

@only_owner
async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fuentes = cargar_fuentes()
    if not fuentes:
        await update.message.reply_text("No hay fuentes registradas.")
    else:
        msg = "Fuentes:\n" + "\n".join([f"{f['name']}: {f['rss']}" for f in fuentes])
        await update.message.reply_text(msg)

@only_owner
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Generando y enviando EPUB...")
    await tarea_diaria(context.application)
    await update.message.reply_text("¡Envío terminado!")

@only_owner
async def update_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Actualizando código desde GitHub...")
    try:
        result = subprocess.run(["git", "pull"], cwd=os.getcwd(), capture_output=True, text=True)
        salida = result.stdout + "\n" + result.stderr
        await update.message.reply_text(f"Resultado de git pull:\n{salida}")
        result_restart = subprocess.run(["sudo", "systemctl", "restart", "telegrambot"], capture_output=True, text=True)
        salida_restart = result_restart.stdout + "\n" + result_restart.stderr
        await update.message.reply_text(f"Servicio reiniciado.\n{salida_restart}")
    except Exception as e:
        await update.message.reply_text(f"Error actualizando: {e}")

@only_owner
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_lines = []
    status_lines.append("🤖 Estado general:")
    status_lines.append(f"- EMAIL_SENDER: {EMAIL_SENDER}")
    status_lines.append(f"- SMTP_SERVER: {SMTP_SERVER}:{SMTP_PORT}")
    status_lines.append(f"- Correos registrados: {len(cargar_emails())}")
    status_lines.append(f"- Fuentes: {len(cargar_fuentes())}")
    status_lines.append(f"- Noticias enviadas: {len(cargar_enviadas())}")
    await update.message.reply_text("\n".join(status_lines))

# --- Lógica de obtención y envío de noticias ---
async def tarea_diaria(application):
    print("[LOG] Ejecutando tarea diaria...")
    fuentes = cargar_fuentes()
    enviadas = cargar_enviadas()
    nuevas_urls = []
    for fuente in fuentes:
        try:
            feed = feedparser.parse(fuente["rss"])
            for entry in feed.entries:
                url = entry.link
                if url not in enviadas:
                    nuevas_urls.append(url)
        except Exception as e:
            print(f"[ERROR] Fuente {fuente['name']}: {e}")
    if not nuevas_urls:
        print("No hay noticias nuevas.")
        return
    nuevas_urls = nuevas_urls[:10]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp_epub:
        tmp_epub.close()
        crear_epub_con_noticias(nuevas_urls, tmp_epub.name)
        emails = cargar_emails()
        for email in emails:
            await enviar_email_kindle(tmp_epub.name, "Noticias Diarias", email)
        try:
            await application.bot.send_document(
                chat_id=int(CHAT_ID),
                document=open(tmp_epub.name, "rb"),
                filename=f"noticias_{datetime.now().strftime('%Y%m%d')}.epub",
            )
        except Exception as e:
            print(f"[ERROR] Enviando EPUB a Telegram: {e}")
        os.unlink(tmp_epub.name)
    enviadas.update(nuevas_urls)
    guardar_enviadas(enviadas)

BANWORDS_FILE = "banwords.json"

def cargar_banwords():
    if not os.path.exists(BANWORDS_FILE):
        return []
    with open(BANWORDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_banwords(banwords):
    with open(BANWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(banwords, f, ensure_ascii=False, indent=2)

def obtener_noticias_nuevas():
    # Carga fuentes y noticias enviadas
    fuentes = cargar_fuentes()
    enviadas = cargar_enviadas()
    nuevas_urls = []
    palabras_bloqueo = ["sociales", "espectáculos", "espectaculos", "farandula", "farándula", "show", "celebridad", "celebridades", "gente"]
    palabras_bloqueo += cargar_banwords()
    for fuente in fuentes:
        url = fuente["rss"]
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.link
            titulo = getattr(entry, 'title', '').lower()
            resumen = getattr(entry, 'summary', '').lower()
            url_lower = link.lower()
            if any(pal.lower() in titulo or pal.lower() in resumen or pal.lower() in url_lower for pal in palabras_bloqueo):
                continue
            if link not in enviadas and link not in nuevas_urls:
                nuevas_urls.append(link)
    return nuevas_urls

@only_owner
async def banword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /banword palabra_o_frase")
        return
    palabra = " ".join(context.args).strip().lower()
    banwords = cargar_banwords()
    if palabra in banwords:
        await update.message.reply_text(f"'{palabra}' ya está en la lista de palabras/frases baneadas.")
        return
    banwords.append(palabra)
    guardar_banwords(banwords)
    await update.message.reply_text(f"'{palabra}' añadida a la lista de palabras/frases baneadas.")

@only_owner
async def unbanword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /unbanword palabra_o_frase")
        return
    palabra = " ".join(context.args).strip().lower()
    banwords = cargar_banwords()
    if palabra not in banwords:
        await update.message.reply_text(f"'{palabra}' no está en la lista de palabras/frases baneadas.")
        return
    banwords = [w for w in banwords if w != palabra]
    guardar_banwords(banwords)
    await update.message.reply_text(f"'{palabra}' eliminada de la lista de palabras/frases baneadas.")


# --- Bot Telegram y scheduler ---
@only_owner
async def force_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Fetching and sending today's news...")
    try:
        # Obtener emails y noticias nuevas igual que en tarea_diaria
        emails = cargar_emails()
        nuevas_urls = obtener_noticias_nuevas()
        if not nuevas_urls:
            await update.message.reply_text("No new news to send.")
            return
        nuevas_urls = nuevas_urls[:10]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp_epub:
            tmp_epub.close()
            crear_epub_con_noticias(nuevas_urls, tmp_epub.name)
            results = []
            for email in emails:
                try:
                    await enviar_email_kindle(tmp_epub.name, "Noticias Diarias", email)
                    results.append(f"✅ Email sent to {email}")
                except Exception as e:
                    results.append(f"❌ Error sending to {email}: {e}")
            os.unlink(tmp_epub.name)
        await update.message.reply_text("\n".join(results))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bienvenido. Este bot genera un EPUB diario con noticias relevantes.\n"
        "Comandos:\n"
        "/addemail correo@ejemplo.com — Agrega correo\n"
        "/listemails — Lista correos\n"
        "/addsource Nombre URL_RSS — Agrega fuente\n"
        "/listsources — Lista fuentes\n"
        "/generate — Genera y envía manualmente\n"
        "/update — Actualiza desde GitHub\n"
        "/status — Estado general"
    )

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    print(f"[DEBUG] Update recibido de user_id={user_id}: {update}")
    if str(user_id) == str(CHAT_ID):
        await update.message.reply_text("Mensaje recibido.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addemail", add_email))
    app.add_handler(CommandHandler("removeemail", remove_email))
    app.add_handler(CommandHandler("listemails", list_emails))
    app.add_handler(CommandHandler("addsource", add_source))
    app.add_handler(CommandHandler("removesource", remove_source))
    app.add_handler(CommandHandler("listsources", list_sources))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("update", update_bot))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("force", force_send))
    app.add_handler(CommandHandler("banword", banword))
    app.add_handler(CommandHandler("unbanword", unbanword))
    app.add_handler(MessageHandler(filters.ALL, log_all_updates))
    scheduler = BackgroundScheduler()
    scheduler.add_job(tarea_diaria, "cron", hour=7, minute=0, args=[app])
    scheduler.start()
    print("[LOG] Iniciando bot...")
    app.run_polling()
    print("[LOG] Bot detenido.")

if __name__ == "__main__":
    main()

