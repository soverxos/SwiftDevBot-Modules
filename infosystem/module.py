from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import logging
import psutil
import platform
import subprocess
import sys
import os
import asyncio
import requests
from datetime import datetime

router = Router()
logger = logging.getLogger("modules.infosystem")
data = None
message_count = 0  # Счетчик сообщений для статистики
cache = {"cpu": None, "memory": None, "disk": None}
cache_timeout = 60  # Кэш обновляется каждые 60 секунд

async def update_cache():
    """Обновление кэша данных CPU, RAM, ROM"""
    while True:
        cache["cpu"] = psutil.cpu_percent(interval=0.1)
        cache["memory"] = psutil.virtual_memory().percent
        cache["disk"] = psutil.disk_usage('/').percent
        await asyncio.sleep(cache_timeout)

def setup(d):
    """Настройка модуля"""
    global data
    dp = d["dp"]
    data = d
    dp.include_router(router)
    # Регистрируем фоновую задачу для обновления кэша
    data["background_tasks"].append(update_cache)
    logger.info("🛠 Модуль InfoSystem настроен")

def get_commands():
    """Список команд модуля"""
    return [
        types.BotCommand(command="/info", description="ℹ️ Системная информация"),
        types.BotCommand(command="/botstats", description="📊 Статистика бота")
    ]

def is_docker():
    """Проверка, работает ли бот в Docker"""
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except FileNotFoundError:
        return False

def is_wsl():
    """Проверка, работает ли бот в WSL"""
    return "microsoft" in platform.uname().release.lower()

def get_cpu_info():
    """Информация о CPU с характеристиками"""
    cpu_usage = cache["cpu"]
    cpu_model = platform.processor() or "Неизвестно"
    cpu_freq = psutil.cpu_freq()
    freq_info = f"{cpu_freq.current:.2f} МГц" if cpu_freq else "Н/Д"
    cores = psutil.cpu_count(logical=True)
    physical_cores = psutil.cpu_count(logical=False)
    return (f"🖥 ЦП:\n"
            f"⚡ Использование: {cpu_usage}%\n"
            f"🧩 Модель: {cpu_model}\n"
            f"⏱ Частота: {freq_info}\n"
            f"🔢 Ядер: {cores} (физических: {physical_cores})")

def get_memory_info():
    """Информация о RAM"""
    memory = psutil.virtual_memory()
    total = memory.total / (1024 ** 3)  # ГБ
    used = memory.used / (1024 ** 3)
    free = memory.available / (1024 ** 3)
    return (f"💾 Память:\n"
            f"📈 Использовано: {cache['memory']}%\n"
            f"📦 Всего: {total:.2f} ГБ\n"
            f"📈 Использовано: {used:.2f} ГБ\n"
            f"📉 Свободно: {free:.2f} ГБ")

def get_disk_info():
    """Информация о ROM (диске)"""
    disk = psutil.disk_usage('/')
    total = disk.total / (1024 ** 3)  # ГБ
    used = disk.used / (1024 ** 3)
    free = disk.free / (1024 ** 3)
    return (f"📀 Диск (/):\n"
            f"📈 Использовано: {cache['disk']}%\n"
            f"📦 Всего: {total:.2f} ГБ\n"
            f"📈 Использовано: {used:.2f} ГБ\n"
            f"📉 Свободно: {free:.2f} ГБ")

def get_system_info():
    """Информация об окружении"""
    env = "Docker" if is_docker() else "WSL" if is_wsl() else "Native OS"
    return f"🛠 Окружение:\n🌍 Тип: {env}"

def get_network_info():
    """Информация о сети с внешним и внутренним IP"""
    net_io = psutil.net_io_counters()
    bytes_sent = net_io.bytes_sent / (1024 ** 2)  # МБ
    bytes_recv = net_io.bytes_recv / (1024 ** 2)  # МБ
    try:
        external_ip = requests.get("https://api.ipify.org", timeout=5).text
    except Exception as e:
        external_ip = f"Ошибка ({e})"
    
    # Получаем внутренние IP-адреса
    interfaces = psutil.net_if_addrs()
    internal_network = ""
    for iface, addrs in interfaces.items():
        for addr in addrs:
            if addr.family == 2:  # AF_INET (IPv4)
                internal_network += f"{iface}: {addr.address}\n"
    internal_network = internal_network.strip() or "Нет данных"

    return (f"🌐 Сеть:\n"
            f"📤 Отправлено: {bytes_sent:.2f} МБ\n"
            f"📥 Получено: {bytes_recv:.2f} МБ\n"
            f"🌍 Внешний IP: {external_ip}\n"
            f"🖧 Внутренняя сеть:\n{internal_network}")

def get_os_updates():
    """Проверка и установка обновлений для различных UNIX-систем"""
    os_name = platform.system().lower()
    if "linux" not in os_name and "darwin" not in os_name and "bsd" not in os_name:
        return "Обновления: поддерживаются только UNIX-системы"

    try:
        # Определяем дистрибутив Linux или тип UNIX
        if "linux" in os_name:
            # Проверяем наличие файлов или команд для определения дистрибутива
            if os.path.exists("/etc/debian_version") or os.path.exists("/usr/bin/apt-get"):
                # Debian/Ubuntu (APT)
                subprocess.run(["apt-get", "update"], capture_output=True, text=True, check=True)
                result = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True)
                updates = result.stdout.splitlines()
                if len(updates) > 1:
                    try:
                        subprocess.run(["sudo", "apt-get", "upgrade", "-y"], capture_output=True, text=True, check=True)
                        return f"Обновления: установлено {len(updates)-1} пакетов (Debian/Ubuntu)"
                    except subprocess.CalledProcessError:
                        return f"Обновления: доступно {len(updates)-1} пакетов (нужен sudo для APT)"
                return "Обновления: все пакеты актуальны (Debian/Ubuntu)"

            elif os.path.exists("/etc/redhat-release") or os.path.exists("/usr/bin/dnf") or os.path.exists("/usr/bin/yum"):
                # Fedora/CentOS/RHEL (DNF или YUM)
                pkg_manager = "dnf" if os.path.exists("/usr/bin/dnf") else "yum"
                result = subprocess.run([pkg_manager, "check-update"], capture_output=True, text=True)
                updates = [line for line in result.stdout.splitlines() if line and not line.startswith(("Last", "Security"))]
                if updates:
                    try:
                        subprocess.run(["sudo", pkg_manager, "upgrade", "-y"], capture_output=True, text=True, check=True)
                        return f"Обновления: установлено {len(updates)} пакетов ({pkg_manager})"
                    except subprocess.CalledProcessError:
                        return f"Обновления: доступно {len(updates)} пакетов (нужен sudo для {pkg_manager})"
                return f"Обновления: все пакеты актуальны ({pkg_manager})"

            elif os.path.exists("/etc/arch-release") or os.path.exists("/usr/bin/pacman"):
                # Arch Linux (Pacman)
                result = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True, check=True)
                updates = result.stdout.splitlines()
                if updates:
                    try:
                        subprocess.run(["sudo", "pacman", "-Syu", "--noconfirm"], capture_output=True, text=True, check=True)
                        return f"Обновления: установлено {len(updates)} пакетов (Arch)"
                    except subprocess.CalledProcessError:
                        return f"Обновления: доступно {len(updates)} пакетов (нужен sudo для Pacman)"
                return "Обновления: все пакеты актуальны (Arch)"

            else:
                return "Обновления: неизвестный дистрибутив Linux"

        elif "darwin" in os_name:
            # macOS (Homebrew)
            if os.path.exists("/usr/local/bin/brew") or os.path.exists("/opt/homebrew/bin/brew"):
                subprocess.run(["brew", "update"], capture_output=True, text=True, check=True)
                result = subprocess.run(["brew", "outdated"], capture_output=True, text=True)
                updates = result.stdout.splitlines()
                if updates:
                    try:
                        subprocess.run(["brew", "upgrade"], capture_output=True, text=True, check=True)
                        return f"Обновления: установлено {len(updates)} пакетов (Homebrew)"
                    except subprocess.CalledProcessError:
                        return f"Обновления: доступно {len(updates)} пакетов (ошибка Homebrew)"
                return "Обновления: все пакеты актуальны (Homebrew)"
            return "Обновления: Homebrew не установлен (macOS)"

        elif "bsd" in os_name:
            # FreeBSD (pkg)
            if os.path.exists("/usr/sbin/pkg"):
                result = subprocess.run(["pkg", "upgrade", "-n"], capture_output=True, text=True)
                updates = result.stdout.splitlines()
                if "0 packages" not in result.stdout:
                    try:
                        subprocess.run(["sudo", "pkg", "upgrade", "-y"], capture_output=True, text=True, check=True)
                        return f"Обновления: установлены пакеты (FreeBSD)"
                    except subprocess.CalledProcessError:
                        return f"Обновления: доступны обновления (нужен sudo для pkg)"
                return "Обновления: все пакеты актуальны (FreeBSD)"
            return "Обновления: pkg не установлен (FreeBSD)"

        return "Обновления: неподдерживаемая UNIX-система"

    except subprocess.CalledProcessError as e:
        return f"Обновления: ошибка ({e.stderr})"
    except Exception as e:
        return f"Обновления: ошибка ({e})"

def get_bot_stats():
    """Статистика бота"""
    global message_count
    try:
        uptime = datetime.now() - data["start_time"]
        return (f"🤖 Статистика:\n"
                f"⏳ Время работы: {str(uptime).split('.')[0]}\n"
                f"📨 Сообщений: {message_count}")
    except Exception as e:
        logger.error(f"Ошибка в статистике: {e}")
        return "🤖 Статистика: ошибка вычисления"

def get_info_menu():
    """Меню выбора информации"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 ЦП", callback_data="info_cpu")],
        [InlineKeyboardButton(text="💾 Память", callback_data="info_memory")],
        [InlineKeyboardButton(text="📀 Диск", callback_data="info_disk")],
        [InlineKeyboardButton(text="🛠 Окружение", callback_data="info_system")],
        [InlineKeyboardButton(text="🌐 Сеть", callback_data="info_network")],
        [InlineKeyboardButton(text="📦 Обновления", callback_data="info_updates")],
        [InlineKeyboardButton(text="🤖 Статистика", callback_data="info_botstats")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="info_refresh")]
    ])
    return "📡 Выберите:", keyboard

@router.message(Command("info"))
async def info_command(message: types.Message):
    """Обработчик команды /info"""
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 Нет доступа!")
        logger.info(f"⛔ Доступ к /info запрещён для {message.from_user.id}")
        return
    
    text, keyboard = get_info_menu()
    await message.answer(text, reply_markup=keyboard)
    logger.info(f"📌 Панель /info отправлена для {message.from_user.id}")

@router.message(Command("botstats"))
async def botstats_command(message: types.Message):
    """Обработчик команды /botstats"""
    global message_count
    message_count += 1
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 Нет доступа!")
        logger.info(f"⛔ Доступ к /botstats запрещён для {message.from_user.id}")
        return
    stats = get_bot_stats()
    await message.answer(stats)
    logger.info(f"📊 Статистика отправлена для {message.from_user.id}")

@router.callback_query(lambda c: c.data.startswith("info_"))
async def info_callback(callback: types.CallbackQuery):
    """Обработчик callback-запросов"""
    global message_count
    message_count += 1
    logger.info(f"📩 Callback: {callback.data} от {callback.from_user.id}")
    if callback.from_user.id not in data["admin_ids"]:
        await callback.answer("🚫 Нет доступа!")
        logger.info(f"⛔ Доступ запрещён для callback {callback.data} от {callback.from_user.id}")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 ЦП", callback_data="info_cpu")],
        [InlineKeyboardButton(text="💾 Память", callback_data="info_memory")],
        [InlineKeyboardButton(text="📀 Диск", callback_data="info_disk")],
        [InlineKeyboardButton(text="🛠 Окружение", callback_data="info_system")],
        [InlineKeyboardButton(text="🌐 Сеть", callback_data="info_network")],
        [InlineKeyboardButton(text="📦 Обновления", callback_data="info_updates")],
        [InlineKeyboardButton(text="🤖 Статистика", callback_data="info_botstats")],
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
    elif callback.data == "info_updates":
        info = get_os_updates()
    elif callback.data == "info_botstats":
        info = get_bot_stats()
    elif callback.data == "info_refresh":
        info = "🔄 Данные обновлены!"

    await callback.message.edit_text(info, reply_markup=keyboard)
    await callback.answer()
    logger.info(f"📤 Информация отправлена для {callback.from_user.id}")

async def on_startup(d):
    """Запуск модуля"""
    logger.info("🚀 Модуль InfoSystem запущен.")

async def on_shutdown(d):
    """Остановка модуля"""
    logger.info("📴 Модуль InfoSystem завершает работу.")
