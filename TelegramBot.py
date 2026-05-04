import os
import logging
import aiohttp
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

OPEN_LIBRARY_API_URL = "http://openlibrary.org/search.json"

# Хранилище для результатов поиска
user_searches = {}


class OpenLibraryAPI:
    @staticmethod
    async def search_books(query: str, limit: int = 20):
        params = {
            'q': query,
            'limit': limit,
            'fields': 'key,title,author_name,first_publish_year,cover_i,edition_count'
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(OPEN_LIBRARY_API_URL, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('docs', [])
                    else:
                        logger.error(f"API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error: {e}")
            return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Главное меню с кнопками
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск книг", callback_data="search_menu")],
        [InlineKeyboardButton("📖 Популярное", callback_data="popular")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "📚 *OpenLibBot готов к работе!*\n\n"
        "Нажмите на кнопку «Поиск книг» внизу или просто напишите название книги/автора 👇\n\n"
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)


async def search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Меню поиска
    keyboard = [
        [InlineKeyboardButton("✍️ Написать запрос", callback_data="type_query")],
        [InlineKeyboardButton("🎲 Случайная книга", callback_data="random")],
        [InlineKeyboardButton("⭐ Классика", callback_data="classics")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🔍 *Режим поиска*\n\nОтправь мне название книги или имя автора, и я найду нужное!"

    await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)
    await update.callback_query.answer()


async def type_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Подсказка для ввода запроса
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "✍️ *Введите ваш запрос:*\n\n"
        "Например: `Достоевский` или `Война и мир`",
        parse_mode='Markdown'
    )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработка поискового запроса
    # Определяем откуда пришёл запрос
    if update.callback_query:
        query_text = update.callback_query.data.replace('quick_search_', '')
        chat_id = update.callback_query.message.chat_id
        message = update.callback_query.message
        await update.callback_query.answer()
    else:
        query_text = update.message.text.strip()
        chat_id = update.message.chat_id
        message = update.message

    # Проверка на пустой запрос
    if not query_text or query_text.startswith('/'):
        return

    # Отправляем сообщение о начале поиска
    status_message = await message.reply_text(
        f"🔍 *Ищу:* «{query_text}»\n\n_Пожалуйста, подождите..._",
        parse_mode='Markdown'
    )

    try:
        books = await OpenLibraryAPI.search_books(query_text, limit=20)

        if not books:
            await status_message.edit_text(
                f"📚 По запросу «{query_text}» ничего не найдено.\n\n"
                f"Попробуйте изменить запрос или проверьте орфографию.",
                parse_mode='Markdown'
            )
            return

        # Сохраняем результаты
        user_id = update.effective_user.id
        user_searches[user_id] = {
            'books': books,
            'query': query_text,
            'page': 0,
            'chat_id': chat_id,
            'message_id': status_message.message_id
        }

        # Показываем первую страницу
        await show_results_page(update, context, user_id, status_message)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await status_message.edit_text(
            "❌ *Произошла ошибка*\n\nПожалуйста, попробуйте позже.",
            parse_mode='Markdown'
        )


async def show_results_page(update, context, user_id, message_to_edit=None):
    # Показать страницу результатов
    data = user_searches.get(user_id)
    if not data:
        return

    books = data['books']
    query = data['query']
    page = data['page']
    books_per_page = 5

    start_idx = page * books_per_page
    end_idx = start_idx + books_per_page
    page_books = books[start_idx:end_idx]
    total_pages = (len(books) + books_per_page - 1) // books_per_page

    # Форматируем результаты
    result_text = f"📖 *Результаты поиска:* «{query}»\n\n"
    for i, book in enumerate(page_books, start_idx + 1):
        title = book.get('title', ['Без названия'])
        if isinstance(title, list):
            title = title[0] if title else 'Без названия'

        authors = book.get('author_name', ['Автор не указан'])
        if isinstance(authors, list):
            author = ', '.join(authors[:2])
        else:
            author = str(authors)

        year = book.get('first_publish_year', ['Год не указан'])
        if isinstance(year, list):
            year = year[0] if year else 'Год не указан'

        editions = book.get('edition_count', 0)

        result_text += f"{i}. *{title[:45]}*\n"
        result_text += f"   👤 {author}\n"
        result_text += f"   📅 {year} | 📚 {editions} изданий\n\n"

    result_text += f"_{start_idx + 1}-{min(end_idx, len(books))} из {len(books)} книг_"

    # Создаём кнопки навигации
    keyboard = []
    nav_buttons = []

    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if message_to_edit:
        await message_to_edit.edit_text(result_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(result_text, parse_mode='Markdown', reply_markup=reply_markup)
        await update.callback_query.answer()


async def change_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Смена страницы
    query = update.callback_query
    user_id = update.effective_user.id
    page_num = int(query.data.split('_')[1])

    if user_id in user_searches:
        user_searches[user_id]['page'] = page_num
        await show_results_page(update, context, user_id)


async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Популярные книги
    await update.callback_query.answer()

    popular_queries = ["Гарри Поттер", "Война и мир", "Преступление и наказание", "Мастер и Маргарита", "1984"]

    keyboard = []
    for book in popular_queries:
        keyboard.append([InlineKeyboardButton(f"📚 {book}", callback_data=f"quick_search_{book}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.message.edit_text(
        "⭐ *Популярные запросы:*\n\nВыберите книгу для поиска:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def show_classics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Классические авторы
    await update.callback_query.answer()

    classics = [
        "Лев Толстой", "Фёдор Достоевский", "Александр Пушкин",
        "Михаил Булгаков", "Антон Чехов", "Николай Гоголь"
    ]

    keyboard = []
    for author in classics:
        keyboard.append([InlineKeyboardButton(f"👤 {author}", callback_data=f"quick_search_{author}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.message.edit_text(
        "📖 *Классическая литература:*\n\nВыберите автора для поиска:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Быстрый поиск
    query = update.callback_query.data.replace('quick_search_', '')
    await handle_search(update, context)


async def new_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Новый поиск
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "✍️ *Введите ваш запрос:*\n\nНапример: `Достоевский` или `Война и мир`",
        parse_mode='Markdown'
    )


async def show_random_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Случайная книга
    await update.callback_query.answer()
    await update.callback_query.message.edit_text(
        "🎲 *Генерирую случайную книгу...*\n\n_Пожалуйста, подождите..._",
        parse_mode='Markdown'
    )

    random_queries = ["love", "war", "peace", "life", "death", "happy", "sad"]
    random_query = random.choice(random_queries)

    books = await OpenLibraryAPI.search_books(random_query, limit=50)

    if books:
        random_book = random.choice(books)
        title = random_book.get('title', ['Без названия'])
        if isinstance(title, list):
            title = title[0] if title else 'Без названия'
        authors = random_book.get('author_name', ['Автор не указан'])
        if isinstance(authors, list):
            author = authors[0] if authors else 'Автор не указан'
        else:
            author = str(authors)
        year = random_book.get('first_publish_year', ['Год не указан'])
        if isinstance(year, list):
            year = year[0] if year else 'Год не указан'

        keyboard = [
            [InlineKeyboardButton("🔄 Другая книга", callback_data="random")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.message.edit_text(
            f"🎲 *Случайная книга*\n\n"
            f"*Название:* {title}\n"
            f"*Автор:* {author}\n"
            f"*Год:* {year}",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.message.edit_text(
            "❌ Не удалось найти случайную книгу. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]])
        )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Помощь
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = (
        "❓ *Помощь*\n\n"
        "*Как пользоваться ботом:*\n\n"
        "1️⃣ *Поиск по названию*\n"
        "   Просто напиши название книги\n"
        "   Пример: `Война и мир`\n\n"
        "2️⃣ *Поиск по автору*\n"
        "   Напиши имя автора\n"
        "   Пример: `Достоевский`\n\n"
        "3️⃣ *Кнопки*\n"
        "   • «Назад/Вперёд» — листать результаты\n"
        "   • «Новый поиск» — начать заново\n"
        "   • «Главное меню» — вернуться в начало\n\n"
        "4️⃣ *Команды*\n"
        "   • `/start` — главное меню\n"
        "   • `/help` — эта справка"
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)


async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # О боте
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    about_text = (
        "ℹ️ *О боте*\n\n"
        "*OpenLibBot* — Telegram-бот для поиска книг.\n\n"
        "*Технологии:*\n"
        "• Python + python-telegram-bot\n"
        "• Open Library API\n\n"
        "*Возможности:*\n"
        "• Поиск по названию и автору\n"
        "• Популярные запросы\n"
        "• Случайная книга\n\n"
        "*Данные:* openlibrary.org"
    )

    await update.callback_query.message.edit_text(about_text, parse_mode='Markdown', reply_markup=reply_markup)
    await update.callback_query.answer()


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработка текстового ввода
    text = update.message.text.strip()
    if text.startswith('/'):
        return
    await handle_search(update, context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработчик кнопок
    query = update.callback_query
    data = query.data

    if data == "back_to_menu":
        await start(update, context)
    elif data == "search_menu":
        await search_menu(update, context)
    elif data == "type_query":
        await type_query(update, context)
    elif data == "help":
        await show_help(update, context)
    elif data == "about":
        await show_about(update, context)
    elif data == "popular":
        await show_popular(update, context)
    elif data == "classics":
        await show_classics(update, context)
    elif data == "random":
        await show_random_book(update, context)
    elif data == "new_search":
        await new_search(update, context)
    elif data.startswith("page_"):
        await change_page(update, context)
    elif data.startswith("quick_search_"):
        await quick_search(update, context)
    else:
        await query.answer()


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработчик ошибок
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ *Произошла ошибка*\n\nПопробуйте позже.",
                parse_mode='Markdown'
            )
        except:
            pass


def main():
    # Запуск бота
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", show_help))

    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))

    # Обработка текста (поиск)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    print("✅ Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
