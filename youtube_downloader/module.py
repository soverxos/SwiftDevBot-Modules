# ./modules/youtube_downloader/module.py
import os
import json
import logging
import asyncio
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import yt_dlp

# Настройка логирования
logger = logging.getLogger(__name__)

# Инициализация роутера
router = Router()

# Глобальные переменные
_kernel_data = None
DOWNLOAD_DIR = None

# Определение состояний FSM
class YoutubeStates(StatesGroup):
    waiting_for_url = State()

# Метаданные модуля
DISPLAY_NAME = "YouTube Downloader 📹"
DESCRIPTION = "Скачивает видео и аудио с YouTube, Facebook, Instagram и других платформ."
GLOBAL_PARAMETERS = {
    "max_quality": {
        "description": "Максимальное качество видео (360, 720, 1080)",
        "required": False,
        "default": "720"
    }
}
USER_PARAMETERS = {
    "default_format": {
        "description": "Формат по умолчанию (video/audio)",
        "required": False,
        "default": "video"
    },
    "default_quality": {
        "description": "Качество видео по умолчанию (360, 720, 1080)",
        "required": False,
        "default": "720"
    }
}

def setup(kernel_data):
    """Инициализация модуля при загрузке."""
    global _kernel_data, DOWNLOAD_DIR
    _kernel_data = kernel_data
    dp = kernel_data["dp"]
    base_dir = kernel_data["base_dir"]
    dp.include_router(router)
    
    DOWNLOAD_DIR = os.path.join(base_dir, "data", "youtube_downloads")
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        logger.info(f"Создана папка для загрузок: {DOWNLOAD_DIR}")
    
    db = kernel_data.get("db")
    if db is None:
        logger.error("База данных не инициализирована в kernel_data['db']!")
        raise ValueError("База данных не инициализирована!")
    
    asyncio.create_task(init_db(db))
    init_config(base_dir)
    
    logger.info(f"Модуль {DISPLAY_NAME} успешно загружен и настроен")

async def init_db(db):
    """Инициализация таблицы для хранения пользовательских настроек."""
    module_name = __name__.split(".")[-2]
    table_name = f"{module_name}_config"
    try:
        async with db.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'") as cursor:
            if not await cursor.fetchone():
                await db.execute(f"""
                    CREATE TABLE {table_name} (
                        user_id INTEGER PRIMARY KEY,
                        default_format TEXT,
                        default_quality TEXT
                    )
                """)
                await db.commit()
                logger.info(f"Таблица {table_name} создана")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise

def init_config(base_dir):
    """Инициализация конфигурационного файла модуля."""
    module_name = __name__.split(".")[-2]
    config_path = os.path.join(base_dir, "modules", module_name, "config.json")
    try:
        if not os.path.exists(config_path):
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            default_config = {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Создан новый config.json: {config_path}")
    except Exception as e:
        logger.error(f"Ошибка при инициализации конфигурации: {e}")
        raise

def load_config(base_dir):
    """Загрузка конфигурации модуля."""
    module_name = __name__.split(".")[-2]
    config_path = os.path.join(base_dir, "modules", module_name, "config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}

async def get_user_config(db, user_id):
    """Получение пользовательских настроек из базы данных."""
    if db is None:
        logger.error("База данных не инициализирована!")
        return {}
    module_name = __name__.split(".")[-2]
    table_name = f"{module_name}_config"
    try:
        async with db.execute(f"SELECT default_format, default_quality FROM {table_name} WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and len(row) >= 2:  # Проверяем, что результат содержит оба значения
                return {"default_format": row[0], "default_quality": row[1]}
            return {}  # Возвращаем пустой словарь, если данных нет
    except Exception as e:
        logger.error(f"Ошибка при получении настроек пользователя {user_id}: {e}")
        return {}

async def set_user_config(db, user_id, config):
    """Сохранение пользовательских настроек в базе данных."""
    if db is None:
        logger.error("База данных не инициализирована!")
        return
    module_name = __name__.split(".")[-2]
    table_name = f"{module_name}_config"
    try:
        if config is None:
            await db.execute(f"DELETE FROM {table_name} WHERE user_id = ?", (user_id,))
        else:
            default_format = config.get("default_format", USER_PARAMETERS["default_format"]["default"])
            default_quality = config.get("default_quality", USER_PARAMETERS["default_quality"]["default"])
            await db.execute(
                f"INSERT OR REPLACE INTO {table_name} (user_id, default_format, default_quality) VALUES (?, ?, ?)",
                (user_id, default_format, default_quality)
            )
        await db.commit()
        logger.info(f"Настройки пользователя {user_id} обновлены: {config}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек пользователя {user_id}: {e}")
        raise

async def get_settings_menu(user_id, is_enabled, admin_ids, kernel_data):
    """Формирование меню настроек модуля."""
    module_name = __name__.split(".")[-2]
    text = (f"📋 **{DISPLAY_NAME}** ({'🟢 Вкл' if is_enabled else '🔴 Выкл'})\n"
            f"📝 **Описание:** {DESCRIPTION}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **Текущие настройки:**\n")
    
    keyboard = []
    
    # Глобальные параметры (для админов)
    if user_id in admin_ids:
        global_config = load_config(kernel_data["base_dir"])
        for param, info in GLOBAL_PARAMETERS.items():
            value = global_config.get(param, info["default"])
            text += f"🔧 {info['description']}: **{value}**\n"
        text += "\n"
        for param in GLOBAL_PARAMETERS:
            keyboard.append([types.InlineKeyboardButton(
                text=f"🔧 Изменить {param}",
                callback_data=f"set_global_{module_name}_{param}"
            )])
        keyboard.append([types.InlineKeyboardButton(
            text=f"{'🔴 Выключить' if is_enabled else '🟢 Включить'}",
            callback_data=f"toggle_{module_name}"
        )])
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить модуль",
            callback_data=f"delete_module_{module_name}"
        )])

    # Пользовательские параметры
    user_config = await get_user_config(kernel_data["db"], user_id)
    for param, info in USER_PARAMETERS.items():
        value = user_config.get(param, info["default"])
        text += f"👤 {info['description']}: **{value}**\n"
    for param in USER_PARAMETERS:
        emoji = "🎥" if param == "default_format" else "📐"
        keyboard.append([types.InlineKeyboardButton(
            text=f"{emoji} Изменить {param}",
            callback_data=f"set_user_{module_name}_{param}"
        )])
    if user_config:
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить мои настройки",
            callback_data=f"delete_config_{module_name}"
        )])
    
    keyboard.append([types.InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="list_modules"
    )])
    
    return text, keyboard

async def download_file(url: str, format_type: str, quality: str = None) -> tuple[str, str]:
    """Скачивание файла с помощью yt-dlp."""
    ydl_opts = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
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
            return file_path, title
    except Exception as e:
        logger.error(f"Ошибка скачивания {url}: {e}")
        raise Exception(f"Не удалось скачать файл: {e}")

@router.message(Command("yt"))
async def yt_command(message: types.Message, state: FSMContext):
    """Обработка команды /yt."""
    if _kernel_data is None:
        await message.answer("❌ Ошибка: модуль не инициализирован корректно!")
        return
    
    db = _kernel_data.get("db")
    if db is None:
        await message.answer("❌ Ошибка: база данных не инициализирована!")
        return
    
    args = message.text.replace("/yt", "").strip()
    if args:
        await process_url(message, args, state)
    else:
        await message.answer("📹 Введите URL для скачивания (YouTube, Facebook, Instagram и т.д.):")
        await state.set_state(YoutubeStates.waiting_for_url)

@router.message(YoutubeStates.waiting_for_url)
async def process_url_input(message: types.Message, state: FSMContext):
    """Обработка ввода URL пользователем."""
    url = message.text.strip()
    if not url:
        await message.answer("📹 Пожалуйста, введите корректный URL:")
        return
    await process_url(message, url, state)

async def process_url(message: types.Message, url: str, state: FSMContext):
    """Предложение выбора формата."""
    user_config = await get_user_config(_kernel_data["db"], message.from_user.id)
    default_format = user_config.get("default_format", USER_PARAMETERS["default_format"]["default"])
    
    keyboard = [
        [types.InlineKeyboardButton(text="🎥 Видео", callback_data=f"yt_video_{url}")],
        [types.InlineKeyboardButton(text="🎵 Аудио (MP3)", callback_data=f"yt_audio_{url}")],
        [types.InlineKeyboardButton(text=f"⚙️ По умолчанию ({default_format})", callback_data=f"yt_default_{url}")]
    ]
    await message.answer("Выберите формат для скачивания:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.clear()

@router.callback_query(lambda c: c.data.startswith("yt_"))
async def process_selection(callback: types.CallbackQuery):
    """Обработка выбора формата и качества."""
    data_parts = callback.data.split("_", 2)
    action = data_parts[1]
    url = data_parts[2]
    user_id = callback.from_user.id
    
    user_config = await get_user_config(_kernel_data["db"], user_id)
    default_format = user_config.get("default_format", USER_PARAMETERS["default_format"]["default"])
    default_quality = user_config.get("default_quality", USER_PARAMETERS["default_quality"]["default"])
    global_config = load_config(_kernel_data["base_dir"])
    max_quality = global_config.get("max_quality", GLOBAL_PARAMETERS["max_quality"]["default"])
    
    if action == "default":
        format_type = default_format
        quality = default_quality if format_type == "video" else None
        if format_type == "video" and int(quality) > int(max_quality):
            quality = max_quality
        await callback.message.edit_text(f"⏳ Скачиваю ({format_type}{' ' + quality + 'p' if quality else ''})...")
        await process_download(callback.message, url, format_type, quality)
    
    elif action == "video":
        keyboard = [
            [types.InlineKeyboardButton(text="360p", callback_data=f"yt_quality_360_{url}")],
            [types.InlineKeyboardButton(text="720p", callback_data=f"yt_quality_720_{url}")],
            [types.InlineKeyboardButton(text="1080p", callback_data=f"yt_quality_1080_{url}")]
        ]
        await callback.message.edit_text("Выберите качество видео:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))
    
    elif action == "audio":
        await callback.message.edit_text("⏳ Скачиваю аудио...")
        await process_download(callback.message, url, "audio", None)
    
    elif action == "quality":
        quality = data_parts[2]
        if int(quality) > int(max_quality):
            await callback.message.edit_text(f"❌ Качество {quality}p превышает максимальное ({max_quality}p).")
            return
        await callback.message.edit_text(f"⏳ Скачиваю видео ({quality}p)...")
        await process_download(callback.message, url, "video", quality)

async def process_download(message: types.Message, url: str, format_type: str, quality: str = None):
    """Скачивание и отправка файла."""
    try:
        file_path, title = await download_file(url, format_type, quality)
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        if file_size > 50:
            await message.reply(f"❌ Файл слишком большой ({file_size:.2f} МБ). Максимум: 50 МБ.")
            os.remove(file_path)
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
        
        os.remove(file_path)
        logger.info(f"Файл {title} ({format_type}) отправлен пользователю {message.from_user.id}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")
        logger.error(f"Ошибка скачивания {url}: {e}")

def get_commands():
    """Список команд модуля."""
    return [
        {"command": types.BotCommand(command="/yt", description="📹 Скачать с YouTube, Facebook и др."), "access": "all"}
    ]

async def on_startup(kernel_data):
    """Действия при запуске модуля."""
    logger.info(f"Модуль {DISPLAY_NAME} запущен")

async def on_shutdown(kernel_data):
    """Действия при завершении работы модуля."""
    logger.info(f"Модуль {DISPLAY_NAME} завершён")