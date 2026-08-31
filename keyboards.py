from datetime import date, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from services.dto import GroupDTO


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
            [InlineKeyboardButton(text="ℹ️ Справка и FAQ", callback_data="show_faq")],
            [InlineKeyboardButton(text="📜 Соглашение и конфиденциальность", callback_data="show_terms")]
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
            ],
            [
                InlineKeyboardButton(text="5️⃣ курс", callback_data="sel_course_5")
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


# ==========================================
# Клавиатуры для беседы (группового чата)
# ==========================================

def group_chat_settings_kb(chat_id: int, is_active: bool, notifications_enabled: bool) -> InlineKeyboardMarkup:
    active_text = "💬 Ответы в чате: ВКЛ 🟢" if is_active else "💬 Ответы в чате: ВЫКЛ 🔴"
    notif_text = "🔔 Уведомления 07:45: ВКЛ 🟢" if notifications_enabled else "🔕 Уведомления 07:45: ВЫКЛ 🔴"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=active_text, callback_data=f"g_toggle_act_{chat_id}")],
            [InlineKeyboardButton(text=notif_text, callback_data=f"g_toggle_not_{chat_id}")],
            [InlineKeyboardButton(text="🎓 Установить группу беседы", callback_data=f"g_pick_crs_{chat_id}")],
            [InlineKeyboardButton(text="❌ Закрыть меню", callback_data=f"g_close_{chat_id}")]
        ]
    )


def group_chat_courses_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ курс", callback_data=f"g_crs_{chat_id}_1"),
                InlineKeyboardButton(text="2️⃣ курс", callback_data=f"g_crs_{chat_id}_2")
            ],
            [
                InlineKeyboardButton(text="3️⃣ курс", callback_data=f"g_crs_{chat_id}_3"),
                InlineKeyboardButton(text="4️⃣ курс", callback_data=f"g_crs_{chat_id}_4")
            ],
            [
                InlineKeyboardButton(text="5️⃣ курс", callback_data=f"g_crs_{chat_id}_5")
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"g_back_{chat_id}")]
        ]
    )


def group_chat_groups_kb(chat_id: int, groups: list[GroupDTO]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"Гр. {g.number} • {g.name}", callback_data=f"g_setgrp_{chat_id}_{g.id}")]
        for g in groups
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Выбрать другой курс", callback_data=f"g_pick_crs_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)