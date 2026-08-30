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
    "• <b>🔔 Уведы</b> — включает/выключает утреннюю рассылку пар в <b>07:45</b> по Минску\n"
    "• <b>⚙️ Настройки</b> — смена подгруппы, имени или повторный выбор группы\n\n"
    "<b>💬 Поиск на естественном языке (текстом):</b>\n"
    "Вы можете писать боту запросы обычной речью, даже с опечатками:\n"
    "• <i>«что во вторник?»</i>, <i>«пары в четверг»</i>, <i>«расписание на сб»</i>\n"
    "• <i>«какая 2 пара во вторник?»</i>, <i>«3 пара завтра»</i>\n"
    "• <i>«след неделя»</i>, <i>«в следующий понедельник»</i>\n\n"
    "<b>🔍 Поиск расписания ДРУГИХ групп:</b>\n"
    "Используйте формат <code>КУРС-ГРУППА</code>:\n"
    "• <i>«Что у 1-41 в чт?»</i> — расписание 41 группы 1 курса на четверг\n"
    "• <i>«2-42 на завтра»</i> — расписание 42 группы 2 курса на завтра\n"
    "• <i>«1-41 на неделю»</i> — недельное расписание чужой группы\n"
    "• <i>«Какая 1 пара у 3-41 в пятницу»</i> — конкретная пара чужой группы\n\n"
    "<b>🔍 Поиск ПРЕПОДАВАТЕЛЕЙ:</b>\n"
    "Вы можете искать преподавателей по их фамилии:\n"
    "• <i>«/teachers»</i> — показывает список всех найденных в базе преподавателей с подсказками по поиску\n"
    "• <i>«Кукулянская», «Где Рудакевич?», «Расписание Гричик», «пары Сауткина»</i> — поиск по фамилии\n"
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
    "• Настройки уведомлений (вкл/выкл утренней рассылки)\n"
    "• <i>Для бесед (групповых чатов):</i> ID чата, название и привязанная академическая группа\n"
    "🔒 <i>Бот <b>НЕ</b> собирает, не запрашивает и не хранит пароли, личные переписки, номера телефонов, геолокацию или платежные данные. Данные не передаются третьим лицам.</i>\n\n"
    "⚖️ <b>3. Ограничение ответственности:</b>\n"
    "• Сервис предоставляется по принципу <b>«как есть» («as is»)</b> на безвозмездной основе\n"
    "• Разработчики не несут ответственности за возможные неточности, внезапные изменения в расписании со стороны деканата/кафедр, технические сбои сайта факультета или опоздания на занятия\n"
    "• В случае спорных моментов и изменений первоисточником всегда является официальное распоряжение деканата факультета\n\n"
    "🗑 <b>4. Удаление данных:</b>\n"
    "Если вы хотите прекратить использование бота и удалить свои данные из базы, достаточно заблокировать бота или отключить уведомления в настройках"
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


@router.message(F.text.contains("Уведы"))
async def toggle_notifications(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        user.notifications_enabled = not user.notifications_enabled
        new_status = user.notifications_enabled
        await session.commit()

    status_text = "включены 🔔" if new_status else "выключены 🔕"
    await message.answer(f"Уведомления успешно <b>{status_text}</b>!", reply_markup=main_menu_kb(new_status))


@router.message(F.text.contains("Настройки"))
async def open_settings(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала пройдите регистрацию: /start")
            return

    group = schedule_cache.get_group_by_id(user.group_id) if user.group_id else None
    group_name = group.name if group else "Не выбрана"
    course_str = f"{group.course} курс" if group else "—"

    safe_name = html.escape(user.first_name or "Студент")
    safe_group = html.escape(group_name)

    text = (
        f"⚙️ <b>Личный кабинет и настройки</b>\n\n"
        f"👤 Ваше имя: <b>{safe_name}</b>\n"
        f"🎓 Курс: <b>{course_str}</b>\n"
        f"👥 Группа: <b>{group.number if group else '—'} ({safe_group})</b>\n"
        f"🔢 Подгруппа: <b>{user.subgroup or 'Вся группа'}</b>\n"
        f"🔔 Уведомления: <b>{'Включены' if user.notifications_enabled else 'Выключены'}</b>\n\n"
        f"Что хотите изменить?"
    )
    await message.answer(text, reply_markup=settings_inline_kb())


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
        reply_markup=main_menu_kb(user.notifications_enabled if user else True),
    )


@router.message(SettingsFSM.changing_nickname)
async def process_invalid_nickname(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте новое имя обычным текстовым сообщением:")


@router.callback_query(F.data == "restart_reg")
async def callback_restart_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 <b>Перерегистрация</b>\n\n<b>Шаг 1 из 4:</b> Выберите ваш <b>курс</b>:", reply_markup=courses_kb()
    )
    await state.set_state(RegistrationFSM.choosing_course)
    await callback.answer()
