"""
Клавиатуры для модуля template_full.

Этот файл содержит функции для создания всех клавиатур и кнопок, 
используемых в модуле.
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_example_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с примером кнопки.
    
    Возвращает:
        InlineKeyboardMarkup: Инлайн-клавиатура
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Пример кнопки", callback_data="example_button")
    keyboard.adjust(1)  # Кнопки в один столбец
    
    return keyboard.as_markup()


def get_back_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопкой "Назад".
    
    Возвращает:
        InlineKeyboardMarkup: Инлайн-клавиатура
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="◀️ Назад", callback_data="example_back")
    
    return keyboard.as_markup()


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с настройками модуля.
    
    Возвращает:
        InlineKeyboardMarkup: Инлайн-клавиатура
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⚙️ Настройка 1", callback_data="example_setting_1")
    keyboard.button(text="🔧 Настройка 2", callback_data="example_setting_2")
    keyboard.button(text="◀️ Назад", callback_data="example_back")
    keyboard.adjust(1)  # Кнопки в один столбец
    
    return keyboard.as_markup()
