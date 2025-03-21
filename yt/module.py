# ./modules/youtube_downloader/module.py
import os
import asyncio
import logging
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

router = Router()
logger = logging.getLogger("youtube_downloader")

DOWNLOAD_DIR = None
kernel_data = None

def setup(data):
    """Настройка модуля"""
    global DOWNLOAD_DIR, kernel_data
    kernel_data = data
    dp = data["dp"]
    base_dir = data["base_dir"]
    dp.include_router(router)
    
    DOWNLOAD_DIR = os.path.join(base_dir, "data", "youtube_downloads")
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        logger.info(f"Создана папка для загрузок: {DOWNLOAD_DIR}")
    
    router.download_dir = DOWNLOAD_DIR
    router.user_states = {}
    logger.info("Модуль youtube_downloader настроен")

def get_module_info():
    """Информация о модуле"""
    return {
        "name": "youtube_downloader",
        "display_name": "YouTube Downloader",
        "description": "Скачивает видео и аудио с YouTube, Facebook или Instagram",
        "global_params": {
            "max_quality": {
                "description": "Максимальное качество видео по умолчанию (360, 720, 1080)",
                "default": "720"
            }
        },
        "user_params": {
            "default_format": {
                "description": "Формат по умолчанию (video/audio)",
                "default": "video"
            },
            "default_quality": {
                "description": "Качество видео по умолчанию (360, 720, 1080)",
                "default": "720"
            }
        }
    }

def get_commands():
    """Список команд модуля"""
    return [
        {"command": types.BotCommand(command="/yt", description="📹 Скачать с YouTube, Facebook или Instagram"), "access": "all"}
    ]

async def get_settings_menu(user_id: int, is_enabled: bool, admin_ids: list, data: dict):
    """Меню настроек модуля"""
    module_info = get_module_info()
    display_name = module_info["display_name"]
    text = f"📹 {display_name} ({'ON🟢' if is_enabled else 'OFF🔴'})"
    keyboard = []

    # Глобальные параметры (для админов)
    if user_id in admin_ids:
        global_config_path = os.path.join(data["base_dir"], "modules", "youtube_downloader", "config.json")
        global_config = {}
        if os.path.exists(global_config_path):
            with open(global_config_path, "r", encoding="utf-8") as f:
                import json
                global_config = json.load(f)
        max_quality = global_config.get("max_quality", module_info["global_params"]["max_quality"]["default"])
        text += f"\n- Максимальное качество: {max_quality}p"
        keyboard.append([
            InlineKeyboardButton(text="Изменить макс. качество", callback_data="set_global_youtube_downloader_max_quality")
        ])
        if is_enabled:
            keyboard.append([
                InlineKeyboardButton(text="Выключить", callback_data="toggle_youtube_downloader")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(text="Включить", callback_data="toggle_youtube_downloader")
            ])
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить модуль", callback_data="delete_module_youtube_downloader")
        ])

    # Пользовательские параметры
    user_config = await get_user_config(data["db"], user_id) or {}
    default_format = user_config.get("default_format", module_info["user_params"]["default_format"]["default"])
    default_quality = user_config.get("default_quality", module_info["user_params"]["default_quality"]["default"])
    text += f"\n- Формат по умолчанию: {default_format}"
    text += f"\n- Качество по умолчанию: {default_quality}p"
    keyboard.append([
        InlineKeyboardButton(text="Изменить формат", callback_data="set_user_youtube_downloader_default_format")
    ])
    keyboard.append([
        InlineKeyboardButton(text="Изменить качество", callback_data="set_user_youtube_downloader_default_quality")
    ])
    if user_config:
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить мои настройки", callback_data="delete_config_youtube_downloader")
        ])
    
    keyboard.append([
        InlineKeyboardButton(text="↩️ Назад", callback_data="list_modules")
    ])
    
    return text, keyboard

async def get_user_config(db, user_id):
    """Получение пользовательских настроек из базы данных"""
    if db is None:
        logger.error("База данных не инициализирована!")
        return None
    async with db.execute("SELECT config FROM user_configs WHERE module_name = ? AND user_id = ?", 
                         ("youtube_downloader", user_id)) as cursor:
        row = await cursor.fetchone()
        if row:
            import json
            return json.loads(row[0])
    return None

async def set_user_config(db, user_id, config):
    """Сохранение пользовательских настроек в базу данных"""
    if db is None:
        logger.error("База данных не инициализирована!")
        return
    import json
    config_json = json.dumps(config) if config is not None else None
    await db.execute(
        "INSERT OR REPLACE INTO user_configs (module_name, user_id, config) VALUES (?, ?, ?)",
        ("youtube_downloader", user_id, config_json)
    )
    await db.commit()

async def download_file(url: str, download_dir: str, format_type: str, quality: str = None) -> tuple[str, str, str]:
    """Скачивание файла с YouTube, Facebook или Instagram"""
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,  # Скачивать только одно видео, а не плейлист
    }
    
    if format_type == "video":
        ydl_opts["format"] = f"bestvideo[height<={quality}][filesize<50M]+bestaudio/best[filesize<50M]"
        ydl_opts["merge_output_format"] = "mp4"
    elif format_type == "audio":
        ydl_opts["format"] = "bestaudio/best[filesize<50M]"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if format_type == "audio":
                file_path = file_path.rsplit(".", 1)[0] + ".mp3"
            title = info.get("title", "Без названия")
            thumbnail_url = info.get("thumbnail", "")
            return file_path, title, thumbnail_url
    except Exception as e:
        logger.error(f"Ошибка скачивания {url}: {e}")
        raise Exception(f"Не удалось скачать файл: {e}")

@router.message(Command("yt"))
async def download_command(message: types.Message):
    """Обработка команды /yt"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажи ссылку на видео: /yt <URL> (YouTube, Facebook или Instagram)")
        logger.info(f"Пользователь {message.from_user.id} не указал URL для /yt")
        return
    
    url = args[1]
    router.user_states[message.from_user.id] = {"url": url}
    
    user_config = await get_user_config(kernel_data["db"], message.from_user.id) or {}
    default_format = user_config.get("default_format", "video")
    
    if default_format == "video":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Видео", callback_data="format_video")],
            [InlineKeyboardButton(text="🎵 Аудио (MP3)", callback_data="format_audio")],
            [InlineKeyboardButton(text="⚙️ По умолчанию (видео)", callback_data="use_default")]
        ])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Видео", callback_data="format_video")],
            [InlineKeyboardButton(text="🎵 Аудио (MP3)", callback_data="format_audio")],
            [InlineKeyboardButton(text="⚙️ По умолчанию (аудио)", callback_data="use_default")]
        ])
    
    await message.answer("Выбери формат для скачивания:", reply_markup=keyboard)
    logger.info(f"Пользователь {message.from_user.id} ввёл URL {url}, предложен выбор формата")

@router.callback_query(lambda c: c.data.startswith("format_") or c.data == "use_default")
async def process_format_selection(callback: types.CallbackQuery):
    """Обработка выбора формата"""
    user_id = callback.from_user.id
    url = router.user_states.get(user_id, {}).get("url")
    
    if not url:
        await callback.message.edit_text("Ошибка: URL потерян. Попробуй заново с /yt.")
        logger.error(f"URL потерян для пользователя {user_id}")
        return
    
    if callback.data == "use_default":
        user_config = await get_user_config(kernel_data["db"], user_id) or {}
        default_format = user_config.get("default_format", "video")
        default_quality = user_config.get("default_quality", "720")
        if default_format == "video":
            await callback.message.edit_text(f"⏳ Начинаю скачивание видео ({default_quality}p)...")
            asyncio.create_task(process_download(callback.message, url, "video", user_id, default_quality))
        else:
            await callback.message.edit_text("⏳ Начинаю скачивание аудио...")
            asyncio.create_task(process_download(callback.message, url, "audio", user_id))
        return
    
    format_type = callback.data.split("_")[1]
    if format_type == "video":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="360p", callback_data="quality_360")],
            [InlineKeyboardButton(text="720p", callback_data="quality_720")],
            [InlineKeyboardButton(text="1080p", callback_data="quality_1080")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
        ])
        await callback.message.edit_text("Выбери качество видео:", reply_markup=keyboard)
        logger.info(f"Пользователь {user_id} выбрал видео для {url}, предложен выбор качества")
    elif format_type == "audio":
        await callback.message.edit_text("⏳ Начинаю скачивание аудио...")
        asyncio.create_task(process_download(callback.message, url, "audio", user_id))

@router.callback_query(lambda c: c.data.startswith("quality_") or c.data == "cancel")
async def process_quality_selection(callback: types.CallbackQuery):
    """Обработка выбора качества или отмены"""
    user_id = callback.from_user.id
    url = router.user_states.get(user_id, {}).get("url")
    
    if not url:
        await callback.message.edit_text("Ошибка: URL потерян. Попробуй заново с /yt.")
        logger.error(f"URL потерян для пользователя {user_id}")
        return
    
    if callback.data == "cancel":
        await callback.message.edit_text("Скачивание отменено.")
        logger.info(f"Пользователь {user_id} отменил скачивание")
        del router.user_states[user_id]
        return
    
    quality = callback.data.split("_")[1]
    await callback.message.edit_text(f"⏳ Начинаю скачивание видео ({quality}p)...")
    asyncio.create_task(process_download(callback.message, url, "video", user_id, quality))

async def process_download(message: types.Message, url: str, format_type: str, user_id: int, quality: str = None):
    """Общий процесс скачивания и отправки файла"""
    try:
        global_config_path = os.path.join(kernel_data["base_dir"], "modules", "youtube_downloader", "config.json")
        global_config = {}
        if os.path.exists(global_config_path):
            with open(global_config_path, "r", encoding="utf-8") as f:
                import json
                global_config = json.load(f)
        max_quality = global_config.get("max_quality", "720")
        
        if quality and int(quality) > int(max_quality):
            await message.reply(f"❌ Выбранное качество ({quality}p) превышает максимальное ({max_quality}p).")
            logger.warning(f"Качество {quality}p превышает максимальное {max_quality}p для {user_id}")
            return
        
        file_path, title, thumbnail_url = await download_file(url, router.download_dir, format_type, quality)
        
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        if file_size > 50:
            await message.reply(f"❌ Файл слишком большой ({file_size:.2f} МБ). Максимум: 50 МБ.")
            os.remove(file_path)
            logger.warning(f"Файл {title} ({file_size:.2f} МБ) превышает лимит Telegram для {user_id}")
            return
        
        if format_type == "video":
            file = types.FSInputFile(file_path, filename=f"{title}.mp4")
            await message.reply_video(
                video=file,
                caption=f"🎥 {title} ({quality}p)",
                supports_streaming=True
            )
        elif format_type == "audio":
            file = types.FSInputFile(file_path, filename=f"{title}.mp3")
            await message.reply_audio(
                audio=file,
                title=title,
                caption="🎵 Скачано"
            )
        
        logger.info(f"Файл {title} ({format_type}) успешно отправлен пользователю {user_id}")
        os.remove(file_path)
        logger.info(f"Временный файл {file_path} удалён")
        
        if user_id in router.user_states:
            del router.user_states[user_id]
        
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")
        logger.error(f"Ошибка обработки скачивания для {url}: {e}")

async def on_startup(data):
    """Действия при запуске модуля"""
    logger.info("Модуль youtube_downloader запущен")
    # Создание таблицы для хранения пользовательских настроек
    if data["db"]:
        await data["db"].execute("""
            CREATE TABLE IF NOT EXISTS user_configs (
                module_name TEXT,
                user_id INTEGER,
                config TEXT,
                PRIMARY KEY (module_name, user_id)
            )
        """)
        await data["db"].commit()
        logger.info("Таблица user_configs инициализирована для youtube_downloader")

async def on_shutdown(data):
    """Действия при завершении работы модуля"""
    logger.info("Модуль youtube_downloader завершает работу")
