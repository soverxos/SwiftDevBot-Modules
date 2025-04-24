"""
Обработчики команд и сообщений для модуля template_full.

Этот файл содержит все обработчики модуля для различных типов сообщений,
команд и колбэков от инлайн-кнопок.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.utils import get_module_logger
from . import keyboards
from . import utils

# Создаем логгер для модуля
logger = get_module_logger("template_full")


# ============= Обработчики команд =============

async def cmd_example(message: Message):
    """
    Обработчик команды /example.
    Пример обработчика команды модуля.
    """
    # Получаем аргументы команды (если необходимо)
    command_args = message.text.split(maxsplit=1)
    args = command_args[1] if len(command_args) > 1 else "Нет аргументов"
    
    # Получаем клавиатуру
    markup = keyboards.get_example_keyboard()
    
    # Обрабатываем бизнес-логику через утилиты модуля
    result = await utils.process_example_command(message.from_user.id, args)
    
    # Отправляем ответ
    await message.answer(
        f"Это пример команды модуля.\n"
        f"Аргументы: {args}\n"
        f"Результат обработки: {result}",
        reply_markup=markup
    )
    
    # Логируем действие
    logger.info(f"Пользователь {message.from_user.id} использовал команду example с аргументами: {args}")


# ============= Обработчики колбэков =============

async def process_example_callback(callback: CallbackQuery):
    """
    Обработчик колбэков от кнопок модуля.
    """
    callback_data = callback.data
    user_id = callback.from_user.id
    
    if callback_data == "example_button":
        # Обрабатываем нажатие на кнопку
        result = await utils.process_button_click(user_id, "example_button")
        
        # Обновляем сообщение с кнопкой "Назад"
        await callback.message.edit_text(
            f"Вы нажали на кнопку примера!\nРезультат: {result}",
            reply_markup=keyboards.get_back_keyboard()
        )
        logger.info(f"Пользователь {user_id} нажал на кнопку примера")
    
    elif callback_data == "example_back":
        # Возвращаемся к исходному сообщению
        await callback.message.edit_text(
            "Это пример команды модуля.\nАргументы: Нет аргументов\nРезультат обработки: None",
            reply_markup=keyboards.get_example_keyboard()
        )
        logger.info(f"Пользователь {user_id} вернулся назад")
    
    # Завершаем обработку колбэка
    await callback.answer()


def register_handlers(router: Router):
    """
    Регистрирует все обработчики модуля.
    
    Аргументы:
        router: Роутер для регистрации обработчиков
    """
    # Регистрируем обработчики команд
    router.message.register(cmd_example, Command("example"))
    
    # Регистрируем обработчики колбэков
    router.callback_query.register(process_example_callback, F.data.startswith("example_"))
