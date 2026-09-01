import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, ADMINISTRATOR
from aiogram.enums import ChatType

from database import async_session_maker
from models import Chat
from services.schedule_cache import schedule_cache
from keyboards import group_chat_settings_kb, group_chat_courses_kb, group_chat_groups_kb
from config import ADMIN_IDS, logger

router = Router()


async def is_user_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Проверка прав администратора в чате (или супер-админа бота)."""
    if user_id in ADMIN_IDS:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ("creator", "administrator")
    except Exception as e:
        logger.warning(f"Не удалось проверить права {user_id} в чате {chat_id}: {e}")
        return False


# 1. Автоматическая миграция обычной группы в супергруппу (Telegram меняет ID чата)
@router.message(F.migrate_to_chat_id)
async def on_group_migrated(message: Message):
    old_id = message.chat.id
    new_id = message.migrate_to_chat_id
    if not new_id:
        return

    async with async_session_maker() as session:
        old_chat = await session.get(Chat, old_id)
        new_chat = await session.get(Chat, new_id)

        if old_chat and not new_chat:
            new_chat = Chat(
                chat_id=new_id,
                title=message.chat.title or old_chat.title,
                group_id=old_chat.group_id,
                is_active=old_chat.is_active,
                notifications_enabled=old_chat.notifications_enabled,
                change_notifications_enabled=old_chat.change_notifications_enabled,
                created_at=old_chat.created_at,
            )
            session.add(new_chat)
            await session.delete(old_chat)
            await session.commit()
            logger.info(f"🔄 Беседа успешно перенесена с ID {old_id} на супергруппу ID {new_id}")
        elif old_chat and new_chat:
            new_chat.group_id = old_chat.group_id
            new_chat.is_active = old_chat.is_active
            new_chat.notifications_enabled = old_chat.notifications_enabled
            new_chat.change_notifications_enabled = old_chat.change_notifications_enabled
            await session.delete(old_chat)
            await session.commit()
            logger.info(f"🔄 Данные беседы {old_id} объединены с супергруппой {new_id}")


GROUPHELP_TEXT = (
    "📖 <b>Инструкция по настройке бота в беседе группы:</b>\n\n"
    "1️⃣ <b>Добавьте бота в беседу</b> вашей группы или подгруппы.\n"
    "2️⃣ <b>Сделайте бота администратором чата</b> (чтобы бот мог читать вопросы к нему без упоминания через @bot).\n"
    "3️⃣ <b>Настройте группу:</b>\n"
    "• Отправьте команду <code>/chat_settings</code>\n"
    "• Нажмите <b>«🎓 Установить группу беседы»</b> и выберите курс и группу (например, <i>2-41</i>).\n\n"
    "⚡ <b>Как обращаться к боту в беседе:</b>\n"
    "В беседах бот отвечает только на сообщения, начинающиеся со слова <b>«Бот»</b>:\n"
    "• <b>«Бот»</b> — мгновенная проверка связи (ответит <i>«Летаю! 🦅»</i>)\n"
    "• <b>«Бот что завтра?»</b>, <b>«Бот 1-41 неделя»</b>, <b>«Бот чо у 2-42 в чт»</b>\n"
    "• <b>«Бот где Гричик?»</b>, <b>«Бот какая 2 пара?»</b>, <b>«Бот отработка по химии»</b>\n\n"
    "🔔 <b>Автоматические уведомления:</b>\n"
    "• В <b>07:45</b> бот присылает карточку расписания на день прямо в беседу.\n"
    "• При любых изменениях пар на сайте деканата бот мгновенно отправит карточку с изменениями!"
)


@router.message(Command("grouphelp"))
async def cmd_grouphelp(message: Message):
    await message.answer(GROUPHELP_TEXT)


# 2. Приветствие при добавлении бота в чат или выдаче прав админа
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> (MEMBER | ADMINISTRATOR)))
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER >> ADMINISTRATOR))
async def on_bot_added_to_chat(event: ChatMemberUpdated, bot: Bot):
    chat = event.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat.id)
        if not chat_obj:
            chat_obj = Chat(chat_id=chat.id, title=chat.title)
            session.add(chat_obj)
        else:
            chat_obj.title = chat.title
        await session.commit()

    welcome_text = (
        f"👋 <b>Всем привет! Я бот расписания Биофака БГУ</b>\n\n"
        f"Чтобы я мог присылать расписание и отвечать на ваши вопросы, администратору чата нужно задать группу:\n\n"
        f"1️⃣ Нажмите кнопку <b>«⚙️ Настройки беседы»</b> ниже (или отправьте <code>/chat_settings</code>)\n"
        f"2️⃣ Выберите курс и номер группы\n"
        f"3️⃣ В беседе задавайте вопросы вида: <b>«Бот что завтра?»</b> или <b>«Бот 1-41 неделя»</b> ✨"
    )

    kb = group_chat_settings_kb(
        chat.id, 
        is_active=True, 
        notifications_enabled=True, 
        change_notifications_enabled=True
    )
    await bot.send_message(chat_id=chat.id, text=welcome_text, reply_markup=kb)


# 3. Открытие панели настроек беседы
@router.message(Command("chat_settings"))
@router.message(Command("groupsettings"))
async def cmd_chat_settings(message: Message, bot: Bot):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("⚠️ Эта команда предназначена только для бесед (групповых чатов)!")
        return

    is_admin = await is_user_chat_admin(bot, message.chat.id, message.from_user.id)
    if not is_admin:
        await message.reply("⛔ <b>Настройки беседы доступны только администраторам чата!</b>")
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, message.chat.id)
        if not chat_obj:
            chat_obj = Chat(chat_id=message.chat.id, title=message.chat.title)
            session.add(chat_obj)
            await session.commit()

    group = schedule_cache.get_group_by_id(chat_obj.group_id) if chat_obj.group_id else None
    group_str = f"{group.course}-{group.number} ({group.name})" if group else "⚠️ <i>Не выбрана</i>"

    text = (
        f"⚙️ <b>Панель управления беседой:</b>\n\n"
        f"💬 Чат: <b>{html.escape(message.chat.title or 'Беседа')}</b>\n"
        f"🎓 Привязанная группа: <b>{group_str}</b>\n\n"
        f"<b>Параметры работы:</b>\n"
        f"• 🗣 Ответы на «Бот ...»: <b>{'Включены 🟢' if chat_obj.is_active else 'Выключены 🔴'}</b>\n"
        f"• 🌅 Утренний дайджест (07:45): <b>{'Включен 🟢' if chat_obj.notifications_enabled else 'Выключен 🔴'}</b>\n"
        f"• ⚡ Алерты об изменениях: <b>{'Включены 🟢' if chat_obj.change_notifications_enabled else 'Выключены 🔴'}</b>\n\n"
        f"<i>Управлять кнопками могут только администраторы чата:</i>"
    )

    kb = group_chat_settings_kb(
        message.chat.id, 
        is_active=chat_obj.is_active, 
        notifications_enabled=chat_obj.notifications_enabled,
        change_notifications_enabled=chat_obj.change_notifications_enabled
    )
    await message.answer(text, reply_markup=kb)


# 4. Переключение чтения сообщений «Бот ...» (ВКЛ / ВЫКЛ)
@router.callback_query(F.data.startswith("g_toggle_act_"))
async def callback_toggle_chat_active(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[3])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Менять настройки могут только администраторы чата!", show_alert=True)
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat_id)
        if chat_obj:
            chat_obj.is_active = not chat_obj.is_active
            await session.commit()
            is_act = chat_obj.is_active
            notif = chat_obj.notifications_enabled
            chg = chat_obj.change_notifications_enabled
        else:
            is_act, notif, chg = True, True, True

    await callback.message.edit_reply_markup(
        reply_markup=group_chat_settings_kb(chat_id, is_act, notif, chg)
    )
    status_str = "включены 🟢" if is_act else "выключены 🔴"
    await callback.answer(f"Ответы на «Бот ...» {status_str}!")


# 5. Переключение утренних уведомлений 07:45 (ВКЛ / ВЫКЛ)
@router.callback_query(F.data.startswith("g_toggle_not_"))
async def callback_toggle_chat_notifications(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[3])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Менять настройки могут только администраторы чата!", show_alert=True)
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat_id)
        if chat_obj:
            chat_obj.notifications_enabled = not chat_obj.notifications_enabled
            await session.commit()
            is_act = chat_obj.is_active
            notif = chat_obj.notifications_enabled
            chg = chat_obj.change_notifications_enabled
        else:
            is_act, notif, chg = True, True, True

    await callback.message.edit_reply_markup(
        reply_markup=group_chat_settings_kb(chat_id, is_act, notif, chg)
    )
    status_str = "включена 🟢" if notif else "выключена 🔴"
    await callback.answer(f"Утренняя рассылка (07:45) {status_str}!")


# 6. Переключение уведомлений об изменениях в расписании (ВКЛ / ВЫКЛ)
@router.callback_query(F.data.startswith("g_toggle_chg_"))
async def callback_toggle_chat_changes(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[3])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Менять настройки могут только администраторы чата!", show_alert=True)
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat_id)
        if chat_obj:
            chat_obj.change_notifications_enabled = not chat_obj.change_notifications_enabled
            await session.commit()
            is_act = chat_obj.is_active
            notif = chat_obj.notifications_enabled
            chg = chat_obj.change_notifications_enabled
        else:
            is_act, notif, chg = True, True, True

    await callback.message.edit_reply_markup(
        reply_markup=group_chat_settings_kb(chat_id, is_act, notif, chg)
    )
    status_str = "включены 🟢" if chg else "выключены 🔴"
    await callback.answer(f"Оповещения об изменениях расписания {status_str}!")


# 7. Меню выбора курса для беседы
@router.callback_query(F.data.startswith("g_pick_crs_"))
async def callback_pick_course_for_chat(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[3])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Только администраторы могут менять группу чата!", show_alert=True)
        return

    await callback.message.edit_text(
        "🎓 <b>Выберите курс для беседы:</b>", 
        reply_markup=group_chat_courses_kb(chat_id)
    )
    await callback.answer()


# 8. Меню выбора группы выбранного курса
@router.callback_query(F.data.startswith("g_crs_"))
async def callback_select_course_for_chat(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    course = int(parts[3])

    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Только администраторы могут менять группу чата!", show_alert=True)
        return

    groups = schedule_cache.get_all_groups_for_course(course)
    if not groups:
        await callback.answer(f"⚠️ Группы {course} курса не найдены в базе!", show_alert=True)
        return

    await callback.message.edit_text(
        f"🎓 Выбран: <b>{course} курс</b>\nВыберите академическую группу вашей беседы:",
        reply_markup=group_chat_groups_kb(chat_id, groups)
    )
    await callback.answer()


# 9. Сохранение группы беседы
@router.callback_query(F.data.startswith("g_setgrp_"))
async def callback_save_group_for_chat(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    group_id = int(parts[3])

    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Только администраторы могут менять группу чата!", show_alert=True)
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat_id)
        if chat_obj:
            chat_obj.group_id = group_id
            await session.commit()
            is_act = chat_obj.is_active
            notif = chat_obj.notifications_enabled
            chg = chat_obj.change_notifications_enabled
        else:
            is_act, notif, chg = True, True, True

    group = schedule_cache.get_group_by_id(group_id)
    grp_name = f"{group.course}-{group.number} ({group.name})" if group else "Выбрана"

    await callback.message.edit_text(
        f"✅ <b>Группа беседы успешно установлена:</b> <code>{grp_name}</code>\n\n"
        f"Теперь любой участник может писать:\n"
        f"• <i>«Бот что завтра?»</i>\n"
        f"• <i>«Бот 1-41 неделя»</i>\n"
        f"• <i>«Бот какая 1 пара в пн?»</i> ✨",
        reply_markup=group_chat_settings_kb(chat_id, is_act, notif, chg)
    )
    await callback.answer("Группа успешно сохранена!")


# 10. Возврат в главное меню настроек беседы
@router.callback_query(F.data.startswith("g_back_"))
async def callback_back_to_chat_settings(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[2])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Доступно только администраторам!", show_alert=True)
        return

    async with async_session_maker() as session:
        chat_obj = await session.get(Chat, chat_id)

    is_act = chat_obj.is_active if chat_obj else True
    notif = chat_obj.notifications_enabled if chat_obj else True
    chg = chat_obj.change_notifications_enabled if chat_obj else True
    group = schedule_cache.get_group_by_id(chat_obj.group_id) if (chat_obj and chat_obj.group_id) else None
    group_str = f"{group.course}-{group.number} ({group.name})" if group else "⚠️ <i>Не выбрана</i>"

    text = (
        f"⚙️ <b>Панель управления беседой:</b>\n\n"
        f"🎓 Привязанная группа: <b>{group_str}</b>\n\n"
        f"<b>Параметры работы:</b>\n"
        f"• 🗣 Ответы на «Бот ...»: <b>{'Включены 🟢' if is_act else 'Выключены 🔴'}</b>\n"
        f"• 🌅 Утренняя рассылка (07:45): <b>{'Включен 🟢' if notif else 'Выключен 🔴'}</b>\n"
        f"• ⚡ Уведы об изменениях: <b>{'Включены 🟢' if chg else 'Выключены 🔴'}</b>"
    )

    await callback.message.edit_text(
        text, 
        reply_markup=group_chat_settings_kb(chat_id, is_act, notif, chg)
    )
    await callback.answer()


# 11. Закрытие меню
@router.callback_query(F.data.startswith("g_close_"))
async def callback_close_group_settings(callback: CallbackQuery, bot: Bot):
    chat_id = int(callback.data.split("_")[2])
    if not await is_user_chat_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("⛔ Доступно только администраторам!", show_alert=True)
        return

    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text("⚙️ Настройки сохранены")
    await callback.answer()