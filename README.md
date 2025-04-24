# Руководство по созданию модулей для SwiftDevBot

## Содержание
1. [Введение](#введение)
2. [Структура модуля](#структура-модуля)
3. [Manifest.json](#manifestjson)
4. [Разработка модуля](#разработка-модуля)
   - [Простой модуль](#простой-модуль)
   - [Расширенный модуль](#расширенный-модуль)
5. [Жизненный цикл модуля](#жизненный-цикл-модуля)
6. [Взаимодействие с пользователем](#взаимодействие-с-пользователем)
7. [Работа с данными модуля](#работа-с-данными-модуля)
8. [Шаблоны модулей](#шаблоны-модулей)
9. [Лучшие практики](#лучшие-практики)

## Введение

SwiftDevBot построен на модульной архитектуре, что позволяет легко расширять его функциональность без изменения основного кода. Модули являются независимыми компонентами, которые могут быть включены или отключены администратором бота.ф

Этот документ поможет вам разработать свои собственные модули, используя предоставленные шаблоны и API.

## Структура модуля

Типичная структура модуля выглядит следующим образом:

```
modules/my_module/              # Директория модуля
├── __init__.py                 # Точка входа модуля
├── manifest.json               # Метаданные модуля
├── handlers.py                 # Обработчики команд и сообщений (опционально)
├── keyboards.py                # Клавиатуры и кнопки (опционально)
├── utils.py                    # Вспомогательные функции (опционально)
└── requirements.txt            # Зависимости модуля (опционально)
```

В зависимости от сложности модуля, вы можете использовать один файл `__init__.py` для небольших модулей или разделить код на несколько файлов для более сложных.

## Manifest.json

Файл `manifest.json` содержит метаданные о модуле и является обязательным. Он помогает системе идентифицировать, загружать и управлять модулем.

```json
{
    "name": "my_module",
    "version": "1.0.0",
    "description": "Описание вашего модуля",
    "author": "Ваше имя",
    "entry_point": "__init__.py",
    "commands": [
        {
            "command": "mycommand",
            "description": "Описание команды",
            "roles": ["user", "admin"]
        }
    ],
    "permissions": ["basic_commands"],
    "dependencies": [],
    "settings": {
        "example_setting": "default_value"
    }
}
```

### Поля manifest.json:

- **name**: Уникальное имя модуля
- **version**: Версия модуля
- **description**: Описание функциональности модуля
- **author**: Имя автора или команды
- **entry_point**: Файл, который является точкой входа в модуль
- **commands**: Список команд, предоставляемых модулем
  - **command**: Название команды без слеша (например, `mycommand` для команды `/mycommand`)
  - **description**: Описание команды (отображается в меню команд)
  - **roles**: Роли пользователей, которым доступна команда (`user`, `admin` и т.д.)
- **permissions**: Набор разрешений, необходимых модулю
- **dependencies**: Зависимости от других модулей
- **settings**: Настройки модуля по умолчанию

## Разработка модуля

### Простой модуль

Для простых модулей достаточно создать директорию с двумя файлами: `manifest.json` и `__init__.py`.

Пример `__init__.py` для простого модуля:

```python
"""
Мой простой модуль для SwiftDevBot.
"""
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.utils import get_module_logger

# Создаем логгер для модуля
logger = get_module_logger("my_module")


async def cmd_mycommand(message: Message):
    """Обработчик команды /mycommand"""
    await message.answer("Привет от моего модуля!")
    logger.info(f"Пользователь {message.from_user.id} использовал команду mycommand")


async def setup(bot: Bot, dp: Dispatcher, router: Router):
    """Настраивает модуль при загрузке"""
    router.message.register(cmd_mycommand, Command("mycommand"))
    logger.info("Модуль my_module успешно загружен")


async def cleanup():
    """Выполняет очистку при выгрузке модуля"""
    logger.info("Модуль my_module выгружается")
```

### Расширенный модуль

Для более сложных модулей рекомендуется разделять код на несколько файлов:

#### __init__.py
```python
"""
Точка входа для модуля.
"""
from aiogram import Bot, Dispatcher, Router

from app.utils import get_module_logger
from . import handlers
from . import utils

# Создаем логгер для модуля
logger = get_module_logger("my_module")


async def setup(bot: Bot, dp: Dispatcher, router: Router):
    """Настраивает модуль при загрузке"""
    await utils.init_module_data()
    handlers.register_handlers(router)
    logger.info("Модуль my_module успешно загружен")


async def cleanup():
    """Выполняет очистку при выгрузке модуля"""
    await utils.save_module_data()
    logger.info("Модуль my_module выгружается")
```

#### handlers.py
```python
"""
Обработчики команд и сообщений модуля.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.utils import get_module_logger
from . import keyboards
from . import utils

# Создаем логгер для модуля
logger = get_module_logger("my_module")


async def cmd_mycommand(message: Message):
    """Обработчик команды /mycommand"""
    markup = keyboards.get_main_keyboard()
    result = await utils.process_command(message.from_user.id)
    await message.answer(f"Привет от моего модуля! Результат: {result}", reply_markup=markup)
    logger.info(f"Пользователь {message.from_user.id} использовал команду mycommand")


async def callback_handler(callback: CallbackQuery):
    """Обработчик колбэков от кнопок"""
    await callback.answer()
    # Ваша логика обработки колбэков


def register_handlers(router: Router):
    """Регистрирует все обработчики модуля"""
    router.message.register(cmd_mycommand, Command("mycommand"))
    router.callback_query.register(callback_handler, F.data.startswith("my_module_"))
```

## Жизненный цикл модуля

Каждый модуль имеет два основных метода жизненного цикла:

1. **setup(bot, dp, router)** - вызывается при загрузке модуля
   - Здесь вы регистрируете обработчики команд и сообщений
   - Инициализируете данные модуля
   - Подготавливаете все необходимые ресурсы

2. **cleanup()** - вызывается при выгрузке модуля
   - Здесь вы освобождаете ресурсы
   - Сохраняете данные модуля
   - Выполняете другие действия по очистке

## Взаимодействие с пользователем

### Команды

Команды — основной способ взаимодействия пользователя с модулем. Они регистрируются в файле `manifest.json` и обрабатываются в функциях модуля.

Пример регистрации обработчика команды:
```python
router.message.register(cmd_mycommand, Command("mycommand"))
```

### Инлайн-клавиатуры

Инлайн-клавиатуры позволяют создавать кнопки в сообщениях:

```python
from aiogram.utils.keyboard import InlineKeyboardBuilder

keyboard = InlineKeyboardBuilder()
keyboard.button(text="Моя кнопка", callback_data="my_module_button")
keyboard.adjust(1)  # Кнопки в один столбец

await message.answer("Текст сообщения", reply_markup=keyboard.as_markup())
```

Для обработки нажатий на кнопки используйте обработчик колбэков:

```python
router.callback_query.register(callback_handler, F.data.startswith("my_module_"))
```

## Работа с данными модуля

### Временные данные

Для хранения временных данных модуля (в оперативной памяти):

```python
# Глобальные переменные модуля
module_data = {}

# В функции setup()
module_data["counter"] = 0

# Использование данных
module_data["counter"] += 1
```

### Постоянные данные

Для сохранения данных между перезапусками бота, вы можете использовать файловую систему или базу данных:

```python
import json
import os

data_file = os.path.join(os.path.dirname(__file__), "data.json")

# Загрузка данных
async def load_data():
    if os.path.exists(data_file):
        with open(data_file, "r") as f:
            return json.load(f)
    return {}

# Сохранение данных
async def save_data(data):
    with open(data_file, "w") as f:
        json.dump(data, f)
```

## Шаблоны модулей

SwiftDevBot предоставляет два готовых шаблона модулей, которые вы можете использовать:

### 1. Простой шаблон (`template`)

Для небольших модулей, где вся логика размещается в одном файле. 

Использование:
```bash
cp -r modules/template/ modules/my_module/
```

### 2. Расширенный шаблон (`template_full`)

Для более сложных модулей с разделением кода на несколько файлов.

Использование:
```bash
cp -r modules/template_full/ modules/my_module/
```

После копирования шаблона не забудьте:
1. Изменить название модуля в `manifest.json`
2. Обновить имя логгера во всех файлах (`logger = get_module_logger("my_module")`)
3. Заменить примеры на свой код

## Лучшие практики

1. **Разделяйте ответственность**: Обработчики должны заниматься только обработкой сообщений, а бизнес-логику лучше вынести в отдельные функции.

2. **Используйте логгер**: Записывайте важные события и действия в лог для облегчения отладки.
   ```python
   logger.info("Событие произошло")
   logger.error("Произошла ошибка", exc_info=True)
   ```

3. **Обрабатывайте исключения**: Не позволяйте ошибкам в вашем модуле влиять на работу всего бота.
   ```python
   try:
       # Ваш код
   except Exception as e:
       logger.error(f"Ошибка при обработке: {e}", exc_info=True)
       await message.answer("Произошла ошибка при обработке команды")
   ```

4. **Правильно именуйте колбэки**: Используйте префикс с названием вашего модуля для колбэков:
   ```python
   callback_data=f"my_module_action"
   ```

5. **Инициализируйте данные модуля**: Всегда инициализируйте данные при загрузке модуля, чтобы обеспечить их доступность.

6. **Документируйте свой код**: Добавляйте докстринги и комментарии для лучшего понимания кода.

---

Удачи в создании ваших модулей для SwiftDevBot!
