from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import async_session_maker
from models import User, Group
from keyboards import main_menu_kb, settings_inline_kb, settings_subgroups_kb, courses_kb
from handlers.start import RegistrationFSM

router = Router()


class SettingsFSM(StatesGroup):
    changing_nickname = State()


@router.message(F.text.contains("Уведы"))
async def toggle_notifications(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            return
        user.notifications_enabled = not user.notifications_enabled
        new_status = user.notifications_enabled
        await session.commit()

    status_text = "включены 🔔" if new_status else "выключены 🔕"
    await message.answer(
        f"Уведомления успешно <b>{status_text}</b>!", 
        reply_markup=main_menu_kb(new_status)
    )


@router.message(F.text.contains("Настройки"))
async def open_settings(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        group = await session.get(Group, user.group_id) if user.group_id else None
        group_name = group.name if group else "Не выбрана"

    text = (
        f"⚙️ <b>Личный кабинет и настройки</b>\n\n"
        f"👤 Ваше имя: <b>{user.first_name}</b>\n"
        f"👥 Группа: <b>{group.number if group else '—'} ({group_name})</b>\n"
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


@router.message(SettingsFSM.changing_nickname)
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
    await message.answer(
        f"✅ Имя успешно изменено на: <b>{new_name}</b>!",
        reply_markup=main_menu_kb(user.notifications_enabled if user else True)
    )


@router.callback_query(F.data == "restart_reg")
async def callback_restart_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 <b>Перерегистрация</b>\n\n<b>Шаг 1 из 4:</b> Выберите ваш <b>курс</b>:",
        reply_markup=courses_kb()
    )
    await state.set_state(RegistrationFSM.choosing_course)
    await callback.answer()