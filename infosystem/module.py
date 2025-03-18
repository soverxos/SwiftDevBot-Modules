from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.filters import Command
import logging
import psutil
import platform
import subprocess
import sys
import os
import socket
import json
import asyncio
from datetime import datetime

router = Router()
logger = logging.getLogger("modules.infosystem")
data = None
message_count = 0
INFO_MESSAGE_FILE = None
LOG_FILE = None
cache = {"cpu": None, "memory": None, "disk": None}
cache_timeout = 60
LOGS_PER_PAGE = 5
LOGS_CACHE = {"logs": [], "last_updated": 0}
LOGS_CACHE_TIMEOUT = 60

async def update_cache():
    while True:
        cache["cpu"] = psutil.cpu_percent(interval=0.1)
        cache["memory"] = psutil.virtual_memory().percent
        cache["disk"] = psutil.disk_usage('/').percent
        if cache["memory"] > 90:
            await data["bot"].send_message(data["admin_ids"][0], "⚠️ Память заполнена более чем на 90%!")
        if cache["disk"] > 95:
            await data["bot"].send_message(data["admin_ids"][0], "⚠️ Диск заполнен более чем на 95%!")
        await asyncio.sleep(cache_timeout)

async def update_logs_cache():
    global LOGS_CACHE
    while True:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                LOGS_CACHE["logs"] = f.read().splitlines()
            LOGS_CACHE["last_updated"] = datetime.now().timestamp()
            logger.info("Логи закэшированы в памяти")
        await asyncio.sleep(LOGS_CACHE_TIMEOUT)

def setup(d):
    global data, INFO_MESSAGE_FILE, LOG_FILE
    dp = d["dp"]
    data = d
    INFO_MESSAGE_FILE = os.path.join(data["base_dir"], "data", "info_message.json")
    LOG_FILE = os.path.join(data["base_dir"], "data", "logs.txt")
    dp.include_router(router)
    logger.info("🛠 Модуль InfoSystem настроен")

def get_commands():
    return [
        types.BotCommand(command="/info", description="ℹ️ Показать системную информацию"),
        types.BotCommand(command="/botstats", description="📊 Статистика бота"),
        types.BotCommand(command="/restartbot", description="🔁 Перезапустить бота (админ)"),
        types.BotCommand(command="/resetstats", description="🔄 Сбросить статистику (админ)")
    ]

def is_docker():
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except FileNotFoundError:
        return False

def is_wsl():
    return "microsoft" in platform.uname().release.lower()

def save_info_message(chat_id, message_id):
    with open(INFO_MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"chat_id": chat_id, "message_id": message_id}, f)
    logger.info(f"Сохранён message_id {message_id} для chat_id {chat_id}")

def load_info_message():
    if os.path.exists(INFO_MESSAGE_FILE):
        with open(INFO_MESSAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def get_cpu_info():
    cpu_cores = psutil.cpu_count(logical=True)
    cpu_physical = psutil.cpu_count(logical=False)
    return f"🖥 ЦП:\n⚡ Использование: {cache['cpu']}%\n🧩 Логические ядра: {cpu_cores}\n🔩 Физические ядра: {cpu_physical}"

def get_memory_info():
    memory = psutil.virtual_memory()
    total = memory.total / (1024 ** 3)
    used = memory.used / (1024 ** 3)
    free = memory.available / (1024 ** 3)
    return f"💾 Память:\n📈 Использовано: {cache['memory']}%\n📦 Всего: {total:.2f} ГБ\n📈 Использовано: {used:.2f} ГБ\n📉 Свободно: {free:.2f} ГБ"

def get_disk_info():
    disk = psutil.disk_usage('/')
    total = disk.total / (1024 ** 3)
    used = disk.used / (1024 ** 3)
    free = disk.free / (1024 ** 3)
    return f"📀 Диск (/):\n📈 Использовано: {cache['disk']}%\n📦 Всего: {total:.2f} ГБ\n📈 Использовано: {used:.2f} ГБ\n📉 Свободно: {free:.2f} ГБ"

def get_system_info():
    os_name = platform.system()
    os_version = platform.release()
    hostname = platform.node()
    uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    env = "Docker" if is_docker() else "WSL" if is_wsl() else "Native OS"
    return f"🛠 Система:\n🖥 ОС: {os_name} {os_version}\n🖧 Хост: {hostname}\n🌍 Окружение: {env}\n⏳ Время работы: {str(uptime).split('.')[0]}"

def get_network_info():
    net_io = psutil.net_io_counters()
    bytes_sent = net_io.bytes_sent / (1024 ** 2)
    bytes_recv = net_io.bytes_recv / (1024 ** 2)
    interfaces = psutil.net_if_addrs()
    ip_info = ""
    for iface, addrs in interfaces.items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                ip_info += f"{iface}: {addr.address}\n"
    try:
        connections = len(psutil.net_connections()) if not is_docker() else "N/A (Docker)"
    except psutil.AccessDenied:
        connections = "N/A (нет доступа)"
    return f"🌐 Сеть:\n📤 Отправлено: {bytes_sent:.2f} МБ\n📥 Получено: {bytes_recv:.2f} МБ\n🖧 IP-адреса:\n{ip_info}🔗 Активных соединений: {connections}"

def get_temp_info():
    if is_docker() or is_wsl():
        return "🌡️ Температура: недоступно в Docker/WSL"
    try:
        temp = psutil.sensors_temperatures()
        if not temp:
            return "🌡️ Температура: данные недоступны (установите lm-sensors)"
        cpu_temp = temp.get('coretemp', temp.get('cpu_thermal', []))
        if cpu_temp:
            return f"🌡️ Температура ЦП: {cpu_temp[0].current}°C"
        return "🌡️ Температура: данные недоступны"
    except Exception as e:
        return f"🌡️ Температура: ошибка ({e})"

def get_processes_info():
    try:
        processes = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']), 
                           key=lambda p: p.info['cpu_percent'], reverse=True)[:5]
        result = "⚙️ Топ-5 процессов:\n"
        for proc in processes:
            result += f"PID: {proc.info['pid']} | {proc.info['name']} | ЦП: {proc.info['cpu_percent']:.1f}% | RAM: {proc.info['memory_percent']:.1f}%\n"
        return result
    except psutil.AccessDenied:
        return "⚙️ Процессы: нет доступа (Docker/WSL ограничения)"

def get_bot_stats():
    global message_count
    uptime = datetime.now() - data["start_time"]
    return f"🤖 Статистика бота:\n⏳ Время работы: {str(uptime).split('.')[0]}\n📨 Обработано сообщений: {message_count}"

def get_system_logs(page=0):
    try:
        if LOGS_CACHE["logs"]:
            logs = LOGS_CACHE["logs"]
            total_pages = (len(logs) - 1) // LOGS_PER_PAGE + 1
            start = page * LOGS_PER_PAGE
            end = start + LOGS_PER_PAGE
            recent_logs = "\n".join(logs[start:end])
            return f"📜 Логи бота (страница {page + 1} из {total_pages}):\n{recent_logs}", total_pages
        else:
            return "📜 Логи бота: файл logs.txt отсутствует или ещё не закэширован", 1
    except Exception as e:
        return f"📜 Логи бота: ошибка ({e})", 1

def get_os_updates():
    os_name = platform.system().lower()
    try:
        if "ubuntu" in os_name or "debian" in os_name:
            subprocess.run(["apt-get", "update"], capture_output=True, text=True, check=True)
            result = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True)
            updates = result.stdout.splitlines()
        elif "centos" in os_name or "fedora" in os_name or "rhel" in os_name:
            pkg_manager = "dnf" if os.path.exists("/usr/bin/dnf") else "yum"
            result = subprocess.run([pkg_manager, "check-update"], capture_output=True, text=True)
            updates = [line for line in result.stdout.splitlines() if line and not line.startswith(("Last", "Security"))]
        else:
            return "📦 Обновления ОС: ОС не поддерживается (только Ubuntu/Debian/CentOS/RHEL)"
        if len(updates) > 1:
            return f"📦 Доступные обновления ОС (требуются права root):\n{len(updates)-1} пакетов\n" + "\n".join(updates[1:5]) + ("..." if len(updates) > 5 else "")
        return "📦 Обновления ОС: все пакеты актуальны"
    except subprocess.CalledProcessError as e:
        return f"📦 Обновления ОС: ошибка проверки ({e.stderr})"
    except PermissionError:
        return "📦 Обновления ОС: нет доступа (нужны права root)"
    except Exception as e:
        return f"📦 Обновления ОС: непредвиденная ошибка ({e})"

def get_info_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 ЦП", callback_data="info_cpu")],
        [InlineKeyboardButton(text="💾 Память", callback_data="info_memory")],
        [InlineKeyboardButton(text="📀 Диск", callback_data="info_disk")],
        [InlineKeyboardButton(text="🛠 Система", callback_data="info_system")],
        [InlineKeyboardButton(text="🌐 Сеть", callback_data="info_network")],
        [InlineKeyboardButton(text="🌡️ Температура", callback_data="info_temp")],
        [InlineKeyboardButton(text="⚙️ Процессы", callback_data="info_processes")],
        [InlineKeyboardButton(text="🤖 Статистика", callback_data="info_botstats")],
        [InlineKeyboardButton(text="📜 Логи", callback_data="info_logs?page=0")],
        [InlineKeyboardButton(text="📦 Обновления", callback_data="info_updates")],
        [InlineKeyboardButton(text="🔁 Перезапустить", callback_data="info_restart")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="info_refresh")]
    ])
    return "📡 Выберите, что показать:", keyboard

@router.message(Command("info"))
async def info_command(message: types.Message):
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа!")
        logger.info(f"⛔ Доступ к /info запрещён для {message.from_user.id}")
        return
    
    text, keyboard = get_info_menu()
    sent_message = await message.answer(text, reply_markup=keyboard)
    save_info_message(message.chat.id, sent_message.message_id)
    logger.info(f"📌 Панель /info отправлена для {message.from_user.id}")

@router.message(Command("botstats"))
async def botstats_command(message: types.Message):
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа!")
        logger.info(f"⛔ Доступ к /botstats запрещён для {message.from_user.id}")
        return
    stats = get_bot_stats()
    await message.answer(stats)
    logger.info(f"📊 Статистика бота отправлена для {message.from_user.id}")

@router.message(Command("restartbot"))
async def restart_command(message: types.Message):
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа!")
        logger.info(f"⛔ Доступ к /restartbot запрещён для {message.from_user.id}")
        return
    await message.answer("🔁 Бот перезапускается...")
    logger.info("Перезапуск бота через /restartbot...")
    sys.exit(0)

@router.message(Command("resetstats"))
async def reset_stats_command(message: types.Message):
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа!")
        logger.info(f"⛔ Доступ к /resetstats запрещён для {message.from_user.id}")
        return
    message_count = 0
    await message.answer("🔄 Статистика сброшена!")
    logger.info(f"📉 Статистика сброшена для {message.from_user.id}")

@router.callback_query(lambda c: c.data.startswith("info_"))
async def info_callback(callback: types.CallbackQuery):
    global message_count
    message_count += 1
    logger.info(f"📩 Получен callback: {callback.data} от {callback.from_user.id}")
    if callback.from_user.id not in data["admin_ids"]:
        await callback.answer("🚫 У вас нет доступа!")
        logger.info(f"⛔ Доступ запрещён для callback {callback.data} от {callback.from_user.id}")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 ЦП", callback_data="info_cpu")],
        [InlineKeyboardButton(text="💾 Память", callback_data="info_memory")],
        [InlineKeyboardButton(text="📀 Диск", callback_data="info_disk")],
        [InlineKeyboardButton(text="🛠 Система", callback_data="info_system")],
        [InlineKeyboardButton(text="🌐 Сеть", callback_data="info_network")],
        [InlineKeyboardButton(text="🌡️ Температура", callback_data="info_temp")],
        [InlineKeyboardButton(text="⚙️ Процессы", callback_data="info_processes")],
        [InlineKeyboardButton(text="🤖 Статистика", callback_data="info_botstats")],
        [InlineKeyboardButton(text="📜 Логи", callback_data="info_logs?page=0")],
        [InlineKeyboardButton(text="📦 Обновления", callback_data="info_updates")],
        [InlineKeyboardButton(text="🔁 Перезапустить", callback_data="info_restart")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="info_refresh")]
    ])

    if callback.data == "info_cpu":
        info = get_cpu_info()
    elif callback.data == "info_memory":
        info = get_memory_info()
    elif callback.data == "info_disk":
        info = get_disk_info()
    elif callback.data == "info_system":
        info = get_system_info()
    elif callback.data == "info_network":
        info = get_network_info()
    elif callback.data == "info_temp":
        info = get_temp_info()
    elif callback.data == "info_processes":
        info = get_processes_info()
    elif callback.data == "info_botstats":
        info = get_bot_stats()
    elif callback.data.startswith("info_logs?page="):
        page = int(callback.data.split("page=")[1])
        logs, total_pages = get_system_logs(page)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"info_logs?page={page-1}") if page > 0 else InlineKeyboardButton(text=" ", callback_data="noop"),
             InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"info_logs?page={page+1}") if page < total_pages - 1 else InlineKeyboardButton(text=" ", callback_data="noop")],
            [InlineKeyboardButton(text="Скачать логи", callback_data="info_download_logs")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="info_refresh")]
        ])
        info = logs
    elif callback.data == "info_download_logs":
        with open(LOG_FILE, "rb") as f:
            await callback.message.reply_document(InputFile(f, filename="logs.txt"), caption="📑 Полные логи бота")
        await callback.answer()
        return
    elif callback.data == "info_updates":
        info = get_os_updates()
    elif callback.data == "info_restart":
        await callback.message.edit_text("🔁 Бот перезапускается...", reply_markup=None)
        save_info_message(callback.message.chat.id, callback.message.message_id)
        await callback.answer()
        logger.info("Перезапуск бота через callback info_restart...")
        sys.exit(0)
    elif callback.data == "info_refresh":
        info = "🔄 Данные обновлены!"

    await callback.message.edit_text(info, reply_markup=keyboard)
    await callback.answer()
    logger.info(f"📤 Информация отправлена для {callback.from_user.id}")

async def on_startup(d):
    logger.info("🚀 Модуль InfoSystem запущен.")
    asyncio.create_task(update_cache())
    asyncio.create_task(update_logs_cache())
    bot = d["bot"]
    saved_message = load_info_message()
    if saved_message:
        try:
            text, keyboard = get_info_menu()
            await bot.edit_message_text(
                chat_id=saved_message["chat_id"],
                message_id=saved_message["message_id"],
                text=f"✅ Бот перезапущен!\n\n{text}",
                reply_markup=keyboard
            )
            logger.info(f"Обновлено сообщение {saved_message['message_id']} после перезапуска в /info")
        except Exception as e:
            logger.error(f"Ошибка обновления сообщения /info после перезапуска: {e}")
            if "message to edit not found" in str(e):
                os.remove(INFO_MESSAGE_FILE)
                logger.info(f"Сброшено сохранённое сообщение /info из-за ошибки 'message to edit not found'")

async def on_shutdown(d):
    logger.info("📴 Модуль InfoSystem завершает работу.")
