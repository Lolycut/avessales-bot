import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatType

from database import async_session_maker
from models import User
from services.schedule_cache import schedule_cache
from keyboards import main_menu_kb, courses_kb, reg_subgroups_kb
from config import get_minsk_now

router = Router()


class RegistrationFSM(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_subgroup = State()
    entering_nickname = State()


# Регистрация доступна только в личных сообщениях
@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if user and user.group_id:
            safe_name = html.escape(user.first_name or "Студент")
            await message.answer(
                f"Рад снова видеть, <b>{safe_name}</b>! Что интересует по расписанию?",
                reply_markup=main_menu_kb(user.notifications_enabled),
            )
            return

    await message.answer(
        "👋 <b>Добро пожаловать в бота расписания Биофака БГУ!</b>\n\n<b>Шаг 1 из 4:</b> Выберите ваш <b>курс</b>:",
        reply_markup=courses_kb(),
    )
    await state.set_state(RegistrationFSM.choosing_course)


@router.callback_query(RegistrationFSM.choosing_course, F.data.startswith("sel_course_"))
async def process_course(callback: CallbackQuery, state: FSMContext):
    course = int(callback.data.split("_")[2])
    await state.update_data(course=course)

    groups = schedule_cache.get_all_groups_for_course(course)

    buttons = [
        [InlineKeyboardButton(text=f"Гр. {g.number} • {g.name}", callback_data=f"sel_group_{g.id}")] for g in groups
    ]

    await callback.message.edit_text(
        f"Выбран: <b>{course} курс</b>\n\n<b>Шаг 2 из 4:</b> Выберите вашу группу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(RegistrationFSM.choosing_group)


@router.callback_query(RegistrationFSM.choosing_group, F.data.startswith("sel_group_"))
async def process_group(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[2])
    await state.update_data(group_id=group_id)

    group = schedule_cache.get_group_by_id(group_id)
    group_number = group.number if group else "?"

    await callback.message.edit_text(
        f"Выбрана: <b>Группа {group_number}</b>\n\n<b>Шаг 3 из 4:</b> Выберите вашу <b>подгруппу</b> (для языков/лаб):",
        reply_markup=reg_subgroups_kb(),
    )
    await state.set_state(RegistrationFSM.choosing_subgroup)


@router.callback_query(RegistrationFSM.choosing_subgroup, F.data.startswith("reg_subgroup_"))
async def process_subgroup(callback: CallbackQuery, state: FSMContext):
    subgroup = int(callback.data.split("_")[2])
    await state.update_data(subgroup=subgroup)

    default_name = callback.from_user.first_name or "Студент"
    sub_title = f"{subgroup}-я подгруппа" if subgroup != 0 else "Вся группа"

    await callback.message.edit_text(
        f"Подгруппа: <b>{sub_title}</b>\n\n"
        f"<b>Шаг 4 из 4:</b> Как к вам обращаться?\n"
        f"Отправьте имя текстом в чат или нажмите кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Оставить «{default_name}»", callback_data="use_default_name")]
            ]
        ),
    )
    await state.set_state(RegistrationFSM.entering_nickname)


@router.callback_query(RegistrationFSM.entering_nickname, F.data == "use_default_name")
async def process_default_nickname(callback: CallbackQuery, state: FSMContext):
    name = callback.from_user.first_name or "Студент"
    await save_user_registration(callback.from_user.id, callback.from_user.username, name, state, callback.message)
    await callback.answer()


@router.message(RegistrationFSM.entering_nickname, F.text)
async def process_custom_nickname(message: Message, state: FSMContext):
    name = message.text.strip() or (message.from_user.first_name or "Студент")
    await save_user_registration(message.from_user.id, message.from_user.username, name, state, message)


@router.message(RegistrationFSM.entering_nickname)
async def process_invalid_nickname(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте ваше имя обычным текстовым сообщением:")


async def save_user_registration(
    user_id: int, username: str | None, nickname: str, state: FSMContext, target_msg: Message
):
    data = await state.get_data()
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(telegram_id=user_id, registered_at=get_minsk_now())
            session.add(user)

        user.username = username
        user.first_name = nickname

        if "group_id" in data:
            user.group_id = data["group_id"]
        if "subgroup" in data:
            subgroup_val = data["subgroup"]
            user.subgroup = subgroup_val if subgroup_val != 0 else None

        user.notifications_enabled = True
        await session.commit()

    await state.clear()
    safe_nick = html.escape(nickname)
    await target_msg.answer(f"🎉 <b>Отлично, {safe_nick}! Регистрация завершена!</b>", reply_markup=main_menu_kb(True))
