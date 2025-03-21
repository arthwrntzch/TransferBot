import logging
import telebot
import gspread
import random
import string
import sqlite3
import datetime
import re
from oauth2client.service_account import ServiceAccountCredentials
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telebot import types

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = "8092395793:AAF2lbSS2bnn0oAeEiqizG0t30zdbRIiv8w"
bot = telebot.TeleBot(TOKEN)

# Подключение к Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS_FILE = "andreytelegrambot-f11896416c4f.json"
SPREADSHEET_ID = "16T0XpPEOrOTzTNd8lZKIEH4HrLMxhbO32_47qGrnmGc"

creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# Тарифы
tariffs = {
    "standard": "Стандарт 5500₽ (3 пассажира)",
    "comfort": "Комфорт 6500₽ (4 пассажира)",
    "crossover": "Кроссовер 7500₽ (4 пассажира)",
    "business": "Бизнес 8500₽ (4 пассажира)",
    "minivan": "Минивэн 9000₽ (7 пассажиров), 10000₽ (8 пассажиров)"
}

# Опции
platka_options = ["Да", "Нет"]
chair_options = ["Да", "Нет"]

# Данные пользователей
user_data = {}

# Администратор
ADMIN_PASSWORD = "admin123"  # Пароль для входа в режим администратора
admin_chat_id = None  # ID чата администратора

# Список популярных адресов
popular_addresses = [
    "Шереметьево (аэропорт)",
    "Домодедово (аэропорт)",
    "Внуково (аэропорт)",
    "Жуковский (аэропорт)",
    "Казанский вокзал (вокзал)",
    "Ленинградский вокзал (вокзал)",
    "Ярославский вокзал (вокзал)",
    "Киевский вокзал (вокзал)",
    "Павелецкий вокзал (вокзал)",
    "Курский вокзал (вокзал)",
    "Белорусский вокзал (вокзал)",
    "Рижский вокзал (вокзал)",
    "Савеловский вокзал (вокзал)"
]


##############################################
# Блок вспомогательных функций и БД
##############################################

def init_db():
    """Инициализация базы данных SQLite"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()

    # Создаем таблицу, если она не существует
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_orders (
            user_id INTEGER,
            order_id TEXT,
            chat_id INTEGER,
            PRIMARY KEY (user_id, order_id)
        )
    ''')

    # Проверяем, существует ли столбец chat_id
    cursor.execute("PRAGMA table_info(user_orders)")
    columns = cursor.fetchall()
    column_names = [column[1] for column in columns]

    if 'chat_id' not in column_names:
        # Добавляем столбец chat_id, если его нет
        cursor.execute('ALTER TABLE user_orders ADD COLUMN chat_id INTEGER')

    conn.commit()
    conn.close()


def add_order_to_db(user_id, order_id, chat_id):
    """Добавляет номер заявки в базу данных для конкретного пользователя"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO user_orders (user_id, order_id, chat_id) VALUES (?, ?, ?)',
                   (user_id, order_id, chat_id))
    conn.commit()
    conn.close()


def get_chat_id_by_order_id(order_id):
    """Возвращает chat_id по номеру заявки"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM user_orders WHERE order_id = ?', (order_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def get_user_orders(user_id):
    """Возвращает все номера заявок для конкретного пользователя"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT order_id FROM user_orders WHERE user_id = ?', (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return [order[0] for order in orders]


def delete_order_from_db(user_id, order_id):
    """Удаляет номер заявки из базы данных для конкретного пользователя"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_orders WHERE user_id = ? AND order_id = ?',
                   (user_id, order_id))
    conn.commit()
    conn.close()


init_db()


def generate_order_number():
    """Генерирует уникальный номер заявки"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def send_to_google_sheets(chat_id, username, data):
    """
    Отправляет данные заявки в Google Sheets, соблюдая порядок столбцов:
    1) Номер заявки (data[15])
    2) Водитель (пока пусто)
    3) Заказчик (@username или телефон)
    4) Вылет/Прилет (data[0])
    5) Дата (data[1])
    6) Подача в (data[3])
    7) Время рейса (data[2])
    8) Номер рейса (data[4])
    9) Адрес Отпр (data[5])
    10) Адрес Приб (data[6])
    11) Колво Пасс (data[7])
    12) Колво детей (data[8])
    13) ФИО (data[10])
    14) Телефон (data[11])
    15) Откуда узнали (data[12])
    16) Тариф (data[13])
    17) Платка (data[14])
    18) Кресло (data[9])
    """
    if len(data) < 16:
        bot.send_message(chat_id, "Ошибка: Недостаточно данных для сохранения в таблицу.")
        return

    application_number = data[15]  # Номер заявки
    user_contact = f"@{username}" if username else (data[11] if data[11] else "-")

    new_row = [
        application_number,  # Номер заявки
        "",                 # Водитель (пока пусто)
        user_contact,       # Заказчик
        data[0],            # Вылет/Прилет
        data[1],            # Дата
        data[3],            # Подача в
        data[2],            # Время рейса
        data[4],            # Номер рейса
        data[5],            # Адрес отправления
        data[6],            # Адрес прибытия
        data[7],            # Кол-во пассажиров
        data[8],            # Кол-во детей
        data[10],           # ФИО
        data[11],           # Телефон
        data[12],           # Откуда узнали
        data[13],           # Тариф
        data[14],           # Платка
        data[9]             # Кресло
    ]
    sheet.append_row(new_row)

    # Уведомление администратора о новой заявке
    if admin_chat_id:
        bot.send_message(admin_chat_id,
                         f"📝 Новая заявка №{application_number} от @{username}")

def update_google_sheets(order_id, data):
    """
    Обновляет заявку в Google Sheets в соответствии с порядком столбцов (A-R).
    Предполагается, что data хранит поля в том же порядке, что и при вставке.
    """
    orders = sheet.get_all_values()
    order_index = next((index for index, order in enumerate(orders) if order[0] == order_id), None)

    if order_index is None:
        return False  # Заявка не найдена

    updated_row = [
        order_id,                  # A Номер заявки
        orders[order_index][1],    # B Водитель (без изменения)
        orders[order_index][2],    # C Заказчик (без изменения)
        data[1],                   # D Вылет/Прилет
        data[0],                   # E Дата
        data[3],                   # F Подача
        data[2],                   # G Время рейса
        data[4],                   # H Рейс
        data[5],                   # I Адрес Отпр
        data[6],                   # J Адрес Приб
        data[7],                   # K Кол-во Пасс
        data[8],                   # L Кол-во детей
        data[9],                   # M ФИО
        data[10],                  # N Телефон
        data[11],                  # O Откуда узнали
        data[12],                  # P Тариф
        data[13],                  # Q Платка
        data[14]                   # R Кресло
    ]

    sheet.update(f"A{order_index + 1}:R{order_index + 1}", [updated_row])

    # Уведомление администратора об изменении заявки
    if admin_chat_id:
        bot.send_message(admin_chat_id,
                         f"📝 Заявка №{order_id} была изменена.")
    return True

@bot.callback_query_handler(func=lambda call: call.data.startswith("generate_message_"))
def generate_message_for_admin(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    orders = sheet.get_all_values()
    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(chat_id, "❌ Ошибка: Заявка не найдена.")
        return

    driver_username = order[1]
    driver_username_clean = driver_username.lstrip('@')

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE username = ?', (driver_username_clean,))
    driver = cursor.fetchone()
    conn.close()

    if not driver:
        bot.send_message(chat_id, f"❌ Ошибка: Данные водителя {driver_username} не найдены.")
        return

    admin_message = (
        f"Добрый день, {order[4]} в {order[5]} по адресу {order[8]} Вас будет ожидать "
        f"{driver[4]} {driver[6]}, {driver[5]}, водитель {driver[3]} {driver[2]}."
    )

    bot.send_message(chat_id, admin_message)



##############################################
# ADDED: Inline “Cancel” button creation
##############################################
def get_cancel_markup(callback_data="cancel_application"):
    """
    Returns an InlineKeyboardMarkup with a single button:
    ❌ Отмена заполнения заявки
    """
    markup = InlineKeyboardMarkup()
    cancel_btn = InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data=callback_data)
    markup.add(cancel_btn)
    return markup


##############################################
# ADDED: Callback to handle “Cancel” presses
##############################################
@bot.callback_query_handler(func=lambda c: c.data == "cancel_application")
def cancel_application_callback(c):
    chat_id = c.message.chat.id
    # Clear any stored data for this user
    if chat_id in user_data:
        del user_data[chat_id]
    # Terminate any step-handler
    bot.clear_step_handler_by_chat_id(chat_id)

    bot.answer_callback_query(c.id, "Заполнение заявки отменено.")
    bot.send_message(chat_id, "❌ Вы отменили заполнение заявки. Если захотите начать заново, введите /start.")


##############################################
# Команды /start и /admin
##############################################

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)  # Сброс step-хендлера
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    create_order_button = KeyboardButton("Создать заявку")
    my_orders_button = KeyboardButton("Мои заявки")
    tariffs_button = KeyboardButton("Стоимость услуг")
    driver_button = KeyboardButton("🚖 Для водителей")
    markup.add(create_order_button, my_orders_button, tariffs_button, driver_button)
    bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)


@bot.message_handler(commands=['admin'])
def admin_login(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)  # Сброс step-хендлера
    bot.send_message(chat_id, "Введите пароль для входа в режим администратора:")
    bot.register_next_step_handler(message, check_admin_password)


def check_admin_password(message):
    global admin_chat_id
    if message.text == ADMIN_PASSWORD:
        admin_chat_id = message.chat.id
        bot.send_message(message.chat.id, "✅ Вы вошли как администратор.")
        show_admin_menu(message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Неверный пароль.")


def show_admin_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    all_orders_button = KeyboardButton("Все заявки")
    all_drivers_button = KeyboardButton("Все водители")
    markup.add(all_orders_button, all_drivers_button)
    bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)

def admin_confirm_order(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    if set_cell_color(order_id, {"red": 0.0, "green": 1.0, "blue": 0.0}):  # Зеленый цвет
        bot.send_message(chat_id, f"✅ Заявка №{order_id} подтверждена и окрашена в зеленый.")
    else:
        bot.send_message(chat_id, "❌ Ошибка: Не удалось изменить цвет ячейки.")
##############################################
# Утилита для покраски ячеек (не менялась)
##############################################
def set_cell_color(order_id, color):
    orders = sheet.get_all_values()
    order_index = next((index for index, o in enumerate(orders) if o[0] == order_id), None)
    if order_index is None:
        return False

    body = {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": order_index,
                        "endRowIndex": order_index + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 1
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            }
        ]
    }
    sheet.spreadsheet.batch_update(body)
    return True


##############################################
# ADDED: Universal callback router
##############################################
@bot.callback_query_handler(func=lambda call: True, middlewares=None)
def universal_callback_router(call):
    chat_id = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)

    if call.data.startswith("admin_order_"):
        admin_order_details(call)
    elif call.data.startswith("admin_delete_"):
        admin_delete_order(call)
    elif call.data.startswith("admin_confirm_"):
        admin_confirm_order(call)
    elif call.data.startswith("notify_"):
        notify_client(call)
    elif call.data.startswith("client_confirm_"):
        handle_client_confirm(call)
    elif call.data.startswith("client_question_"):
        handle_client_question(call)
    elif call.data.startswith("client_confirm_replace_"):
        handle_client_confirm_replace(call)
    elif call.data.startswith("client_question_replace_"):
        handle_client_question_replace(call)
    elif call.data.startswith("attach_driver_"):
        attach_driver(call)
    elif call.data in ["confirm_attach_driver", "cancel_attach_driver"]:
        if call.data == "confirm_attach_driver":
            confirm_attach_driver(call)
        else:
            cancel_attach_driver(call)
    elif call.data in tariffs:
        tariff_selection(call)
    elif call.data.startswith("platka_"):
        platka_selection(call)
    elif call.data.startswith("chair_"):
        chair_selection(call)
    elif call.data in ["flight_type_departure", "flight_type_arrival"]:
        process_flight_type(call)

    # ✅ ДОБАВЛЕНЫ новые обработчики
    elif re.match(r"^(departure|arrival)_category_(airports|railways)_\d+$", call.data):
        process_address_category(call)
    elif re.match(r"^(departure|arrival)_back_category_\d+$", call.data):
        process_back_to_category(call)

    elif "_addr_" in call.data:
        process_popular_address(call)

    elif call.data == "confirm":
        confirm_order(call)
    elif call.data == "edit":
        edit_order(call)
    elif call.data == "create_return_trip":
        create_return_trip_callback(call)
    elif call.data == "skip_return_trip":
        skip_return_trip_callback(call)
    elif call.data.startswith("edit_"):
        if call.data.startswith("edit_tariff_confirm_"):
            confirm_edit_tariff(call)
        elif call.data.startswith("edit_platka_confirm_"):
            confirm_edit_platka(call)
        elif call.data.startswith("edit_chair_confirm_"):
            confirm_edit_chair(call)
        elif call.data.startswith("edit_order_"):
            edit_order_details(call)
        elif "_confirm_" not in call.data:
            select_field_to_edit(call)
    elif call.data == "cancel_edit":
        cancel_edit(call)
    elif call.data.startswith("edit_tariff_"):
        edit_tariff_callback(call)
    elif call.data.startswith("order_"):
        order_details(call)
    elif call.data.startswith("delete_"):
        delete_order(call)
    elif call.data == "update_driver_info":
        update_driver_info(call)
    elif call.data.startswith("driver_"):
        show_driver_details(call)
    else:
        bot.answer_callback_query(call.id, "Обработчик не найден.")



@bot.message_handler(func=lambda message: message.chat.id == admin_chat_id and message.text == "Все водители")
def show_all_drivers(message):
    """Выводит список всех водителей для администратора"""
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, name, car_brand FROM drivers')
    drivers = cursor.fetchall()
    conn.close()

    if not drivers:
        bot.send_message(message.chat.id, "Водителей нет в базе данных.")
        return

    markup = InlineKeyboardMarkup()
    for driver in drivers:
        user_id, name, car_brand = driver
        markup.add(InlineKeyboardButton(f"{name} ({car_brand})", callback_data=f"driver_{user_id}"))

    bot.send_message(message.chat.id, "Список всех водителей:", reply_markup=markup)


def show_driver_details(call):
    """Выводит детали водителя при выборе из списка"""
    chat_id = call.message.chat.id
    user_id = call.data.split("_")[1]

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE user_id = ?', (user_id,))
    driver = cursor.fetchone()
    conn.close()

    if not driver:
        bot.send_message(chat_id, "Ошибка: Водитель не найден.")
        return

    driver_info = (
        f"🚖 *Информация о водителе:*\n"
        f"👤 Юзернейм: @{driver[1]}\n"
        f"👤 Имя: {driver[2]}\n"
        f"📞 Телефон: {driver[3]}\n"
        f"🚗 Марка машины: {driver[4]}\n"
        f"🎨 Цвет машины: {driver[6]}\n"
        f"🔢 Гос номер: {driver[5]}"
    )
    bot.send_message(chat_id, driver_info, parse_mode="Markdown")






##############################################
# Админ: просмотр всех заявок
##############################################
@bot.message_handler(func=lambda message: message.chat.id == admin_chat_id and message.text == "Все заявки")
def show_all_orders(message):
    orders = sheet.get_all_values()
    if not orders:
        bot.send_message(message.chat.id, "Заявок нет.")
        return

    markup = InlineKeyboardMarkup()
    for order in orders:
        markup.add(InlineKeyboardButton(f"Заявка №{order[0]}",
                                        callback_data=f"admin_order_{order[0]}"))

    bot.send_message(message.chat.id, "Все заявки:", reply_markup=markup)


def admin_order_details(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]
    orders = sheet.get_all_values()

    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(chat_id, "Заявка не найдена.")
        return

    full_data = (
        f"📋 *Детали заявки №{order[0]}*\n\n"
        f"🚖 *Водитель:* {order[1]}\n"
        f"👤 *Заказчик:* {order[2]}\n"
        f"📅 *В аэропорт/Из аэропорта:* {order[3]}\n"
        f"📅 *Дата:* {order[4]}\n"
        f"⏰ *Подача в:* {order[5]}\n"
        f"⏰ *Время рейса:* {order[6]}\n"
        f"✈️ *Номер рейса:* {order[7]}\n"
        f"📍 *Адрес отправления:* {order[8]}\n"
        f"📍 *Адрес прибытия:* {order[9]}\n"
        f"🧑‍🤝‍🧑 *Кол-во пассажиров:* {order[10]}\n"
        f"👶🏻 *Кол-во детей:* {order[11]}\n"
        f"👤 *ФИО:* {order[12]}\n"
        f"📞 *Телефон:* {order[13]}\n"
        f"ℹ️ *Откуда узнали:* {order[14]}\n"
        f"🚗 *Тариф:* {order[15]}\n"
        f"🏎️ *Платка:* {order[16]}\n"
        f"💺 *Кресло:* {order[17]}"
    )

    markup = InlineKeyboardMarkup()
    confirm_button = InlineKeyboardButton("✅ Подтверждено", callback_data=f"admin_confirm_{order_id}")
    delete_button = InlineKeyboardButton("❌ Удалить заявку", callback_data=f"admin_delete_{order_id}")
    attach_driver_button = InlineKeyboardButton("🚖 Прикрепить водителя", callback_data=f"attach_driver_{order_id}")
    notify_button = InlineKeyboardButton("🔔 Оповестить клиента", callback_data=f"notify_{order_id}")
    generate_message_button = InlineKeyboardButton("📩 Сформировать сообщение", callback_data=f"generate_message_{order_id}")

    markup.add(confirm_button, attach_driver_button)
    markup.add(notify_button, delete_button)
    markup.add(generate_message_button)

    bot.send_message(chat_id, full_data, parse_mode="Markdown", reply_markup=markup)



def admin_delete_order(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]
    orders = sheet.get_all_values()
    order_index = next((index for index, o in enumerate(orders) if o[0] == order_id), None)

    if order_index is None:
        bot.send_message(chat_id, "Заявка не найдена.")
        return

    sheet.delete_rows(order_index + 1)
    bot.send_message(chat_id, f"Заявка №{order_id} удалена.")


##############################################
# Админ: оповещение клиента / водителя
##############################################
def notify_client(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[1]

    client_chat_id = get_chat_id_by_order_id(order_id)
    if not client_chat_id:
        bot.send_message(chat_id, "❌ Ошибка: Невозможно найти chat_id клиента.")
        return

    orders = sheet.get_all_values()
    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(chat_id, "❌ Ошибка: Заявка не найдена.")
        return

    driver_username = order[1]
    driver_username_clean = driver_username.lstrip('@')

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE username = ?', (driver_username_clean,))
    driver = cursor.fetchone()
    conn.close()

    if not driver:
        bot.send_message(chat_id,
                         f"❌ Ошибка: Данные водителя {driver_username} не найдены.")
        return

    # Обработка ночной подачи
    flight_time_str = order[6]
    flight_date_str = order[4]
    dispatch_time_str = order[5]
    dispatch_date = flight_date_str

    try:
        flight_time = datetime.datetime.strptime(flight_time_str, "%H:%M").time()
        dispatch_time = datetime.datetime.strptime(dispatch_time_str, "%H:%M").time()

        if dispatch_time > flight_time:
            # Значит подача — накануне вечером
            flight_date = datetime.datetime.strptime(flight_date_str, "%d.%m.%Y")
            dispatch_date = (flight_date - datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    except Exception as e:
        dispatch_date = flight_date_str  # fallback

    client_message = (
        f"Добрый день, {dispatch_date} в {order[5]} по адресу {order[8]} Вас будет ожидать "
        f"{driver[4]} {driver[6]}, {driver[5]}, водитель {driver[3]} {driver[2]}. "
        f"Сообщите, пожалуйста, о получении информации."
    )

    markup = InlineKeyboardMarkup()
    confirm_button = InlineKeyboardButton("✅ Подтверждаю", callback_data=f"client_confirm_{order_id}")
    question_button = InlineKeyboardButton("❓ Есть вопросы", callback_data=f"client_question_{order_id}")
    markup.add(confirm_button, question_button)

    try:
        bot.send_message(client_chat_id, client_message, reply_markup=markup)
        bot.send_message(chat_id, f"✅ Клиент заявки №{order_id} успешно оповещен.")

        # Оповещение водителя
        driver_chat_id = driver[0]
        driver_message = (
            f"🚖 Уведомление:\n"
            f"Вы назначены водителем по заявке №{order_id}.\n"
            f"Дата подачи: {dispatch_date}\n"
            f"Время подачи: {order[5]}\n"
            f"Адрес подачи: {order[8]}\n"
            f"📍 Адрес прибытия: {order[9]}\n"
            f"🧑‍🤝‍🧑 Пассажиров: {order[10]}, 👶🏻 Детей: {order[11]}\n"
            f"💺 Кресло: {order[17]}, 🏎️ Платка: {order[16]}\n"
            f"🚗 Тариф: {order[15]}\n"
            f"Клиент: {order[12]}, Телефон: {order[13]}"
        )

        bot.send_message(driver_chat_id, driver_message)
        bot.send_message(chat_id, f"✅ Водитель также получил уведомление.")

    except telebot.apihelper.ApiTelegramException as e:
        if "chat not found" in str(e):
            bot.send_message(chat_id,
                             f"❌ Ошибка: Чат не найден (chat_id: {client_chat_id} или водитель).")
        else:
            bot.send_message(chat_id,
                             f"❌ Ошибка при отправке уведомлений: {e}")




def handle_client_confirm(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    bot.send_message(admin_chat_id,
                     f"✅ Клиент заявки №{order_id} подтвердил получение информации.")
    set_cell_color(order_id, {"red": 0.0, "green": 1.0, "blue": 0.0})
    bot.send_message(chat_id,
                     "Спасибо за подтверждение! Если возникнут вопросы, свяжитесь с нами.")


def handle_client_question(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    bot.send_message(admin_chat_id,
                     f"❓ Клиент заявки №{order_id} имеет вопросы. Свяжитесь с ним.")
    set_cell_color(order_id, {"red": 1.0, "green": 0.0, "blue": 0.0})
    bot.send_message(chat_id, "Обратитесь к администратору для уточнения деталей.")


def handle_client_confirm_replace(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    set_cell_color(order_id, {"red": 0.0, "green": 1.0, "blue": 0.0})
    if admin_chat_id:
        bot.send_message(admin_chat_id,
                         f"✅ Клиент по заявке №{order_id} подтвердил получение данных о новом водителе.")

    bot.send_message(chat_id,
                     "Спасибо за подтверждение! Если возникнут вопросы, свяжитесь с нами.")


def handle_client_question_replace(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    set_cell_color(order_id, {"red": 1.0, "green": 0.0, "blue": 0.0})
    if admin_chat_id:
        bot.send_message(admin_chat_id,
                         f"❓ Клиент по заявке №{order_id} имеет вопросы по смене водителя.")

    bot.send_message(chat_id,
                     "Мы передадим информацию администратору, ожидайте, пожалуйста, обратной связи.")


##############################################
# Админ: прикрепить водителя к заявке
##############################################
def attach_driver(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]

    user_data[chat_id] = {"order_id": order_id, "action": "attach_driver"}
    bot.send_message(chat_id, "Введите номер телефона или юзернейм водителя (без @):")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_input)


def process_driver_input(message):
    chat_id = message.chat.id
    if chat_id not in user_data or user_data[chat_id].get("action") != "attach_driver":
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют.")
        return

    user_data[chat_id]["driver_info"] = message.text.strip()

    markup = InlineKeyboardMarkup()
    confirm_button = InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_attach_driver")
    cancel_button = InlineKeyboardButton("❌ Отменить", callback_data="cancel_attach_driver")
    markup.add(confirm_button, cancel_button)

    bot.send_message(chat_id,
                     f"Вы хотите прикрепить водителя: {message.text}?",
                     reply_markup=markup)


def confirm_attach_driver(call):
    chat_id = call.message.chat.id
    if (chat_id not in user_data
            or user_data[chat_id].get("action") != "attach_driver"):
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют.")
        return

    order_id = user_data[chat_id]["order_id"]
    new_driver_info = user_data[chat_id]["driver_info"]

    orders = sheet.get_all_values()
    order_index = next((index for index, o in enumerate(orders) if o[0] == order_id), None)
    if order_index is None:
        bot.send_message(chat_id, "❌ Заявка не найдена.")
        return

    old_driver_username = orders[order_index][1].lstrip("@").strip()
    sheet.update_cell(order_index + 1, 2, new_driver_info)  # B колонка: водитель

    bot.send_message(chat_id,
                     f"✅ Водитель {new_driver_info} успешно прикреплён к заявке №{order_id}.")

    # Оповещение клиента
    client_chat_id = get_chat_id_by_order_id(order_id)
    if not client_chat_id:
        bot.send_message(chat_id,
                         "❌ Ошибка: Невозможно найти chat_id клиента.")
    else:
        clean_username = new_driver_info.lstrip('@')
        conn = sqlite3.connect('users_orders.db')
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM drivers WHERE username = ? OR phone = ?',
            (clean_username, clean_username)
        )
        driver_data = cursor.fetchone()
        conn.close()

        if driver_data:
            orders = sheet.get_all_values()
            order = next((o for o in orders if o[0] == order_id), None)
            if order:
                msg_text = (
                    f"Добрый день! Ваша заявка №{order_id} обновлена.\n"
                    f"Новый водитель: {driver_data[2]}\n"
                    f"Телефон: {driver_data[3]}\n"
                    f"Автомобиль: {driver_data[4]} {driver_data[5]}, госномер {driver_data[6]}\n\n"
                    f"Это уведомление о том, что водитель был изменён."
                )
                try:
                    bot.send_message(client_chat_id, msg_text)
                    bot.send_message(chat_id, "✅ Клиент оповещён о смене водителя.")

                    # Оповещение нового водителя
                    driver_message = (
                        f"🚖 Уведомление:\n"
                        f"Вы назначены водителем по заявке №{order_id}.\n"
                        f"Дата подачи: {order[4]}\n"
                        f"Время подачи: {order[5]}\n"
                        f"Адрес подачи: {order[8]}\n"
                        f"📍 Адрес прибытия: {order[9]}\n"
                        f"🧑‍🤝‍🧑 Пассажиров: {order[10]}, 👶🏻 Детей: {order[11]}\n"
                        f"💺 Кресло: {order[17]}, 🏎️ Платка: {order[16]}\n"
                        f"🚗 Тариф: {order[15]}\n"
                        f"Клиент: {order[12]}, Телефон: {order[13]}"
                    )
                    bot.send_message(driver_data[0], driver_message)

                    # Оповещение старого водителя, если отличается
                    if old_driver_username and old_driver_username != clean_username:
                        conn = sqlite3.connect('users_orders.db')
                        cursor = conn.cursor()
                        cursor.execute(
                            'SELECT user_id FROM drivers WHERE username = ?',
                            (old_driver_username,)
                        )
                        old_driver_result = cursor.fetchone()
                        conn.close()
                        if old_driver_result:
                            bot.send_message(
                                old_driver_result[0],
                                f"ℹ️ Вы были сняты с заявки №{order_id}."
                            )

                except telebot.apihelper.ApiTelegramException as e:
                    bot.send_message(chat_id, f"❌ Не удалось оповестить: {e}")
        else:
            bot.send_message(chat_id,
                             "❌ Новый водитель не найден в базе (drivers). Оповещение не отправлено.")

    del user_data[chat_id]

def cancel_attach_driver(call):
    chat_id = call.message.chat.id
    if chat_id in user_data and user_data[chat_id].get("action") == "attach_driver":
        del user_data[chat_id]

    bot.send_message(chat_id, "❌ Прикрепление водителя отменено.")


##############################################
# Стоимость услуг
##############################################
@bot.message_handler(func=lambda message: message.text == "Стоимость услуг")
def show_tariffs(message):
    tariffs_text = "🚗 *Стоимость услуг:*\n\n"
    for key, value in tariffs.items():
        tariffs_text += f"• {value}\n"
    bot.send_message(message.chat.id, tariffs_text, parse_mode="Markdown")


##############################################
# Создание заявки (пошаговый ввод)
##############################################

@bot.message_handler(func=lambda message: message.text == "Создать заявку")
def create_order(message):
    start_order(message.chat.id)


def start_order(chat_id):
    user_data[chat_id] = []
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    btn_departure = types.InlineKeyboardButton("В аэропорт", callback_data="flight_type_departure")
    btn_arrival = types.InlineKeyboardButton("Из аэропорта", callback_data="flight_type_arrival")
    keyboard.add(btn_departure, btn_arrival)
    bot.send_message(chat_id, "Укажите, это Вам нужен трансфер в аэропорт или из аэропорта?", reply_markup=keyboard)


def process_flight_type(call):
    chat_id = call.message.chat.id
    flight_type = "В аэропорт" if call.data == "flight_type_departure" else "Из аэропорта"
    user_data[chat_id].append(flight_type)  # data[0]

    bot.answer_callback_query(call.id)

    if flight_type == "В аэропорт":
        bot.send_message(
            chat_id,
            "📆 Введите дату вылета (например: 01.05.2025):",
            reply_markup=get_cancel_markup()
        )
    else:
        bot.send_message(
            chat_id,
            "📆 Введите дату прилета (например: 01.05.2025):",
            reply_markup=get_cancel_markup()
        )

    bot.register_next_step_handler_by_chat_id(chat_id, step_flight_date)


def step_flight_date(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
        bot.send_message(
            chat_id,
            "❌ Неверный формат даты! Введите дд.мм.гггг (например: 01.05.2025):",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler_by_chat_id(chat_id, step_flight_date)
        return

    user_data[chat_id].append(text)  # data[1] = Дата
    bot.send_message(
        chat_id,
        "⏰ Введите время рейса (ЧЧ:ММ):",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, step_flight_time)


def step_flight_time(message):
    chat_id = message.chat.id
    text = message.text.strip()
    try:
        flight_dt = datetime.datetime.strptime(text, "%H:%M")
    except ValueError:
        bot.send_message(
            chat_id,
            "Неверный формат! Введите время в формате ЧЧ:ММ.",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler_by_chat_id(chat_id, step_flight_time)
        return

    user_data[chat_id].append(text)  # data[2] = Время рейса
    flight_type = user_data[chat_id][0]

    if flight_type == "В аэропорт":
        dispatch_dt = flight_dt - datetime.timedelta(hours=7)
    else:
        dispatch_dt = flight_dt

    dispatch_str = dispatch_dt.strftime("%H:%M")
    user_data[chat_id].append(dispatch_str)  # data[3] = Подача

    bot.send_message(
        chat_id,
        "✈️ Введите номер рейса:",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, flight_number)


def flight_number(message):
    chat_id = message.chat.id
    user_data[chat_id].append(message.text)  # data[4]
    flight_type = user_data[chat_id][0]

    if flight_type == "В аэропорт":
        bot.send_message(
            chat_id,
            "📍 Введите адрес отправления (свой вариант):",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler_by_chat_id(chat_id, process_custom_departure_address)
    else:
        show_popular_addresses(chat_id, "departure", 5, "📍 Выберите адрес отправления:")


def process_custom_departure_address(message):
    chat_id = message.chat.id
    user_data[chat_id].append(message.text)  # data[5]
    show_popular_addresses(chat_id, "arrival", 6, "📍 Выберите адрес прибытия:")


def show_popular_addresses(chat_id, prefix, field_index, text_for_user):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✈️ Аэропорты", callback_data=f"{prefix}_category_airports_{field_index}"),
        InlineKeyboardButton("🚉 Вокзалы", callback_data=f"{prefix}_category_railways_{field_index}")
    )
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))
    bot.send_message(chat_id, text_for_user, reply_markup=markup)

airports = [
    "Шереметьево (аэропорт)",
    "Домодедово (аэропорт)",
    "Внуково (аэропорт)",
    "Жуковский (аэропорт)"
]

railway_stations = [
    "Казанский вокзал (вокзал)",
    "Ленинградский вокзал (вокзал)",
    "Ярославский вокзал (вокзал)",
    "Киевский вокзал (вокзал)",
    "Павелецкий вокзал (вокзал)",
    "Курский вокзал (вокзал)",
    "Белорусский вокзал (вокзал)",
    "Рижский вокзал (вокзал)",
    "Савеловский вокзал (вокзал)"
]

@bot.callback_query_handler(func=lambda call: re.match(r"^(departure|arrival)_category_(airports|railways)_\d+$", call.data))
def process_address_category(call):
    chat_id = call.message.chat.id
    parts = call.data.split("_")
    prefix = parts[0]  # departure / arrival
    category = parts[2]  # airports / railways
    field_index = int(parts[3])

    address_list = airports if category == "airports" else railway_stations

    markup = InlineKeyboardMarkup(row_width=1)
    for i, addr in enumerate(address_list):
        callback_data = f"{prefix}_addr_idx_{i}"
        markup.add(InlineKeyboardButton(addr, callback_data=callback_data))

    # Кнопка "Назад"
    markup.add(InlineKeyboardButton("🔙 Назад", callback_data=f"{prefix}_back_category_{field_index}"))

    # Кнопка "Отмена"
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.edit_message_text("Выберите адрес:", chat_id=chat_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: re.match(r"^(departure|arrival)_back_category_\d+$", call.data))
def process_back_to_category(call):
    chat_id = call.message.chat.id
    parts = call.data.split("_")
    prefix = parts[0]
    field_index = int(parts[3])
    show_popular_addresses(chat_id, prefix, field_index, "Выберите категорию адреса:")


def process_popular_address(call):
    chat_id = call.message.chat.id
    parts = call.data.split("_addr_")  # e.g. ["departure","idx_0"] or ["departure","custom_5"]
    prefix = parts[0]
    remainder = parts[1]

    if remainder.startswith("custom_"):
        field_index = int(remainder.split("_")[1])  # Исправлено: добавлена закрывающая скобка
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "Введите адрес (свой вариант):",
            reply_markup=get_cancel_markup()
        )
        # Сохраняем информацию о текущем шаге
        user_data[chat_id] = {
            "prefix": prefix,
            "field_index": field_index,
            "custom_addr": True
        }
        bot.register_next_step_handler_by_chat_id(chat_id, process_custom_address)

    elif remainder.startswith("idx_"):
        i = int(remainder.split("_")[1])
        address = popular_addresses[i]
        bot.answer_callback_query(call.id, f"Вы выбрали: {address}")

        if prefix == "departure":
            field_index = 5
        else:
            field_index = 6

        # Убедимся, что список user_data[chat_id] достаточно длинный
        while len(user_data[chat_id]) <= field_index:
            user_data[chat_id].append(None)
        user_data[chat_id][field_index] = address

        if prefix == "departure":
            flight_type = user_data[chat_id][0]
            if flight_type == "В аэропорт":
                show_popular_addresses(chat_id, "arrival", 6, "📍 Выберите адрес прибытия:")
            else:
                bot.send_message(
                    chat_id,
                    "📍 Введите адрес прибытия (свой вариант):",
                    reply_markup=get_cancel_markup()
                )
                bot.register_next_step_handler_by_chat_id(chat_id, process_custom_arrival_address)
        else:
            bot.send_message(
                chat_id,
                "🧑‍🤝‍🧑 Введите количество пассажиров:",
                reply_markup=get_cancel_markup()
            )
            bot.register_next_step_handler_by_chat_id(chat_id, passengers_count)


def process_custom_arrival_address(message):
    chat_id = message.chat.id
    user_data[chat_id].append(message.text)  # data[6]
    bot.send_message(
        chat_id,
        "🧑‍🤝‍🧑 Введите количество пассажиров:",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, passengers_count)


def passengers_count(message):
    chat_id = message.chat.id
    if not validate_passenger_count(message.text):
        bot.send_message(
            chat_id,
            "❌ Введите число от 1 до 10 (только цифры). Повторите ввод:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, passengers_count)
        return

    user_data[chat_id].append(message.text)  # data[7]
    bot.send_message(
        chat_id,
        "👶🏻 Введите количество детей:",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler(message, children_count)


def children_count(message):
    chat_id = message.chat.id
    if not validate_children_count(message.text):
        bot.send_message(
            chat_id,
            "❌ Введите число от 0 до 10 (только цифры). Повторите ввод:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, children_count)
        return

    user_data[chat_id].append(message.text)  # data[8]

    if int(message.text) > 0:
        markup = InlineKeyboardMarkup()
        for option in chair_options:
            markup.add(InlineKeyboardButton(option, callback_data=f"chair_{option}"))
        markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))
        bot.send_message(chat_id, "💺 Нужно ли детское кресло?", reply_markup=markup)
    else:
        user_data[chat_id].append("Нет")  # data[9] = Кресло (если детей нет)
        bot.send_message(
            chat_id,
            "👤 Введите ФИО:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, full_name)


def chair_selection(call):
    chat_id = call.message.chat.id
    choice = call.data.split("_")[1]
    user_data[chat_id].append(choice)  # data[9]

    bot.send_message(chat_id, f"Вы выбрали кресло: {choice}")
    bot.send_message(
        chat_id,
        "👤 Введите ФИО:",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, full_name)


def full_name(message):
    chat_id = message.chat.id
    if not validate_fio(message.text):
        bot.send_message(
            chat_id,
            "❌ ФИО должно содержать только буквы и пробелы. Повторите ввод:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, full_name)
        return

    user_data[chat_id].append(message.text)  # data[10]
    bot.send_message(
        chat_id,
        "☎️ Введите телефон (11 цифр):",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler(message, phone_number)


def phone_number(message):
    chat_id = message.chat.id
    if not validate_phone_number(message.text):
        bot.send_message(
            chat_id,
            "❌ Номер должен состоять только из 11 цифр, без + и пробелов. Повторите:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, phone_number)
        return

    user_data[chat_id].append(message.text)  # data[11]
    bot.send_message(
        chat_id,
        "ℹ️ Введите, откуда вы узнали о нас (только буквы):",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler(message, referral)


def referral(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if not validate_referral(text):
        bot.send_message(
            chat_id,
            "❌ Укажите только буквы. Введите ещё раз:",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler(message, referral)
        return

    user_data[chat_id].append(text)  # data[12]

    # Предлагаем тарифы с учётом пассажиров
    try:
        passengers = int(user_data[chat_id][7])
    except ValueError:
        passengers = 1

    available_tariffs = {}
    for key, value in tariffs.items():
        if "3 пассажира" in value and passengers <= 3:
            available_tariffs[key] = value
        elif "4 пассажира" in value and passengers <= 4:
            available_tariffs[key] = value
        elif "7 пассажиров" in value and passengers <= 7:
            available_tariffs[key] = value
        elif "8 пассажиров" in value and passengers <= 8:
            available_tariffs[key] = value

    markup = InlineKeyboardMarkup()
    for tkey, text_tariff in available_tariffs.items():
        markup.add(InlineKeyboardButton(text_tariff, callback_data=tkey))

    # Add “Cancel” button
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, "🚘 Выберите тариф:", reply_markup=markup)


def tariff_selection(call):
    chat_id = call.message.chat.id
    user_data[chat_id].append(tariffs[call.data])  # data[13]
    bot.send_message(chat_id, f"Вы выбрали тариф: {tariffs[call.data]}")

    markup = InlineKeyboardMarkup()
    for option in platka_options:
        markup.add(InlineKeyboardButton(option, callback_data=f"platka_{option}"))

    # Cancel button
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, "🏎️ Платка (да или нет):", reply_markup=markup)


def platka_selection(call):
    chat_id = call.message.chat.id
    choice = call.data.split("_")[1]
    user_data[chat_id].append(choice)  # data[14]

    bot.send_message(chat_id, f"Вы выбрали платку: {choice}")
    send_summary(chat_id)


def send_summary(chat_id):
    data = user_data.get(chat_id, [])
    if len(data) < 15:
        bot.send_message(chat_id, "❌ Ошибка: Не все данные заявки заполнены.")
        return

    summary = (
        f"📝 *Предварительная заявка:*\n"
        f"📅 Дата: {data[1]}\n"
        f"✈️ В аэропорт/Из аэропорта: {data[0]}\n"
        f"⏰ Время рейса: {data[2]}\n"
        f"🚕 Подача в: {data[3]}\n"
        f"🛫 Номер рейса: {data[4]}\n"
        f"📍 Адрес отправления: {data[5]}\n"
        f"📍 Адрес прибытия: {data[6]}\n"
        f"🧑‍🤝‍🧑 Кол-во пассажиров: {data[7]}\n"
        f"👶🏻 Кол-во детей: {data[8]}\n"
        f"💺 Кресло: {data[9]}\n"
        f"👤 ФИО: {data[10]}\n"
        f"☎️ Телефон: {data[11]}\n"
        f"ℹ️ Откуда узнали: {data[12]}\n"
        f"🚘 Тариф: {data[13]}\n"
        f"🏎️ Платка: {data[14]}"
    )

    markup = InlineKeyboardMarkup()
    confirm_button = InlineKeyboardButton("✅ Забронировать", callback_data="confirm")
    edit_button = InlineKeyboardButton("📝 Редактировать", callback_data="edit")
    markup.add(confirm_button, edit_button)

    # Cancel
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, summary, parse_mode="Markdown", reply_markup=markup)


def confirm_order(call):
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют.")
        return

    data = user_data[chat_id]
    if len(data) < 15:
        bot.send_message(chat_id, "❌ Ошибка: Не все данные заявки заполнены.")
        return

    application_number = generate_order_number()
    data.append(application_number)  # data[15]

    username = call.message.chat.username
    if not username or username.strip() == "":
        username = data[10] if len(data) > 10 and data[10] else "-"

    send_to_google_sheets(chat_id, username, data)
    add_order_to_db(chat_id, application_number, chat_id)

    bot.send_message(chat_id,
                     f"✅ Заявка подтверждена и отправлена!\nНомер вашей заявки: {application_number}")

    # Предлагаем создать обратную заявку
    markup = InlineKeyboardMarkup()
    yes_button = InlineKeyboardButton("Да", callback_data="create_return_trip")
    no_button = InlineKeyboardButton("Нет", callback_data="skip_return_trip")
    markup.add(yes_button, no_button)
    bot.send_message(chat_id,
                     "Хотите сразу оформить обратную поездку?",
                     reply_markup=markup)


def edit_order(call):
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют.")
        return

    markup = InlineKeyboardMarkup()
    fields = [
        ("0", "📅 Дата"),
        ("1", "✈️ В аэропорт/Из аэропорта"),
        ("2", "⏰ Время рейса"),
        ("4", "🛫 Номер рейса"),
        ("5", "📍 Адрес отправления"),
        ("6", "📍 Адрес прибытия"),
        ("7", "🧑‍🤝‍🧑 Кол-во пассажиров"),
        ("8", "👶🏻 Кол-во детей"),
        ("9", "👤 ФИО"),
        ("10", "☎️ Телефон"),
        ("11", "ℹ️ Откуда узнали"),
        ("12", "🚘 Тариф"),
        ("13", "🏎️ Платка"),
        ("14", "💺 Кресло"),
    ]
    for index, field_name in fields:
        markup.add(InlineKeyboardButton(field_name, callback_data=f"edit_{index}"))

    # Cancel
    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, "Выберите поле для редактирования:", reply_markup=markup)


def select_field_to_edit(call):
    chat_id = call.message.chat.id
    field_key = call.data.replace("edit_", "", 1)

    try:
        field_index = int(field_key)
    except ValueError:
        bot.send_message(chat_id, "❌ Ошибка: Неверный формат данных.")
        return

    if field_index == 12:
        # Edit tariff
        try:
            passengers = int(user_data[chat_id][7])
        except ValueError:
            passengers = 1

        available_tariffs = {}
        for key, value in tariffs.items():
            if "3 пассажира" in value and passengers <= 3:
                available_tariffs[key] = value
            elif "4 пассажира" in value and passengers <= 4:
                available_tariffs[key] = value
            elif "7 пассажиров" in value and passengers <= 7:
                available_tariffs[key] = value
            elif "8 пассажиров" in value and passengers <= 8:
                available_tariffs[key] = value

        markup = InlineKeyboardMarkup()
        for tariff_key, tariff_text in available_tariffs.items():
            callback = f"edit_tariff_confirm_{tariff_key}"
            markup.add(InlineKeyboardButton(tariff_text, callback_data=callback))

        # Cancel
        markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))
        bot.send_message(chat_id, "🚘 Выберите новый тариф:", reply_markup=markup)
        return

    elif field_index == 13:
        # Edit platka
        markup = InlineKeyboardMarkup()
        for option in platka_options:
            callback = f"edit_platka_confirm_{option}"
            markup.add(InlineKeyboardButton(option, callback_data=callback))

        # Cancel
        markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))
        bot.send_message(chat_id, "🏎️ Выберите платку (Да или Нет):", reply_markup=markup)
        return

    elif field_index == 14:
        # Edit chair
        markup = InlineKeyboardMarkup()
        for option in chair_options:
            callback = f"edit_chair_confirm_{option}"
            markup.add(InlineKeyboardButton(option, callback_data=callback))

        # Cancel
        markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))
        bot.send_message(chat_id, "💺 Выберите кресло (Да или Нет):", reply_markup=markup)
        return

    # If it's a normal text field:
    if chat_id not in user_data or len(user_data[chat_id]) <= field_index:
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют или неполные.")
        return

    current_value = user_data[chat_id][field_index]
    markup = InlineKeyboardMarkup()
    cancel_button = InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")
    markup.add(cancel_button)

    bot.send_message(
        chat_id,
        f"📝 Вы редактируете поле:\n"
        f"Текущее значение: *{current_value}*\nВведите новое значение:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.register_next_step_handler_by_chat_id(chat_id, process_field_edit, field_index)


def process_field_edit(message, field_index):
    chat_id = message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "❌ Ошибка: Данные заявки отсутствуют.")
        return

    user_data[chat_id][field_index] = message.text

    # Пересчитываем "Подача" (data[3]) если менялись [1] (Вылет/Прилет) или [2] (Время рейса)
    if field_index in [1, 2]:
        recalc_dispatch_time(chat_id)

    # Если заявки ещё нет (нет data[15]):
    if len(user_data[chat_id]) < 16:
        bot.send_message(chat_id, "✅ Данные обновлены!")
        send_summary(chat_id)
    else:
        # Уже подтвержденная заявка -> обновим Google Sheets
        order_id = user_data[chat_id][15]
        if update_google_sheets(order_id, user_data[chat_id]):
            bot.send_message(chat_id, "✅ Данные обновлены в таблице!")
        else:
            bot.send_message(chat_id, "❌ Ошибка при обновлении данных в таблице.")


def recalc_dispatch_time(chat_id):
    data = user_data[chat_id]
    flight_type = data[1]
    try:
        flight_dt = datetime.datetime.strptime(data[2], "%H:%M")
    except ValueError:
        return
    if flight_type == "В аэропорт":
        dispatch_dt = flight_dt - datetime.timedelta(hours=7)
    else:
        dispatch_dt = flight_dt
    data[3] = dispatch_dt.strftime("%H:%M")


def cancel_edit(call):
    chat_id = call.message.chat.id
    bot.send_message(chat_id, "❌ Редактирование отменено.")
    send_summary(chat_id)


##############################################
# Список заявок ("Мои заявки")
##############################################
@bot.message_handler(func=lambda message: message.text == "Мои заявки")
def my_orders(message):
    chat_id = message.chat.id
    user_orders = get_user_orders(chat_id)
    if not user_orders:
        bot.send_message(chat_id, "У вас нет заявок.")
        return

    markup = InlineKeyboardMarkup()
    for order_id in user_orders:
        markup.add(InlineKeyboardButton(f"Заявка №{order_id}",
                                        callback_data=f"order_{order_id}"))
    bot.send_message(chat_id, "Ваши заявки:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("order_"))
def order_details(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[1]

    orders = sheet.get_all_values()
    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(chat_id, "Заявка не найдена.")
        return

    summary = (
        f"📋 *Детали заявки №{order[0]}*\n\n"
        f"🚖 *Водитель:* {order[1]}\n"
        f"👤 *Заказчик:* {order[2]}\n"
        f"📅 *В аэроопорт/Из аэропорта:* {order[3]}\n"
        f"📅 *Дата:* {order[4]}\n"
        f"⏰ *Подача в:* {order[5]}\n"
        f"⏰ *Время рейса:* {order[6]}\n"
        f"✈️ *Номер рейса:* {order[7]}\n"
        f"📍 *Адрес отправления:* {order[8]}\n"
        f"📍 *Адрес прибытия:* {order[9]}\n"
        f"🧑‍🤝‍🧑 *Кол-во пассажиров:* {order[10]}\n"
        f"👶🏻 *Кол-во детей:* {order[11]}\n"
        f"👤 *ФИО:* {order[12]}\n"
        f"📞 *Телефон:* {order[13]}\n"
        f"ℹ️ *Откуда узнали:* {order[14]}\n"
        f"🚗 *Тариф:* {order[15]}\n"
        f"🏎️ *Платка:* {order[16]}\n"
        f"💺 *Кресло:* {order[17]}"
    )

    markup = InlineKeyboardMarkup()
    delete_button = InlineKeyboardButton("❌ Удалить заявку", callback_data=f"delete_{order_id}")
    edit_button = InlineKeyboardButton("📝 Изменить заявку", callback_data=f"edit_order_{order_id}")
    markup.add(delete_button, edit_button)

    bot.send_message(chat_id, summary, parse_mode="Markdown", reply_markup=markup)


def delete_order(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[1]

    orders = sheet.get_all_values()
    order_index = next((index for index, o in enumerate(orders) if o[0] == order_id), None)
    if order_index is None:
        bot.send_message(chat_id, "Заявка не найдена.")
        return

    sheet.delete_rows(order_index + 1)
    delete_order_from_db(chat_id, order_id)
    bot.send_message(chat_id, f"Заявка №{order_id} удалена.")


def edit_order_details(call):
    chat_id = call.message.chat.id
    order_id = call.data.split("_")[2]
    orders = sheet.get_all_values()

    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(chat_id, "Заявка не найдена.")
        return

    loaded_data = [
        order[4],   # 0 Дата
        order[3],   # 1 Вылет/Прилет
        order[6],   # 2 Время рейса
        order[5],   # 3 Подача
        order[7],   # 4 Рейс
        order[8],   # 5 Адрес Отпр
        order[9],   # 6 Адрес Приб
        order[10],  # 7 Пасс
        order[11],  # 8 Дети
        order[12],  # 9 ФИО
        order[13],  # 10 Тел
        order[14],  # 11 Узнали
        order[15],  # 12 Тариф
        order[16],  # 13 Платка
        order[17],  # 14 Кресло
        order[0]    # 15 Номер заявки
    ]
    user_data[chat_id] = loaded_data

    markup = InlineKeyboardMarkup()
    fields = [
        ("0", "📅 Дата"),
        ("1", "✈️ В аэропорт/Из аэропорта"),
        ("2", "⏰ Время рейса"),
        ("4", "🛫 Номер рейса"),
        ("5", "📍 Адрес отправления"),
        ("6", "📍 Адрес прибытия"),
        ("7", "🧑‍🤝‍🧑 Кол-во пассажиров"),
        ("8", "👶🏻 Кол-во детей"),
        ("9", "👤 ФИО"),
        ("10", "☎️ Телефон"),
        ("11", "ℹ️ Откуда узнали"),
        ("12", "🚘 Тариф"),
        ("13", "🏎️ Платка"),
        ("14", "💺 Кресло"),
    ]
    for index, field_name in fields:
        markup.add(InlineKeyboardButton(field_name, callback_data=f"edit_{index}"))

    # Cancel
    # markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, "Выберите поле для редактирования:", reply_markup=markup)


##############################################
# Возвратная поездка
##############################################
def create_return_trip_callback(call):
    chat_id = call.message.chat.id
    if chat_id not in user_data or len(user_data[chat_id]) < 16:
        bot.send_message(chat_id, "❌ Нет исходной заявки для создания обратной.")
        return

    old_data = user_data[chat_id]
    return_data = old_data[:15].copy()

    # Меняем местами адреса
    old_departure = return_data[5]
    old_arrival = return_data[6]
    return_data[5] = old_arrival
    return_data[6] = old_departure

    # Переключаем "Вылет" <-> "Прилет"
    if return_data[0] == "В аэропорт":
        return_data[0] = "Из аэропорта"
    else:
        return_data[0] = "В аэропорт"

    user_data[chat_id] = return_data
    if len(user_data[chat_id]) == 16:
        user_data[chat_id].pop()

    bot.answer_callback_query(call.id)
    bot.send_message(
        chat_id,
        "📆 Введите дату обратной поездки (дд.мм.гггг):",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, return_trip_date)



def skip_return_trip_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, "Обратная заявка не создаётся.")
    bot.send_message(chat_id, "Спасибо! Если потребуется, вы можете создать заявку позже командой /start.")


def return_trip_date(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
        bot.send_message(
            chat_id,
            "❌ Неверный формат даты! Введите в формате дд.мм.гггг.",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler_by_chat_id(chat_id, return_trip_date)
        return

    user_data[chat_id][1] = text  # Дата поездки (index 1)
    bot.send_message(
        chat_id,
        "⏰ Введите время рейса (ЧЧ:ММ):",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, return_trip_time)

def return_trip_time(message):
    chat_id = message.chat.id
    text = message.text.strip()
    try:
        flight_dt = datetime.datetime.strptime(text, "%H:%M")
    except ValueError:
        bot.send_message(
            chat_id,
            "Неверный формат! Введите время в формате ЧЧ:ММ.",
            reply_markup=get_cancel_markup()
        )
        bot.register_next_step_handler_by_chat_id(chat_id, return_trip_time)
        return

    user_data[chat_id][2] = text  # Время рейса (index 2)
    flight_type = user_data[chat_id][0]  # Вылет/Прилет

    if flight_type == "В аэропорт":
        dispatch_dt = flight_dt - datetime.timedelta(hours=7)
    else:
        dispatch_dt = flight_dt

    user_data[chat_id][3] = dispatch_dt.strftime("%H:%M")  # Подача (index 3)

    bot.send_message(
        chat_id,
        "✈️ Введите номер обратного рейса:",
        reply_markup=get_cancel_markup()
    )
    bot.register_next_step_handler_by_chat_id(chat_id, return_trip_flight_number)



def return_trip_flight_number(message):
    chat_id = message.chat.id
    user_data[chat_id][4] = message.text
    send_summary(chat_id)


##############################################
# Блок для водителей
##############################################
def init_drivers_db():
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            phone TEXT,
            car_brand TEXT,
            car_color TEXT,
            car_number TEXT
        )
    ''')
    conn.commit()
    conn.close()


init_drivers_db()


@bot.message_handler(func=lambda message: message.text == "🚖 Для водителей")
def driver_registration(message):
    chat_id = message.chat.id
    username = message.from_user.username

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE username = ?', (username,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        driver_info = (
            f"🚖 *Ваши данные:*\n\n"
            f"👤 Юзернейм: @{driver[1]}\n"
            f"👤 Имя: {driver[2]}\n"
            f"📞 Телефон: {driver[3]}\n"
            f"🚗 Марка машины: {driver[4]}\n"
            f"🎨 Цвет машины: {driver[5]}\n"
            f"🔢 Гос номер: {driver[6]}"
        )
        markup = InlineKeyboardMarkup()
        update_button = InlineKeyboardButton("🔄 Заполнить заново", callback_data="update_driver_info")
        markup.add(update_button)
        bot.send_message(chat_id, driver_info, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id,
                         "👋 Добро пожаловать! Давайте зарегистрируем вас как водителя.")
        bot.send_message(chat_id, "Введите ваше имя:")
        bot.register_next_step_handler_by_chat_id(chat_id, process_driver_name)


def process_driver_name(message):
    chat_id = message.chat.id
    user_data[chat_id] = {"name": message.text}
    bot.send_message(chat_id, "📞 Введите ваш номер телефона:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_phone)


def process_driver_phone(message):
    chat_id = message.chat.id
    user_data[chat_id]["phone"] = message.text
    bot.send_message(chat_id, "🚗 Введите марку вашей машины:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_car_brand)


def process_driver_car_brand(message):
    chat_id = message.chat.id
    user_data[chat_id]["car_brand"] = message.text
    bot.send_message(chat_id, "🎨 Введите цвет вашей машины:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_car_color)


def process_driver_car_color(message):
    chat_id = message.chat.id
    user_data[chat_id]["car_color"] = message.text
    bot.send_message(chat_id, "🔢 Введите гос номер вашей машины:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_car_number)


def process_driver_car_number(message):
    chat_id = message.chat.id
    user_data[chat_id]["car_number"] = message.text
    username = message.from_user.username

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE user_id = ?', (chat_id,))
    existing_driver = cursor.fetchone()

    if existing_driver:
        cursor.execute('''
            UPDATE drivers
            SET username = ?, name = ?, phone = ?, car_brand = ?, car_color = ?, car_number = ?
            WHERE user_id = ?
        ''', (
            username,
            user_data[chat_id]["name"],
            user_data[chat_id]["phone"],
            user_data[chat_id]["car_brand"],
            user_data[chat_id]["car_color"],
            user_data[chat_id]["car_number"],
            chat_id
        ))
    else:
        cursor.execute('''
            INSERT INTO drivers (user_id, username, name, phone, car_brand, car_color, car_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            chat_id,
            username,
            user_data[chat_id]["name"],
            user_data[chat_id]["phone"],
            user_data[chat_id]["car_brand"],
            user_data[chat_id]["car_color"],
            user_data[chat_id]["car_number"]
        ))

    conn.commit()
    conn.close()

    bot.send_message(chat_id, "✅ Ваши данные успешно сохранены!")


def update_driver_info(call):
    chat_id = call.message.chat.id
    bot.send_message(chat_id, "Введите ваше имя:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_driver_name)


@bot.message_handler(func=lambda message: message.chat.id == admin_chat_id and message.text == "Все водители")
def show_all_drivers(message):
    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, name, car_brand FROM drivers')
    drivers = cursor.fetchall()
    conn.close()

    if not drivers:
        bot.send_message(message.chat.id, "Водителей нет в базе данных.")
        return

    markup = InlineKeyboardMarkup()
    for driver in drivers:
        user_id, name, car_brand = driver
        markup.add(InlineKeyboardButton(f"{name} ({car_brand})",
                                        callback_data=f"driver_{user_id}"))

    bot.send_message(message.chat.id, "Список всех водителей:", reply_markup=markup)


def show_driver_details(call):
    chat_id = call.message.chat.id
    user_id = call.data.split("_")[1]

    conn = sqlite3.connect('users_orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM drivers WHERE user_id = ?', (user_id,))
    driver = cursor.fetchone()
    conn.close()

    if not driver:
        bot.send_message(chat_id, "Ошибка: Водитель не найден.")
        return

    driver_info = (
        f"🚖 *Информация о водителе:*\n"
        f"👤 Юзернейм: @{driver[1]}\n"
        f"👤 Имя: {driver[2]}\n"
        f"📞 Телефон: {driver[3]}\n"
        f"🚗 Марка машины: {driver[4]}\n"
        f"🎨 Цвет машины: {driver[6]}\n"
        f"🔢 Гос номер: {driver[5]}"
    )
    bot.send_message(chat_id, driver_info, parse_mode="Markdown")




##############################################
# Команда /order для админа
##############################################
@bot.message_handler(commands=['order'])
def admin_order_info(message):
    if message.chat.id != admin_chat_id:
        bot.send_message(message.chat.id, "❌ Эта команда доступна только администраторам.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Укажите номер заявки. Пример: /order FB7QNFB3")
        return

    order_id = parts[1].strip()
    process_admin_order_request(message, order_id)


def process_admin_order_request(message, order_id):
    orders = sheet.get_all_values()
    order = next((o for o in orders if o[0] == order_id), None)
    if not order:
        bot.send_message(message.chat.id, f"❌ Заявка с номером {order_id} не найдена.")
        return

    summary = (
        f"📋 *Детали заявки №{order[0]}*\n\n"
        f"🚖 *Водитель:* {order[1]}\n"
        f"👤 *Заказчик:* {order[2]}\n"
        f"📅 *В аэропорт/Из аэропорта:* {order[3]}\n"
        f"📅 *Дата:* {order[4]}\n"
        f"⏰ *Подача в:* {order[5]}\n"
        f"⏰ *Время рейса:* {order[6]}\n"
        f"✈️ *Номер рейса:* {order[7]}\n"
        f"📍 *Адрес отправления:* {order[8]}\n"
        f"📍 *Адрес прибытия:* {order[9]}\n"
        f"🧑‍🤝‍🧑 *Кол-во пассажиров:* {order[10]}\n"
        f"👶🏻 *Кол-во детей:* {order[11]}\n"
        f"👤 *ФИО:* {order[12]}\n"
        f"📞 *Телефон:* {order[13]}\n"
        f"ℹ️ *Откуда узнали:* {order[14]}\n"
        f"🚗 *Тариф:* {order[15]}\n"
        f"🏎️ *Платка:* {order[16]}\n"
        f"💺 *Кресло:* {order[17]}"
    )

    markup = InlineKeyboardMarkup()
    confirm_button = InlineKeyboardButton("✅ Подтверждено", callback_data=f"admin_confirm_{order_id}")
    delete_button = InlineKeyboardButton("❌ Удалить заявку", callback_data=f"admin_delete_{order_id}")
    attach_driver_button = InlineKeyboardButton("🚖 Прикрепить водителя", callback_data=f"attach_driver_{order_id}")
    notify_button = InlineKeyboardButton("🔔 Оповестить клиента", callback_data=f"notify_{order_id}")
    generate_message_button = InlineKeyboardButton("📩 Сформировать сообщение", callback_data=f"generate_message_{order_id}")

    markup.add(confirm_button, attach_driver_button)
    markup.add(notify_button, delete_button)
    markup.add(generate_message_button)

    bot.send_message(message.chat.id, summary, parse_mode="Markdown", reply_markup=markup)


##############################################
# Валидация полей
##############################################
def validate_phone_number(phone: str) -> bool:
    return bool(re.fullmatch(r"\d{11}", phone))

def validate_passenger_count(num_str: str) -> bool:
    if not num_str.isdigit():
        return False
    value = int(num_str)
    return 1 <= value <= 10

def validate_children_count(num_str: str) -> bool:
    if not num_str.isdigit():
        return False
    value = int(num_str)
    return 0 <= value <= 10

def validate_fio(fio: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Zа-яА-Я\s]+", fio.strip()))

def validate_referral(ref: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Zа-яА-Я\s]+", ref.strip()))


##############################################
# Блок редактирования тарифа/платки/кресла
##############################################
def edit_tariff_callback(call):
    chat_id = call.message.chat.id
    # Show available tariffs again or handle some logic
    # (left here as example if you prefer a separate approach)
    try:
        passengers = int(user_data[chat_id][7])
    except ValueError:
        passengers = 1
    available_tariffs = {}
    for key, value in tariffs.items():
        if "3 пассажира" in value and passengers <= 3:
            available_tariffs[key] = value
        elif "4 пассажира" in value and passengers <= 4:
            available_tariffs[key] = value
        elif "7 пассажиров" in value and passengers <= 7:
            available_tariffs[key] = value
        elif "8 пассажиров" in value and passengers <= 8:
            available_tariffs[key] = value

    markup = InlineKeyboardMarkup()
    for tkey, tval in available_tariffs.items():
        markup.add(InlineKeyboardButton(tval, callback_data=f"edit_tariff_confirm_{tkey}"))

    markup.add(InlineKeyboardButton("❌ Отмена заполнения заявки", callback_data="cancel_application"))

    bot.send_message(chat_id, "🚘 Выберите новый тариф:", reply_markup=markup)


def confirm_edit_tariff(call):
    chat_id = call.message.chat.id
    tariff_key = call.data.split("edit_tariff_confirm_")[1]  # 'standard', etc.
    user_data[chat_id][12] = tariffs[tariff_key]
    finalize_edit_update_sheet(chat_id)


def confirm_edit_platka(call):
    chat_id = call.message.chat.id
    choice = call.data.split("edit_platka_confirm_")[1]
    user_data[chat_id][13] = choice
    finalize_edit_update_sheet(chat_id)


def confirm_edit_chair(call):
    chat_id = call.message.chat.id
    choice = call.data.split("edit_chair_confirm_")[1]
    user_data[chat_id][14] = choice
    finalize_edit_update_sheet(chat_id)


def finalize_edit_update_sheet(chat_id):
    data = user_data[chat_id]
    if len(data) < 16:
        bot.send_message(chat_id, "✅ Поле обновлено!")
        send_summary(chat_id)
    else:
        order_id = data[15]
        if update_google_sheets(order_id, data):
            bot.send_message(chat_id, "✅ Данные обновлены в таблице!")
        else:
            bot.send_message(chat_id, "❌ Ошибка при обновлении данных в таблице.")


##############################################
# Запуск бота
##############################################
if __name__ == "__main__":
    bot.polling(none_stop=True)