from datetime import date, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb(notifications: bool = True) -> ReplyKeyboardMarkup:
    notif_btn = "🔔 Уведы: ВКЛ" if notifications else "🔕 Уведы: ВЫКЛ"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="⚡ Какая пара сейчас?"), KeyboardButton(text="🗓 На неделю")],
            [KeyboardButton(text=notif_btn), KeyboardButton(text="⚙️ Настройки")]
        ],
        resize_keyboard=True
    )

def settings_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Сменить подгруппу", callback_data="change_subgroup")],
            [InlineKeyboardButton(text="✏️ Изменить никнейм", callback_data="change_nickname")],
            [InlineKeyboardButton(text="🔄 Сменить группу (перерегистрация)", callback_data="restart_reg")],
            [InlineKeyboardButton(text="ℹ️ Справка и FAQ", callback_data="show_faq")]
        ]
    )

def courses_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ курс", callback_data="sel_course_1"),
                InlineKeyboardButton(text="2️⃣ курс", callback_data="sel_course_2")
            ],
            [
                InlineKeyboardButton(text="3️⃣ курс", callback_data="sel_course_3"),
                InlineKeyboardButton(text="4️⃣ курс", callback_data="sel_course_4")
            ]
        ]
    )

def reg_subgroups_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1-я подгруппа", callback_data="reg_subgroup_1"),
                InlineKeyboardButton(text="2-я подгруппа", callback_data="reg_subgroup_2")
            ],
            [InlineKeyboardButton(text="Вся группа (без деления)", callback_data="reg_subgroup_0")]
        ]
    )

def settings_subgroups_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1-я подгруппа", callback_data="set_subgroup_1"),
                InlineKeyboardButton(text="2-я подгруппа", callback_data="set_subgroup_2")
            ],
            [InlineKeyboardButton(text="Вся группа (без деления)", callback_data="set_subgroup_0")]
        ]
    )

def week_nav_kb(current_monday: date) -> InlineKeyboardMarkup:
    prev_monday = current_monday - timedelta(days=7)
    next_monday = current_monday + timedelta(days=7)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Пред. неделя", 
                    callback_data=f"week_date_{prev_monday.strftime('%Y-%m-%d')}"
                ),
                InlineKeyboardButton(
                    text="След. неделя ▶️", 
                    callback_data=f"week_date_{next_monday.strftime('%Y-%m-%d')}"
                )
            ]
        ]
    )