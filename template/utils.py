"""
Утилиты для модуля template_full.

Этот файл содержит вспомогательные функции и логику работы модуля,
отделенную от обработчиков сообщений и команд.
"""
from app.utils import get_module_logger
from app.services.user import is_user_admin
from typing import Dict, Any, Optional

# Создаем логгер для модуля
logger = get_module_logger("template_full")

# Глобальные переменные модуля
module_data = {}


async def init_module_data():
    """
    Инициализирует данные модуля при загрузке.
    Загружает сохраненные данные или создает структуру по умолчанию.
    """
    # Инициализация данных по умолчанию
    module_data["example_key"] = "example_value"
    module_data["counter"] = 0
    
    # Здесь может быть код для загрузки данных из файла или БД
    
    logger.info("Данные модуля инициализированы")


async def save_module_data():
    """
    Сохраняет данные модуля при выгрузке.
    """
    # Здесь может быть код для сохранения данных в файл или БД
    
    logger.info("Данные модуля сохранены")


async def process_example_command(user_id: int, args: str) -> Dict[str, Any]:
    """
    Обрабатывает логику команды example.
    
    Аргументы:
        user_id: ID пользователя в Telegram
        args: Аргументы команды
        
    Возвращает:
        Dict[str, Any]: Результат обработки команды
    """
    # Увеличиваем счетчик использований
    module_data["counter"] = module_data.get("counter", 0) + 1
    
    # Проверка прав доступа (если необходимо)
    is_admin = await is_user_admin(user_id)
    
    # Пример обработки бизнес-логики
    result = {
        "user_id": user_id,
        "args": args,
        "is_admin": is_admin,
        "counter": module_data["counter"]
    }
    
    logger.debug(f"Обработана команда example: {result}")
    return result


async def process_button_click(user_id: int, button_id: str) -> str:
    """
    Обрабатывает нажатие на кнопку.
    
    Аргументы:
        user_id: ID пользователя в Telegram
        button_id: Идентификатор нажатой кнопки
        
    Возвращает:
        str: Результат обработки нажатия
    """
    # Пример обработки нажатия кнопки
    if button_id == "example_button":
        # Увеличиваем счетчик нажатий
        button_counter = module_data.get("button_counter", 0) + 1
        module_data["button_counter"] = button_counter
        
        return f"Кнопка нажата {button_counter} раз(а)"
    
    return "Неизвестная кнопка"
