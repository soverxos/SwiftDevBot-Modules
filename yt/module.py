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

def setup(data):
    """Настройка модуля"""
    dp = data["dp"]
    base_dir = data["base_dir"]
    dp.include_router(router)
    
    DOWNLOAD_DIR = os.path.join(base_dir, "data", "youtube_downloads")
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        logger.info(f"Создана папка для загрузок: {DOWNLOAD_DIR}")
    
    router.download_dir = DOWNLOAD_DIR
    logger.info("Модуль youtube_downloader настроен")

def get_commands():
    """Список команд модуля"""
    return [
        types.BotCommand(command="/yt", description="📹 Скачать с YouTube, Facebook или Instagram")
    ]

async def download_file(url: str, download_dir: str, format_type: str, quality: str = None) -> tuple[str, str, str]:
    """Скачивание файла с YouTube, Facebook или Instagram"""
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
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
    if not hasattr(router, "user_states"):
        router.user_states = {}
    router.user_states[message.from_user.id] = {"url": url}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Видео", callback_data="format_video")],
        [InlineKeyboardButton(text="🎵 Аудио (MP3)", callback_data="format_audio")]
    ])
    await message.answer("Выбери формат для скачивания:", reply_markup=keyboard)
    logger.info(f"Пользователь {message.from_user.id} ввёл URL {url}, предложен выбор формата")

@router.callback_query(lambda c: c.data.startswith("format_"))
async def process_format_selection(callback: types.CallbackQuery):
    """Обработка выбора формата"""
    format_type = callback.data.split("_")[1]
    user_id = callback.from_user.id
    url = router.user_states.get(user_id, {}).get("url")
    
    if not url:
        await callback.message.edit_text("Ошибка: URL потерян. Попробуй заново с /yt.")
        logger.error(f"URL потерян для пользователя {user_id}")
        return
    
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
        return
    
    quality = callback.data.split("_")[1]
    await callback.message.edit_text(f"⏳ Начинаю скачивание видео ({quality}p)...")
    asyncio.create_task(process_download(callback.message, url, "video", user_id, quality))

async def process_download(message: types.Message, url: str, format_type: str, user_id: int, quality: str = None):
    """Общий процесс скачивания и отправки файла"""
    try:
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
        
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")
        logger.error(f"Ошибка обработки скачивания для {url}: {e}")

async def on_startup(data):
    """Действия при запуске модуля"""
    logger.info("Модуль youtube_downloader запущен")

async def on_shutdown(data):
    """Действия при завершении работы модуля"""
    logger.info("Модуль youtube_downloader завершает работу")