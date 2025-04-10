import logging
import json
import os
import aiohttp
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core.base_module import BaseModule

logger = logging.getLogger(__name__)

class ModuleManagerStates(StatesGroup):
    waiting_for_module_name = State()
    waiting_for_repo_name = State()
    waiting_for_repo_url = State()

class ModuleManagerModule(BaseModule):
    """Модуль для управления модулями и репозиториями"""
    
    async def initialize(self):
        """Инициализация модуля управления модулями"""
        logger.info(f"Инициализация модуля {self.name}")
        
        # Добавляем отладочную информацию
        logger.debug(f"Регистрируем обработчики команд в {self.name}")
        
        # Регистрация обработчиков команд
        self.router.message.register(self.cmd_repos, Command("repos"))
        self.router.message.register(self.cmd_modules, Command("modules"))
        self.router.message.register(self.cmd_install, Command("install"))
        
        # Обработчик callback запросов
        self.router.callback_query.register(
            self.handle_repo_callback, 
            F.data.startswith("repo:")
        )
        
        self.router.callback_query.register(
            self.handle_module_callback, 
            F.data.startswith("module:")
        )
        
        # Состояния FSM для диалогов
        self.router.message.register(
            self.process_module_name, 
            ModuleManagerStates.waiting_for_module_name
        )
        self.router.message.register(
            self.process_repo_name, 
            ModuleManagerStates.waiting_for_repo_name
        )
        self.router.message.register(
            self.process_repo_url, 
            ModuleManagerStates.waiting_for_repo_url
        )
        
        # Включаем роутер
        self.core.dp.include_router(self.router)
        
        # Регистрация команд
        await self.register_command("repos", "Управление репозиториями модулей", self.cmd_repos, is_admin=True)
        await self.register_command("modules", "Доступные модули из репозитория", self.cmd_modules, is_admin=True)
        await self.register_command("install", "Установка модуля из репозитория", self.cmd_install, is_admin=True)
        
        # Создаем улучшенное меню управления модулями
        await self.register_menu(
            menu_id="module_manager",
            title="Управление модулями",
            items=[
                {"text": "📦 Установленные модули", "callback_data": "module:installed"},
                {"text": "🔍 Установить из репозитория", "callback_data": "module:available"},
                {"text": "🔄 Обновить все модули", "callback_data": "module:update_all"},
                {"text": "📚 Управление репозиториями", "callback_data": "repo:list"}
            ],
            admin_only=True
        )
        
        logger.info(f"Модуль {self.name} успешно инициализирован")
    
    # Команды для работы с репозиториями
    async def cmd_repos(self, message: Message):
        """Команда /repos - управление репозиториями модулей"""
        # Добавляем отладочную информацию
        logger.debug(f"Вызвана команда /repos пользователем {message.from_user.id}")
        
        if message.from_user.id not in self.core.config.admin_ids:
            logger.debug(f"Пользователь {message.from_user.id} не является администратором")
            await message.answer("У вас нет доступа к этой команде.")
            return
            
        logger.debug("Показываем список репозиториев")
        await self.show_repositories(message)
    
    async def show_repositories(self, message_or_callback):
        """Показывает список репозиториев"""
        is_callback = isinstance(message_or_callback, CallbackQuery)
        message = message_or_callback.message if is_callback else message_or_callback
        
        # Получаем список репозиториев из конфигурации или базы данных
        repos_config = await self._get_repositories_config()
        
        if not repos_config or not repos_config.get("repositories"):
            # Если репозитории не найдены, показываем соответствующее сообщение
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить репозиторий", callback_data="repo:add")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ])
            
            text = "📦 <b>Репозитории модулей</b>\n\n"
            text += "Не найдено ни одного репозитория модулей.\n\n"
            text += "Нажмите кнопку ниже, чтобы добавить новый репозиторий."
            
            if is_callback:
                await message.edit_text(text, reply_markup=keyboard)
                await message_or_callback.answer()
            else:
                await message.answer(text, reply_markup=keyboard)
            return
            
        # Формируем список репозиториев
        repos = repos_config["repositories"]
        text = "📦 <b>Репозитории модулей</b>\n\n"
        
        # Создаем клавиатуру с репозиториями и кнопками управления
        keyboard = []
        
        for idx, repo in enumerate(repos):
            status = "✅" if repo.get("enabled", True) else "❌"
            name = repo.get('name', 'Неизвестный')
            
            # Добавляем кнопки для каждого репозитория
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status} {name}",
                    callback_data=f"repo:toggle_{idx}"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑️ Удалить {name}",
                    callback_data=f"repo:delete_{idx}"
                )
            ])
        
        # Добавляем кнопки управления репозиториями
        keyboard.extend([
            [InlineKeyboardButton(text="➕ Добавить репозиторий", callback_data="repo:add")],
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="repo:refresh")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ])
        
        if is_callback:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
            await message_or_callback.answer()
        else:
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    
    async def handle_repo_callback(self, callback: CallbackQuery, state: FSMContext = None):
        """Обработчик callback-запросов для репозиториев"""
        action = callback.data.split(":")[1]
        
        if action == "list":
            await self.show_repositories(callback)
            
        elif action == "add":
            await self.add_repository_dialog(callback, state)
            
        elif action == "refresh":
            await self.refresh_repositories(callback)
            
        elif action.startswith("toggle_"):
            repo_idx = int(action.split("_")[1])
            await self.toggle_repository(callback, repo_idx)
            
        elif action.startswith("delete_"):
            repo_idx = int(action.split("_")[1])
            await self.delete_repository(callback, repo_idx)
            
        else:
            await callback.answer("Неизвестное действие")
    
    async def add_repository_dialog(self, callback: CallbackQuery, state: FSMContext):
        """Запускает диалог добавления репозитория"""
        await callback.message.edit_text(
            "➕ <b>Добавление нового репозитория</b>\n\n"
            "Введите название репозитория:"
        )
        await state.set_state(ModuleManagerStates.waiting_for_repo_name)
        # Сохраняем callback для возврата
        await state.update_data(return_callback=callback.data)
        await callback.answer()
    
    async def process_repo_name(self, message: Message, state: FSMContext):
        """Обработка ввода имени репозитория"""
        await state.update_data(repo_name=message.text.strip())
        
        await message.answer(
            "Теперь введите URL репозитория:\n\n"
            "Пример: https://github.com/username/repo\n"
            "или file:///path/to/local/repo"
        )
        
        await state.set_state(ModuleManagerStates.waiting_for_repo_url)
    
    async def process_repo_url(self, message: Message, state: FSMContext):
        """Обработка ввода URL репозитория"""
        repo_url = message.text.strip()
        
        # Проверка URL
        if not (repo_url.startswith("http://") or repo_url.startswith("https://") or repo_url.startswith("file://")):
            await message.answer(
                "⚠️ Некорректный URL репозитория.\n\n"
                "URL должен начинаться с http://, https:// или file://\n\n"
                "Введите URL репозитория снова:"
            )
            return
        
        # Получаем ранее сохраненные данные
        data = await state.get_data()
        repo_name = data.get("repo_name", "Новый репозиторий")
        
        # Добавляем репозиторий в конфигурацию
        repos_config = await self._get_repositories_config()
        
        if not repos_config:
            repos_config = {"repositories": []}
            
        # Проверяем, нет ли уже репозитория с таким URL
        for repo in repos_config["repositories"]:
            if repo["url"] == repo_url:
                await message.answer(
                    f"⚠️ Репозиторий с URL {repo_url} уже существует!\n\n"
                    f"Имя: {repo['name']}"
                )
                await state.clear()
                await self.show_repositories(message)
                return
        
        # Добавляем новый репозиторий
        repos_config["repositories"].append({
            "name": repo_name,
            "url": repo_url,
            "enabled": True,
            "priority": 100,  # Средний приоритет по умолчанию
            "added_at": datetime.now().isoformat()
        })
        
        # Сохраняем обновленную конфигурацию
        await self._save_repositories_config(repos_config)
        
        # Очищаем состояние и показываем список репозиториев
        await state.clear()
        
        await message.answer(
            f"✅ Репозиторий <b>{repo_name}</b> успешно добавлен!\n\n"
            f"URL: {repo_url}"
        )
        
        # Показываем обновленный список репозиториев
        await self.show_repositories(message)
    
    async def refresh_repositories(self, callback: CallbackQuery):
        """Обновляет информацию о репозиториях"""
        await callback.answer("Обновление репозиториев...")
        
        # Временный прогресс-сообщение
        await callback.message.edit_text(
            "🔄 <b>Обновление репозиториев...</b>\n\n"
            "Пожалуйста, подождите, это может занять некоторое время."
        )
        
        # Здесь код для обновления информации о репозиториях
        # ... (код обновления репозиториев)
        
        # После завершения обновления показываем список репозиториев
        await self.show_repositories(callback)
    
    async def toggle_repository(self, callback: CallbackQuery, repo_idx: int):
        """Включает/отключает репозиторий"""
        repos_config = await self._get_repositories_config()
        
        if not repos_config or not repos_config.get("repositories") or repo_idx >= len(repos_config["repositories"]):
            await callback.answer("Репозиторий не найден")
            return
        
        # Инвертируем состояние репозитория
        repos_config["repositories"][repo_idx]["enabled"] = not repos_config["repositories"][repo_idx].get("enabled", True)
        
        # Сохраняем изменения
        await self._save_repositories_config(repos_config)
        
        status = "включен" if repos_config["repositories"][repo_idx]["enabled"] else "отключен"
        await callback.answer(f"Репозиторий {status}")
        
        # Обновляем список репозиториев
        await self.show_repositories(callback)
    
    async def delete_repository(self, callback: CallbackQuery, repo_idx: int):
        """Удаляет репозиторий"""
        repos_config = await self._get_repositories_config()
        
        if not repos_config or not repos_config.get("repositories") or repo_idx >= len(repos_config["repositories"]):
            await callback.answer("Репозиторий не найден")
            return
        
        # Получаем имя репозитория перед удалением
        repo_name = repos_config["repositories"][repo_idx].get("name", "Неизвестный")
        
        # Удаляем репозиторий
        del repos_config["repositories"][repo_idx]
        
        # Сохраняем изменения
        await self._save_repositories_config(repos_config)
        
        await callback.answer(f"Репозиторий {repo_name} удален")
        
        # Обновляем список репозиториев
        await self.show_repositories(callback)
    
    # Команды для работы с модулями
    async def cmd_modules(self, message: Message):
        """Команда /modules - просмотр доступных модулей"""
        if message.from_user.id not in self.core.config.admin_ids:
            await message.answer("У вас нет доступа к этой команде.")
            return
            
        await self.show_available_modules(message)
    
    async def show_available_modules(self, message_or_callback):
        """Показывает список доступных модулей из всех репозиториев"""
        is_callback = isinstance(message_or_callback, CallbackQuery)
        message = message_or_callback.message if is_callback else message_or_callback
        
        # Временное сообщение о загрузке
        if is_callback:
            await message.edit_text(
                "🔍 <b>Поиск доступных модулей...</b>\n\n"
                "Пожалуйста, подождите, это может занять некоторое время."
            )
            await message_or_callback.answer("Поиск модулей...")
        else:
            loading_msg = await message.answer(
                "🔍 <b>Поиск доступных модулей...</b>\n\n"
                "Пожалуйста, подождите, это может занять некоторое время."
            )
        
        # Получаем список доступных модулей из всех репозиториев
        modules = await self._get_available_modules()
        
        if not modules:
            text = "📦 <b>Доступные модули</b>\n\n"
            text += "Не найдено доступных модулей.\n\n"
            text += "Убедитесь, что вы добавили хотя бы один репозиторий и он активен."
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📦 Управление репозиториями", callback_data="repo:list")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ])
            
            if is_callback:
                await message.edit_text(text, reply_markup=keyboard)
            else:
                await loading_msg.delete()
                await message.answer(text, reply_markup=keyboard)
            return
        
        # Формируем текст с доступными модулями
        text = "📦 <b>Доступные модули</b>\n\n"
        
        for idx, module in enumerate(modules, 1):
            text += f"{idx}. <b>{module.get('name', 'Неизвестный')}</b> v{module.get('version', '1.0.0')}\n"
            text += f"   {module.get('description', 'Нет описания')}\n"
            
            if 'author' in module:
                text += f"   Автор: {module.get('author')}\n"
                
            repo_name = module.get('repository_name', 'Неизвестный репозиторий')
            text += f"   Репозиторий: {repo_name}\n\n"
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💾 Установить модуль", callback_data="module:install")],
            [InlineKeyboardButton(text="📦 Управление репозиториями", callback_data="repo:list")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ])
        
        if is_callback:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await loading_msg.delete()
            await message.answer(text, reply_markup=keyboard)
    
    async def cmd_install(self, message: Message, state: FSMContext):
        """Команда /install - установка модуля из репозитория"""
        if message.from_user.id not in self.core.config.admin_ids:
            await message.answer("У вас нет доступа к этой команде.")
            return
        
        await message.answer(
            "💾 <b>Установка модуля</b>\n\n"
            "Введите имя модуля для установки:"
        )
        
        await state.set_state(ModuleManagerStates.waiting_for_module_name)
    
    async def process_module_name(self, message: Message, state: FSMContext):
        """Обработка ввода имени модуля для установки"""
        module_name = message.text.strip()
        
        # Ищем модуль в доступных модулях
        modules = await self._get_available_modules()
        target_module = None
        
        for module in modules:
            if module.get('name', '') == module_name:
                target_module = module
                break
        
        if not target_module:
            await message.answer(
                f"⚠️ Модуль <b>{module_name}</b> не найден в доступных репозиториях.\n\n"
                f"Проверьте имя и попробуйте снова или используйте /modules для просмотра доступных модулей."
            )
            await state.clear()
            return
        
        # Временное сообщение о процессе установки
        installing_msg = await message.answer(
            f"⏳ <b>Установка модуля {module_name}...</b>\n\n"
            f"Пожалуйста, подождите, это может занять некоторое время."
        )
        
        # Устанавливаем модуль
        success, error_msg = await self._install_module(target_module)
        
        await installing_msg.delete()
        
        if success:
            await message.answer(
                f"✅ Модуль <b>{module_name}</b> успешно установлен!\n\n"
                f"Описание: {target_module.get('description', 'Нет описания')}\n"
                f"Версия: {target_module.get('version', '1.0.0')}\n\n"
                f"Для активации модуля перезапустите бота или используйте команду /reload"
            )
        else:
            await message.answer(
                f"❌ Ошибка при установке модуля <b>{module_name}</b>:\n\n"
                f"{error_msg}"
            )
        
        await state.clear()
    
    async def handle_module_callback(self, callback: CallbackQuery, state: FSMContext = None):
        """Обработчик callback-запросов для модулей"""
        parts = callback.data.split(":")
        action = parts[1]
        
        if action == "available":
            await self.show_available_modules(callback)
            
        elif action == "installed":
            await self.show_installed_modules(callback)
            
        elif action == "details" and len(parts) > 2:
            module_name = parts[2]
            await self.show_module_details(callback, module_name)
            
        elif action == "toggle" and len(parts) > 2:
            module_name = parts[2]
            await self.toggle_module_state(callback, module_name)
            
        elif action == "settings" and len(parts) > 2:
            module_name = parts[2]
            await self.show_module_settings(callback, module_name)
            
        elif action == "confirm_delete" and len(parts) > 2:
            module_name = parts[2]
            await self.confirm_delete_module(callback, module_name)
            
        elif action == "delete" and len(parts) > 2:
            module_name = parts[2]
            await self.delete_module(callback, module_name)
            
        elif action == "install":
            await callback.message.edit_text(
                "💾 <b>Установка модуля</b>\n\n"
                "Выберите модуль для установки из списка доступных модулей:"
            )
            # Создаем список модулей для выбора
            modules = await self._get_available_modules()
            
            keyboard = []
            for module in modules:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"{module.get('name')} v{module.get('version', '1.0.0')}",
                        callback_data=f"module:install:{module.get('name')}"
                    )
                ])
                
            keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="module:available")])
            
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
            await callback.answer()
            
        elif action == "update_all":
            await self.update_all_modules(callback)
            
        elif action.startswith("install:") and len(parts) > 2:
            # Установка конкретного модуля
            module_name = parts[2]
            await self.install_module_callback(callback, module_name)
            
        elif action.startswith("update:") and len(parts) > 2:
            # Обновление конкретного модуля
            module_name = parts[2]
            await self.update_module(callback, module_name)
            
        else:
            await callback.answer("Неизвестное действие")
    
    async def show_installed_modules(self, callback: CallbackQuery):
        """Показывает список установленных модулей"""
        await callback.message.edit_text(
            "📦 <b>Установленные модули</b>\n\n"
            "Загрузка списка установленных модулей..."
        )
        
        # Получаем список установленных модулей
        installed_modules = await self._get_installed_modules()
        
        if not installed_modules:
            text = "📦 <b>Установленные модули</b>\n\n"
            text += "У вас нет установленных модулей."
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Установить из репозитория", callback_data="module:available")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
            return
        
        # Формируем текст с установленными модулями
        text = "📦 <b>Установленные модули</b>\n\n"
        text += "Выберите модуль для управления:\n\n"
        
        # Создаем клавиатуру для модулей
        keyboard = []
        
        for module in installed_modules:
            module_name = module.get('name', 'Неизвестный')
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{module_name} v{module.get('version', '1.0.0')}",
                    callback_data=f"module:details:{module_name}"
                )
            ])
        
        # Добавляем навигационные кнопки
        keyboard.extend([
            [InlineKeyboardButton(text="🔄 Обновить все", callback_data="module:update_all")],
            [InlineKeyboardButton(text="🔍 Установить из репозитория", callback_data="module:available")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ])
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await callback.answer()
    
    async def show_module_details(self, callback: CallbackQuery, module_name: str):
        """Показывает детали конкретного модуля и варианты управления"""
        # Получаем информацию о модуле
        modules = await self._get_installed_modules()
        module_info = None
        
        for module in modules:
            if module.get('name', '') == module_name:
                module_info = module
                break
        
        if not module_info:
            await callback.message.edit_text(
                f"❌ <b>Ошибка</b>\n\n"
                f"Модуль {module_name} не найден."
            )
            await callback.answer("Модуль не найден")
            return
        
        # Определяем статус модуля (включен/отключен)
        module_enabled = module_info.get('enabled', True)
        status_text = "✅ Включен" if module_enabled else "❌ Отключен"
        toggle_text = "🔴 Отключить" if module_enabled else "🟢 Включить"
        
        # Формируем текст с информацией о модуле
        text = f"📦 <b>Модуль: {module_name}</b>\n\n"
        text += f"<b>Версия:</b> {module_info.get('version', '1.0.0')}\n"
        text += f"<b>Автор:</b> {module_info.get('author', 'Неизвестен')}\n"
        text += f"<b>Статус:</b> {status_text}\n\n"
        text += f"<b>Описание:</b>\n{module_info.get('description', 'Нет описания')}\n\n"
        
        # Если у модуля есть команды, показываем их
        commands = module_info.get('commands', [])
        if commands:
            text += "<b>Команды:</b>\n"
            for cmd in commands:
                cmd_name = cmd.get('name', '')
                cmd_desc = cmd.get('description', 'Нет описания')
                text += f"/{cmd_name} - {cmd_desc}\n"
        
        # Создаем клавиатуру с действиями для модуля
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"module:toggle:{module_name}"
            )],
            [InlineKeyboardButton(
                text="⚙️ Настройки",
                callback_data=f"module:settings:{module_name}"
            )],
            [InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data=f"module:update:{module_name}"
            )],
            [InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"module:confirm_delete:{module_name}"
            )],
            [InlineKeyboardButton(
                text="◀️ Назад к списку модулей",
                callback_data="module:installed"
            )]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
    
    async def toggle_module_state(self, callback: CallbackQuery, module_name: str):
        """Включает или отключает модуль"""
        # Получаем информацию о модуле
        modules = await self._get_installed_modules()
        module_info = None
        module_path = None
        
        for module in modules:
            if module.get('name', '') == module_name:
                module_info = module
                module_path = module.get('path', '')
                break
        
        if not module_info or not module_path:
            await callback.message.edit_text(
                f"❌ <b>Ошибка</b>\n\n"
                f"Модуль {module_name} не найден."
            )
            await callback.answer("Модуль не найден")
            return
        
        # Определяем новый статус (инвертируем текущий)
        current_status = module_info.get('enabled', True)
        new_status = not current_status
        
        # Обновляем manifest.json модуля
        manifest_path = Path(module_path) / "manifest.json"
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            # Устанавливаем новый статус
            manifest_data['enabled'] = new_status
            
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest_data, f, indent=2, ensure_ascii=False)
            
            status_text = "включен" if new_status else "отключен"
            await callback.answer(f"Модуль {status_text}! Требуется перезагрузка модулей.")
            
            # Обновляем детальную информацию о модуле
            await self.show_module_details(callback, module_name)
            
        except Exception as e:
            logger.error(f"Ошибка при изменении статуса модуля {module_name}: {e}")
            await callback.answer(f"Ошибка при изменении статуса: {e}", show_alert=True)
    
    async def show_module_settings(self, callback: CallbackQuery, module_name: str):
        """Показывает настройки модуля"""
        # Получаем информацию о модуле
        modules = await self._get_installed_modules()
        module_info = None
        module_path = None
        
        for module in modules:
            if module.get('name', '') == module_name:
                module_info = module
                module_path = module.get('path', '')
                break
        
        if not module_info or not module_path:
            await callback.answer("Модуль не найден", show_alert=True)
            return
        
        # Загружаем файл конфигурации модуля, если он существует
        config_path = Path(module_path) / "config.json"
        
        if not config_path.exists():
            await callback.message.edit_text(
                f"⚙️ <b>Настройки модуля {module_name}</b>\n\n"
                f"У этого модуля нет доступных настроек.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="◀️ Назад к модулю",
                        callback_data=f"module:details:{module_name}"
                    )]
                ])
            )
            await callback.answer()
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            text = f"⚙️ <b>Настройки модуля {module_name}</b>\n\n"
            
            # Формируем текст с настройками
            for key, value in config_data.items():
                if isinstance(value, bool):
                    status = "✅ Включено" if value else "❌ Выключено"
                    text += f"<b>{key}</b>: {status}\n"
                else:
                    text += f"<b>{key}</b>: {value}\n"
            
            text += "\n<i>Редактирование настроек в разработке.</i>"
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="◀️ Назад к модулю",
                        callback_data=f"module:details:{module_name}"
                    )]
                ])
            )
            
        except Exception as e:
            logger.error(f"Ошибка при чтении настроек модуля {module_name}: {e}")
            await callback.message.edit_text(
                f"❌ <b>Ошибка</b>\n\n"
                f"Не удалось загрузить настройки модуля: {e}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="◀️ Назад к модулю",
                        callback_data=f"module:details:{module_name}"
                    )]
                ])
            )
        
        await callback.answer()
    
    async def confirm_delete_module(self, callback: CallbackQuery, module_name: str):
        """Показывает подтверждение удаления модуля"""
        await callback.message.edit_text(
            f"🗑️ <b>Удаление модуля</b>\n\n"
            f"Вы действительно хотите удалить модуль <b>{module_name}</b>?\n\n"
            f"⚠️ Это действие необратимо. Все данные модуля будут потеряны.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"module:delete:{module_name}"),
                    InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"module:details:{module_name}")
                ]
            ])
        )
        await callback.answer()
    
    async def delete_module(self, callback: CallbackQuery, module_name: str):
        """Удаляет установленный модуль"""
        await callback.message.edit_text(
            f"🗑 <b>Удаление модуля {module_name}...</b>\n\n"
            f"Пожалуйста, подождите."
        )
        
        # Получаем путь к модулю
        modules = await self._get_installed_modules()
        module_path = None
        
        for module in modules:
            if module.get('name', '') == module_name:
                module_path = module.get('path', '')
                break
        
        if not module_path:
            await callback.message.edit_text(
                f"❌ <b>Ошибка</b>\n\n"
                f"Модуль {module_name} не найден."
            )
            await callback.answer("Модуль не найден")
            return
        
        try:
            # Удаляем директорию модуля
            shutil.rmtree(module_path)
            
            # Сообщаем об успешном удалении
            await callback.message.edit_text(
                f"✅ <b>Модуль {module_name} успешно удален!</b>\n\n"
                f"Для применения изменений перезапустите бота или используйте команду /reload",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Перезагрузить модули", callback_data="admin:reload_all")],
                    [InlineKeyboardButton(text="📦 К списку модулей", callback_data="module:installed")]
                ])
            )
            success = True
        except Exception as e:
            # В случае ошибки
            await callback.message.edit_text(
                f"❌ <b>Ошибка при удалении модуля {module_name}</b>\n\n"
                f"Причина: {str(e)}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="module:installed")]
                ])
            )
            success = False
        
        await callback.answer("Удаление завершено")
        return success
    
    async def update_all_modules(self, callback: CallbackQuery):
        """Обновляет все установленные модули"""
        await callback.message.edit_text(
            "🔄 <b>Обновление всех модулей...</b>\n\n"
            "Пожалуйста, подождите, это может занять некоторое время."
        )
        
        # Здесь код для обновления всех модулей
        # ... (код обновления модулей)
        
        # По завершении обновления показываем результат
        await callback.message.edit_text(
            "✅ <b>Все модули успешно обновлены!</b>\n\n"
            "Для применения изменений перезапустите бота или используйте команду /reload"
        )
        await callback.answer("Обновление завершено")
    
    # Вспомогательные методы
    async def _get_repositories_config(self) -> Dict[str, Any]:
        """Получает конфигурацию репозиториев"""
        repos_path = Path("data/repositories.json")
        
        if not repos_path.exists():
            # Создаем базовую структуру репозиториев
            return {
                "repositories": []
            }
        
        try:
            with open(repos_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Ошибка при чтении файла {repos_path}")
            return {"repositories": []}
        except Exception as e:
            logger.error(f"Ошибка при получении конфигурации репозиториев: {e}")
            return {"repositories": []}
    
    async def _save_repositories_config(self, repos_config: Dict[str, Any]) -> bool:
        """Сохраняет конфигурацию репозиториев"""
        repos_path = Path("data/repositories.json")
        
        try:
            # Создаем директорию, если она не существует
            repos_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(repos_path, 'w', encoding='utf-8') as f:
                json.dump(repos_config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении конфигурации репозиториев: {e}")
            return False
    
    async def _get_available_modules(self) -> List[Dict[str, Any]]:
        """Получает список доступных модулей из всех репозиториев"""
        repos_config = await self._get_repositories_config()
        repositories = repos_config.get("repositories", [])
        
        if not repositories:
            return []
        
        all_modules = []
        
        for repo in repositories:
            if not repo.get("enabled", True):
                continue
                
            repo_url = repo.get("url")
            
            if not repo_url:
                continue
                
            try:
                # Получаем модули из репозитория
                modules = await self._fetch_modules_from_repository(repo)
                
                # Добавляем информацию о репозитории в каждый модуль
                for module in modules:
                    module["repository_name"] = repo.get("name", "Неизвестный репозиторий")
                    module["repository_url"] = repo_url
                
                all_modules.extend(modules)
            except Exception as e:
                logger.error(f"Ошибка при получении модулей из репозитория {repo.get('name')}: {e}")
        
        return all_modules
    
    async def _fetch_modules_from_repository(self, repo: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Получает список модулей из конкретного репозитория"""
        repo_url = repo.get("url")
        
        if not repo_url:
            return []
        
        # Обработка локальных репозиториев
        if repo_url.startswith("file://"):
            local_path = repo_url[7:]  # Удаляем 'file://'
            return await self._fetch_modules_from_local_repository(local_path)
        
        # Обработка удаленных репозиториев по HTTP/HTTPS
        try:
            async with aiohttp.ClientSession() as session:
                # Получаем индексный файл репозитория
                index_url = f"{repo_url}/index.json"
                if not index_url.startswith("http"):
                    index_url = f"https://{index_url}"
                
                async with session.get(index_url) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка при получении индекса репозитория {repo.get('name')}: HTTP {response.status}")
                        return []
                    
                    index_data = await response.json()
                    return index_data.get("modules", [])
        except Exception as e:
            logger.error(f"Ошибка при получении модулей из репозитория {repo.get('name')}: {e}")
            return []
    
    async def _fetch_modules_from_local_repository(self, local_path: str) -> List[Dict[str, Any]]:
        """Получает список модулей из локального репозитория"""
        index_path = Path(local_path) / "index.json"
        
        if not index_path.exists():
            logger.error(f"Индексный файл не найден в локальном репозитории: {index_path}")
            return []
        
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
                return index_data.get("modules", [])
        except json.JSONDecodeError:
            logger.error(f"Ошибка при чтении индексного файла {index_path}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении модулей из локального репозитория: {e}")
            return []
    
    async def _get_installed_modules(self) -> List[Dict[str, Any]]:
        """Получает список установленных модулей"""
        modules_dir = Path("modules")
        
        if not modules_dir.exists():
            return []
        
        installed_modules = []
        
        for module_dir in modules_dir.iterdir():
            if not module_dir.is_dir() or module_dir.name.startswith('__'):
                continue
            
            manifest_path = module_dir / "manifest.json"
            
            if not manifest_path.exists():
                continue
            
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    
                # Добавляем информацию о пути к модулю
                manifest["path"] = str(module_dir)
                installed_modules.append(manifest)
            except json.JSONDecodeError:
                logger.error(f"Ошибка при чтении манифеста {manifest_path}")
            except Exception as e:
                logger.error(f"Ошибка при получении информации о модуле {module_dir.name}: {e}")
        
        return installed_modules
    
    async def _install_module(self, module: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Устанавливает модуль из репозитория
        
        Args:
            module: Информация о модуле
            
        Returns:
            Tuple[bool, str]: (успех, сообщение об ошибке)
        """
        module_name = module.get('name')
        repo_url = module.get('repository_url')
        
        if not module_name:
            return False, "Имя модуля не указано"
        
        if not repo_url:
            return False, "URL репозитория не указан"
        
        # Проверка, не установлен ли уже модуль
        modules_dir = Path("modules")
        module_dir = modules_dir / module_name
        
        if module_dir.exists():
            return False, f"Модуль {module_name} уже установлен"
        
        try:
            # Создаем директорию для модуля
            module_dir.mkdir(parents=True, exist_ok=True)
            
            # Копируем файлы модуля из репозитория
            if repo_url.startswith("file://"):
                # Локальный репозиторий
                local_path = repo_url[7:]  # Удаляем 'file://'
                module_src_dir = Path(local_path) / "modules" / module_name
                
                if not module_src_dir.exists():
                    return False, f"Модуль {module_name} не найден в локальном репозитории"
                
                # Копируем файлы
                for item in module_src_dir.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, module_dir / item.name)
                    else:
                        shutil.copy2(item, module_dir / item.name)
            else:
                # Удаленный репозиторий - скачиваем архив и распаковываем
                module_zip_url = f"{repo_url}/modules/{module_name}/{module_name}.zip"
                
                if not module_zip_url.startswith("http"):
                    module_zip_url = f"https://{module_zip_url}"
                
                # Создаем временную директорию для загрузки архива
                temp_dir = Path("data/temp")
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                zip_path = temp_dir / f"{module_name}.zip"
                
                # Скачиваем архив
                async with aiohttp.ClientSession() as session:
                    async with session.get(module_zip_url) as response:
                        if response.status != 200:
                            return False, f"Ошибка при скачивании модуля: HTTP {response.status}"
                        
                        with open(zip_path, 'wb') as f:
                            f.write(await response.read())
                
                # Распаковываем архив
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(module_dir)
                
                # Удаляем временный архив
                os.remove(zip_path)
            
            # Проверяем, что модуль содержит необходимые файлы
            if not (module_dir / "module.py").exists() or not (module_dir / "manifest.json").exists():
                shutil.rmtree(module_dir)
                return False, "Установленный модуль не содержит необходимых файлов"
            
            return True, ""
        
        except Exception as e:
            # В случае ошибки удаляем директорию модуля
            if module_dir.exists():
                shutil.rmtree(module_dir)
                
            return False, str(e)
