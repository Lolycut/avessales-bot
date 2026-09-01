import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import async_session_maker
from models import User
from services.schedule_cache import schedule_cache
from keyboards import main_menu_kb, settings_inline_kb, settings_subgroups_kb, courses_kb
from handlers.start import RegistrationFSM

router = Router()


class SettingsFSM(StatesGroup):
    changing_nickname = State()


FAQ_TEXT = (
    "📖 <b>Справка и возможности бота</b>\n\n"
    "<b>📱 Кнопки главного меню:</b>\n"
    "• <b>📅 Сегодня / 📆 Завтра</b> — расписание вашей группы на выбранный день в виде таблицы\n"
    "• <b>⚡ Какая пара сейчас?</b> — активная пара в данный момент или ближайшая следующая. Показывает аудиторию, преподавателя и метку <code>⚠️ ВЫЕЗД!</code>, если корпус не на Курчатова 10\n"
    "• <b>🗓 На неделю</b> — расписание на всю неделю с кнопками переключения <code>◀️ Пред.</code> и <code>След. ▶️</code>\n"
    "• <b>🔔 Уведы</b> — быстрое переключение утренней рассылки (07:45)\n"
    "• <b>⚙️ Настройки</b> — тонкая настройка утренних уведов и алертов об изменениях пар, смена подгруппы и имени\n\n"
    "<b>💬 Поиск на естественном языке (текстом):</b>\n"
    "Вы можете писать боту обычным языком:\n"
    "• <i>«что во вторник?»</i>, <i>«1-41 неделя»</i>, <i>«чо у 2-42 в чт»</i>\n"
    "• <i>«какая 2 пара во вторник?»</i>, <i>«3 пара завтра»</i>\n"
    "• <i>«след неделя»</i>, <i>«пары Гричика»</i>\n"
)

TERMS_TEXT = (
    "📜 <b>Пользовательское соглашение и политика конфиденциальности</b>\n\n"
    "⚠️ <b>1. Неофициальный статус проекта (Дисклеймер):</b>\n"
    "• Данный бот является <b>независимым студенческим проектом</b> и <b>НЕ является официальным сервисом</b> Белорусского государственного университета (БГУ) или биологического факультета\n"
    "• Все данные об учебных занятиях и расписании берутся в автоматическом режиме из открытых общедоступных источников (официального сайта <code>bio.bsu.by</code>)\n\n"
    "💾 <b>2. Какие данные мы собираем и храним:</b>\n"
    "Для корректной работы сервиса в базе данных сохраняются исключительно технические параметры:\n"
    "• <code>Telegram ID</code> и публичный <code>username</code> (для идентификации и отправки сообщений)\n"
    "• Указанное вами имя или никнейм\n"
    "• Выбранный курс, номер группы и подгруппа\n"
    "• Настройки уведомлений (утренние дайджесты и алерты об изменениях)\n"
    "• <i>Для бесед (групповых чатов):</i> ID чата, название и привязанная академическая группа\n"
    "🔒 <i>Бот <b>НЕ</b> собирает, не запрашивает и не хранит пароли, личные переписки, номера телефонов, геолокацию или платежные данные.</i>\n\n"
    "⚖️ <b>3. Ограничение ответственности:</b>\n"
    "• Сервис предоставляется по принципу <b>«как есть» («as is»)</b>\n"
    "• В случае спорных моментов первоисточником всегда является официальное распоряжение деканата факультета"
)


def render_settings_text(user: User, group_name: str, course_str: str) -> str:
    safe_name = html.escape(user.first_name or "Студент")
    safe_group = html.escape(group_name)
    sub_title = f"{user.subgroup}-я подгруппа" if user.subgroup else "Вся группа"

    morning_status = "Включена 🟢" if user.notifications_enabled else "Выключена 🔴"
    changes_status = "Включены 🟢" if user.change_notifications_enabled else "Выключены 🔴"

    return (
        f"⚙️ <b>Личный кабинет и настройки</b>\n\n"
        f"👤 Ваше имя: <b>{safe_name}</b>\n"
        f"🎓 Курс: <b>{course_str}</b>\n"
        f"👥 Группа: <b>{safe_group}</b>\n"
        f"🔢 Подгруппа: <b>{sub_title}</b>\n\n"
        f"<b>🔔 Управление уведомлениями:</b>\n"
        f"• 🌅 Утренний дайджест (07:45): <b>{morning_status}</b>\n"
        f"• ⚡ Изменения в расписании: <b>{changes_status}</b>\n\n"
        f"<i>Используйте кнопки ниже для переключения:</i>"
    )


@router.message(Command("help"))
@router.message(Command("faq"))
async def cmd_faq(message: Message):
    await message.answer(FAQ_TEXT)


@router.callback_query(F.data == "show_faq")
async def callback_show_faq(callback: CallbackQuery):
    await callback.message.answer(FAQ_TEXT)
    await callback.answer()


@router.message(Command("terms"))
@router.message(Command("privacy"))
@router.message(Command("agreement"))
async def cmd_terms(message: Message):
    await message.answer(TERMS_TEXT)


@router.callback_query(F.data == "show_terms")
async def callback_show_terms(callback: CallbackQuery):
    await callback.message.answer(TERMS_TEXT)
    await callback.answer()


# Быстрое переключение через кнопку клавиатуры
@router.message(F.text.contains("Уведы"))
async def toggle_notifications_quick(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        user.notifications_enabled = not user.notifications_enabled
        new_status = user.notifications_enabled
        await session.commit()

    status_text = "включена 🔔" if new_status else "выключена 🔕"
    await message.answer(
        f"Утренняя рассылка в 07:45 успешно <b>{status_text}</b>!\n\n"
        f"💡 <i>Настроить уведомления об изменениях расписания можно в <b>⚙️ Настройки</b></i>", 
        reply_markup=main_menu_kb(new_status)
    )


# Главное меню настроек
@router.message(F.text.contains("Настройки"))
async def open_settings(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала пройдите регистрацию: /start")
            return

    group = schedule_cache.get_group_by_id(user.group_id) if user.group_id else None
    group_name = f"{group.number} ({group.name})" if group else "Не выбрана"
    course_str = f"{group.course} курс" if group else "—"

    text = render_settings_text(user, group_name, course_str)
    await message.answer(
        text, 
        reply_markup=settings_inline_kb(user.notifications_enabled, user.change_notifications_enabled)
    )


# Переключение утренней рассылки (07:45)
@router.callback_query(F.data == "toggle_user_morning_notif")
async def callback_toggle_user_morning_notif(callback: CallbackQuery):
    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        user.notifications_enabled = not user.notifications_enabled
        await session.commit()

        group = schedule_cache.get_group_by_id(user.group_id) if user.group_id else None
        group_name = f"{group.number} ({group.name})" if group else "Не выбрана"
        course_str = f"{group.course} курс" if group else "—"

        text = render_settings_text(user, group_name, course_str)
        kb = settings_inline_kb(user.notifications_enabled, user.change_notifications_enabled)

    await callback.message.edit_text(text, reply_markup=kb)
    status_str = "включена 🟢" if user.notifications_enabled else "выключена 🔴"
    await callback.answer(f"Утренняя рассылка {status_str}!")


# Переключение уведомлений об изменениях в парах
@router.callback_query(F.data == "toggle_user_changes_notif")
async def callback_toggle_user_changes_notif(callback: CallbackQuery):
    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        user.change_notifications_enabled = not user.change_notifications_enabled
        await session.commit()

        group = schedule_cache.get_group_by_id(user.group_id) if user.group_id else None
        group_name = f"{group.number} ({group.name})" if group else "Не выбрана"
        course_str = f"{group.course} курс" if group else "—"

        text = render_settings_text(user, group_name, course_str)
        kb = settings_inline_kb(user.notifications_enabled, user.change_notifications_enabled)

    await callback.message.edit_text(text, reply_markup=kb)
    status_str = "включены 🟢" if user.change_notifications_enabled else "выключены 🔴"
    await callback.answer(f"Оповещения об изменениях расписания {status_str}!")


@router.callback_query(F.data == "change_subgroup")
async def callback_change_subgroup(callback: CallbackQuery):
    await callback.message.edit_text("Выберите новую подгруппу:", reply_markup=settings_subgroups_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("set_subgroup_"))
async def callback_save_subgroup(callback: CallbackQuery):
    subgroup_val = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        if user:
            user.subgroup = subgroup_val if subgroup_val != 0 else None
            await session.commit()
    
    sub_title = f"{subgroup_val}-я подгруппа" if subgroup_val != 0 else "Вся группа"
    await callback.message.edit_text(f"✅ Подгруппа успешно изменена на: <b>{sub_title}</b>!")
    await callback.answer()


@router.callback_query(F.data == "change_nickname")
async def callback_change_nickname(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте новое имя текстовым сообщением:")
    await state.set_state(SettingsFSM.changing_nickname)
    await callback.answer()


@router.message(SettingsFSM.changing_nickname, F.text)
async def process_new_nickname(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if not new_name:
        await message.answer("Имя не может быть пустым. Попробуйте еще раз:")
        return

    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if user:
            user.first_name = new_name
            await session.commit()

    await state.clear()
    safe_name = html.escape(new_name)
    await message.answer(
        f"✅ Имя успешно изменено на: <b>{safe_name}</b>!",
        reply_markup=main_menu_kb(user.notifications_enabled if user else True)
    )


@router.message(SettingsFSM.changing_nickname)
async def process_invalid_nickname(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте новое имя обычным текстовым сообщением:")


@router.callback_query(F.data == "restart_reg")
async def callback_restart_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 <b>Перерегистрация</b>\n\n<b>Шаг 1 из 4:</b> Выберите ваш <b>курс</b>:",
        reply_markup=courses_kb()
    )
    await state.set_state(RegistrationFSM.choosing_course)
    await callback.answer()