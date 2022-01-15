import asyncio
import json
import logging
import os
import pprint
import re
import xmlrpc.client

import aioredis
from aiotg import Bot

import keyboard
import settings
import utils
from webservices_xmlrpc import XMLRPCClient

logger = logging.getLogger(__name__)

if settings.BOT_PROXY_URL:
    bot = Bot(api_token=settings.BOT_TOKEN, proxy=settings.BOT_PROXY_URL)
else:
    bot = Bot(api_token=settings.BOT_TOKEN)


async def main():
    global pool
    pool = await aioredis.create_redis_pool(
        (settings.REDIS_HOST, settings.REDIS_PORT),
        encoding="utf-8",
        minsize=2,
        maxsize=4,
    )


def glpi_client():
    return XMLRPCClient(settings.API_BASE, settings.API_USER, settings.API_PASS)


async def glpi_api_call(method, sender_id, chat, **kwargs):
    """
    Function for calling GLPI Webservices plugin API methods

    :type method: str
    :type sender_id: int
    :type chat: message
    :type kwargs: Any
    :param method: API method name
    :param sender_id: ID of chat user
    :param chat: chat with bot
    :param kwargs: API method options
    :return: Result of API method call
    :rtype: dict or bool
    """
    session = await utils.get_user_field(pool, sender_id, "glpi_session")
    params = {"session": session, "id2name": True, **kwargs}
    glpi = glpi_client()

    try:
        # Equals to glpi.method(**params)
        res = getattr(glpi, method)(**params)
        if method == "doLogout":
            await reauth_msg(sender_id, chat)
        return res

    except xmlrpc.client.Fault as err:
        logger.error("FaultCode: %s, FaultString: %s", err.faultCode, err.faultString)
        if err.faultCode == 13:
            await reauth_msg(sender_id, chat)
        return False

    except xmlrpc.client.ProtocolError as err:
        logger.error(
            "URL: %s, headers: %s, Error code: %s, Error message: %s",
            err.url,
            err.headers,
            err.errcode,
            err.errmsg,
        )
        return "Что-то не так с сервером!"


async def reauth_msg(sender_id, chat):
    login_name = await utils.get_user_field(pool, sender_id, "glpi_name")
    markup = keyboard.LOGIN
    if login_name:
        markup["inline_keyboard"][0][0][
            "switch_inline_query_current_chat"
        ] = "{} ".format(login_name)
    text = "❗*Войди для продолжения работы*❗\n{}".format(settings.LOGIN_TEXT)
    if chat.message["from"]["is_bot"]:
        bot.edit_message_text(
            chat.message["chat"]["id"],
            chat.message["message_id"],
            text,
            parse_mode="Markdown",
            reply_markup=json.dumps(markup),
        )
    else:
        chat.send_text(text, parse_mode="Markdown", reply_markup=json.dumps(markup))


async def download_file(path, filename, file_id):
    tg_file = await bot.get_file(file_id)
    if not os.path.exists(path):
        os.makedirs(path)
    local_file = os.path.join(path, filename)

    async with bot.download_file(tg_file["file_path"]) as resp:
        with open(local_file, "wb") as fd:
            while True:
                chunk = await resp.content.read(1024)
                if not chunk:
                    break
                fd.write(chunk)
    return local_file


async def ticket_followup_add(chat, session, users_login, ticket_id):
    params = {
        "session": session,
        "ticket": ticket_id,
        "content": chat.message["text"],
        "users_login": users_login,
        "source": "Telegram",
    }
    glpi = glpi_client()
    res = glpi.addTicketFollowup(**params)
    if res:
        # pprint.pprint(res)
        followup = res["followups"][0]
        followup_fmt = settings.FOLLOWUP_ADDED.format(
            followup["tickets_id"], followup["date_mod"], followup["content"]
        )
        chat.delete_message(chat.message["reply_to_message"]["message_id"])
        chat.send_text(followup_fmt, parse_mode="HTML")


async def ticket_solution_add(chat, session, ticket_id):
    params = {
        "session": session,
        "ticket": ticket_id,
        "type": 8,
        "solution": chat.message["text"],
    }
    glpi = glpi_client()
    res = glpi.setTicketSolution(**params)
    if res:
        # pprint.pprint(res)
        chat.delete_message(chat.message["reply_to_message"]["message_id"])
        chat.send_text("Решение добавлено... вроде")


@bot.inline(r"(.*?)\s+(.*?)\s+((?i)login)")
async def inline_login(iq, match):
    sender_id = iq.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        if match.group(3):
            login_name = match.group(1)
            login_password = match.group(2)
            glpi = glpi_client()
            res = glpi.connect(login_name, login_password)
            logger.debug(res)
            if isinstance(res, dict):
                glpi_user = [iq.sender["id"]]
                for k, v in res.items():
                    new_key = "glpi_{}".format(k)
                    glpi_user.append(new_key)
                    glpi_user.append(v)
                await utils.set_user(pool, glpi_user, **iq.sender)
                res = "Привет, {}!".format(res["firstname"])
                text = "/menu"
            else:
                text = "Login failed"
            return iq.answer(
                [
                    {
                        "type": "article",
                        "title": "Вход в GLPI",
                        "description": res,
                        "message_text": text,
                        "thumb_url": settings.LOGIN_THUMB_URL,
                        "id": "123",
                    }
                ],
                cache_time=10,
            )
    else:
        return iq.answer(
            [
                {
                    "type": "article",
                    "title": "Только для своих",
                    "description": "Чужие не поймут",
                    "message_text": "Доступ запрещен",
                    "thumb_url": settings.LOGIN_THUMB_URL,
                    "id": "321",
                }
            ],
            cache_time=10,
        )


@bot.callback(r"cb_tickets_mine(\d+)")
async def tickets_mine(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        page_start = int(match.group(1))
        page_limit = 5
        page_end = page_start + page_limit
        params = {"assign": True, "status": "notold"}
        res = await glpi_api_call("listTickets", sender_id, chat, **params)
        if res:
            item_count = len(res)
            markup = keyboard.pagination(
                item_count, page_start, page_limit, "cb_tickets_mine"
            )
            for ticket in res[page_start:page_end]:
                time_to_resolve = "нет даты"
                try:
                    time_to_resolve = utils.format_date(ticket["time_to_resolve"])
                except ValueError:
                    pass
                button_text = "[{}] {}".format(time_to_resolve, ticket["name"])
                button_markup = [
                    {
                        "type": "InlineKeyboardButton",
                        "text": button_text,
                        "callback_data": "cb_ticket_{}".format(ticket["id"]),
                    }
                ]
                markup["inline_keyboard"].insert(-1, button_markup)

            markup["inline_keyboard"].append(
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_TICKETS,
                        "callback_data": "cb_tickets",
                    }
                ]
            )
            bot.edit_message_text(
                chat_id,
                message_id,
                "👨‍💻  Назначенные мне заявки ({})".format(item_count),
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_tickets_all_current(\d+)")
async def tickets_all_current(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        glpi_user_id = await utils.get_user_field(pool, sender_id, "glpi_id")
        count = await glpi_api_call(
            "listTickets", sender_id, chat, status="2", count=True
        )
        item_count = int(count["count"])
        page_start = int(match.group(1))
        page_limit = 5
        params = {"status": "notold", "start": page_start, "limit": page_limit}
        res = await glpi_api_call("listTickets", sender_id, chat, **params)
        if res:
            markup = keyboard.pagination(
                item_count, page_start, page_limit, "cb_tickets_all_current"
            )
            for ticket in res:
                time_to_resolve = "нет даты"
                try:
                    time_to_resolve = utils.format_date(ticket["time_to_resolve"])
                except ValueError:
                    pass
                button_text = "[{}] {}".format(time_to_resolve, ticket["name"])
                button_markup = [
                    {
                        "type": "InlineKeyboardButton",
                        "text": button_text,
                        "callback_data": "cb_ticket_{}".format(ticket["id"]),
                    }
                ]
                if ticket["users"]["assign"][0]["id"] == glpi_user_id:
                    button_markup[0]["text"] = "👨‍💻  {}".format(button_text)
                markup["inline_keyboard"].insert(-1, button_markup)

            markup["inline_keyboard"].append(
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "🔙  Заявки",
                        "callback_data": "cb_tickets",
                    }
                ]
            )
            bot.edit_message_text(
                chat_id,
                message_id,
                "👥  Все нерешенные ({})".format(item_count),
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_tickets")
async def tickets(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = {
            "type": "InlineKeyboardMarkup",
            "inline_keyboard": [
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "👨‍💻  Мои заявки",
                        "callback_data": "cb_tickets_mine0",
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "👥  Все нерешенные",
                        "callback_data": "cb_tickets_all_current0",
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "✍️  Новая заявка (не работает)",
                        "callback_data": "cb_tickets",
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_MENU,
                        "callback_data": "cb_menu",
                    }
                ],
            ],
        }
        bot.edit_message_text(
            chat_id, message_id, "Заявки", reply_markup=json.dumps(markup)
        )


@bot.callback(r"cb_ticket_(\d+)_document_(\d+)_send")
async def ticket_document_send(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        ticket = match.group(1)
        document = match.group(2)
        params = {"document": document, "ticket": ticket}
        await chat.send_chat_action("upload_document")
        res = await glpi_api_call("getDocument", sender_id, chat, **params)
        if res:
            doc_name = utils.translit_replace(res["filename"])
            doc_file = utils.b64_to_file(
                settings.DOCS_TMP_PATH, doc_name, res["base64"], res["sha1sum"]
            )
            if doc_file:
                doc_ext = doc_file.split(".")[-1]
                with open(doc_file, "rb") as f:
                    if doc_ext.lower() in ("bmp", "gif", "jpg", "jpeg", "png"):
                        await chat.send_photo(f, caption=res["filename"])
                    else:
                        await chat.send_document(f, caption=res["filename"])


@bot.callback(r"cb_ticket_(\d+)_document_add")
async def ticket_document_add_reply(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = {"type": "ForceReply", "force_reply": True}
        chat.send_text(
            "Документ к заявке #{}".format(match.group(1)),
            reply_markup=json.dumps(markup),
        )


@bot.callback(r"cb_ticket_(\d+)_followup_add")
async def ticket_followup_add_reply(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = {"type": "ForceReply", "force_reply": True}
        chat.send_text(
            "Комментарий к заявке #{}".format(match.group(1)),
            reply_markup=json.dumps(markup),
        )


@bot.callback(r"cb_ticket_(\d+)_solution_add")
async def ticket_solution_add_reply(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = {"type": "ForceReply", "force_reply": True}
        chat.send_text(
            "Решение заявки #{}".format(match.group(1)), reply_markup=json.dumps(markup)
        )


@bot.callback(r"cb_ticket_(\d+)_documents(\d+)")
async def ticket_documents(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        page_start = int(match.group(2))
        page_limit = 5
        page_end = page_start + page_limit
        ticket = match.group(1)
        res = await glpi_api_call("getTicket", sender_id, chat, ticket=ticket)
        if res:
            pprint.pprint(res["documents"])
            item_count = len(res["documents"])
            cb = "cb_ticket_{}_documents".format(ticket)
            markup = keyboard.pagination(item_count, page_start, page_limit, cb)
            sorted_list = sorted(
                res["documents"], key=lambda i: str(i["id"]), reverse=True
            )
            items = []
            for item in sorted_list[page_start:page_end]:
                item_fmt = settings.DOCUMENT_TEXT.format(
                    item["date_creation"], item["users_name"], item["filename"]
                )
                items.append(item_fmt)
                doc_button = [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "💾  {}".format(item["filename"]),
                        "callback_data": "cb_ticket_{}_document_{}_send".format(
                            item["tickets_id"], item["id"]
                        ),
                    }
                ]
                markup["inline_keyboard"].insert(-1, doc_button)
            documents_kbd = [
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "📂  Добавить документ",
                        "callback_data": "cb_ticket_{}_document_add".format(res["id"]),
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_DESC,
                        "callback_data": "cb_ticket_{}".format(res["id"]),
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_MENU,
                        "callback_data": "cb_menu",
                    }
                ],
            ]
            markup["inline_keyboard"] += documents_kbd
            reply = "<b>Документы к заявке «{}»</b>\n{}".format(
                res["name"], "".join(items)
            )
            if not res["documents"]:
                reply = "<b>У заявки «{}» пока нет документов</b>".format(res["name"])

            bot.edit_message_text(
                chat_id,
                message_id,
                reply,
                parse_mode="HTML",
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_ticket_(\d+)_followups(\d+)")
async def ticket_followups(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        page_start = int(match.group(2))
        page_limit = 5
        page_end = page_start + page_limit
        ticket = match.group(1)
        res = await glpi_api_call("getTicket", sender_id, chat, ticket=ticket)
        if res:
            item_count = len(res["followups"])
            cb = "cb_ticket_{}_followups".format(ticket)
            markup = keyboard.pagination(item_count, page_start, page_limit, cb)
            sorted_list = sorted(
                res["followups"], key=lambda i: str(i["id"]), reverse=True
            )
            items = []
            for item in sorted_list[page_start:page_end]:
                item_fmt = settings.FOLLOWUP_TEXT.format(
                    item["date_mod"], item["users_name"], item["content"]
                )
                items.append(item_fmt)
            followup_kbd = [
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": "📝  Добавить комментарий",
                        "callback_data": "cb_ticket_{}_followup_add".format(res["id"]),
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_DESC,
                        "callback_data": "cb_ticket_{}".format(res["id"]),
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_MENU,
                        "callback_data": "cb_menu",
                    }
                ],
            ]
            markup["inline_keyboard"] += followup_kbd
            reply = "<b>Комментарии к заявке «{}»\n</b>{}".format(
                res["name"], "".join(items)
            )
            if not res["followups"]:
                reply = "<b>У заявки «{}» пока нет комментариев</b>".format(res["name"])

            bot.edit_message_text(
                chat_id,
                message_id,
                reply,
                parse_mode="HTML",
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_ticket_(\d+)_history(\d+)")
async def ticket_history(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        page_start = int(match.group(2))
        page_limit = 5
        page_end = page_start + page_limit
        ticket = match.group(1)
        res = await glpi_api_call("getTicket", sender_id, chat, ticket=ticket)
        if res:
            item_count = len(res["events"])
            cb = "cb_ticket_{}_history".format(ticket)
            markup = keyboard.pagination(item_count, page_start, page_limit, cb)
            sorted_list = sorted(
                res["events"], key=lambda i: str(i["id"]), reverse=True
            )
            items = []
            for item in sorted_list[page_start:page_end]:
                item_fmt = settings.HISTORY_TEXT.format(
                    item["date_mod"], item["user_name"], item["field"], item["change"]
                )
                items.append(item_fmt)
            history_kbd = [
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_DESC,
                        "callback_data": "cb_ticket_{}".format(res["id"]),
                    }
                ],
                [
                    {
                        "type": "InlineKeyboardButton",
                        "text": keyboard.BTN_MENU,
                        "callback_data": "cb_menu",
                    }
                ],
            ]
            markup["inline_keyboard"] += history_kbd
            reply = "*История заявки «{}»\n*{}".format(res["name"], "".join(items))

            bot.edit_message_text(
                chat_id,
                message_id,
                reply,
                parse_mode="Markdown",
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_ticket_(\d+)")
async def ticket_details(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("getTicket", sender_id, chat, ticket=match.group(1))
        if res:
            time_to_resolve = ""
            try:
                time_to_resolve = utils.format_date(res["time_to_resolve"])
            except ValueError:
                pass
            requester_user = res["users"]["requester"][0]["users_name"]
            assign_user = ", ".join([u["users_name"] for u in res["users"]["assign"]])
            ticket_fmt = settings.TICKET_TEXT.format(
                settings.API_BASE,
                res["id"],
                res["name"],
                res["content"],
                time_to_resolve,
                res["ticketcategories_name"],
                res["entities_name"].replace("&gt;", ">"),
                requester_user,
                assign_user,
            )
            markup = {
                "type": "InlineKeyboardMarkup",
                "inline_keyboard": [
                    [
                        {
                            "type": "InlineKeyboardButton",
                            "text": "✔️  Решение",
                            "callback_data": "cb_ticket_{}_solution_add".format(
                                res["id"]
                            ),
                        },
                        {
                            "type": "InlineKeyboardButton",
                            "text": "💬  Комментарии ({})".format(len(res["followups"])),
                            "callback_data": "cb_ticket_{}_followups0".format(
                                res["id"]
                            ),
                        },
                    ],
                    [
                        {
                            "type": "InlineKeyboardButton",
                            "text": "📄  Документ ({})".format(len(res["documents"])),
                            "callback_data": "cb_ticket_{}_documents0".format(
                                res["id"]
                            ),
                        },
                        {
                            "type": "InlineKeyboardButton",
                            "text": "📖️  История ({})".format(len(res["events"])),
                            "callback_data": "cb_ticket_{}_history0".format(res["id"]),
                        },
                    ],
                    [
                        {
                            "type": "InlineKeyboardButton",
                            "text": "🔙  Мои заявки",
                            "callback_data": "cb_tickets_mine0",
                        },
                        {
                            "type": "InlineKeyboardButton",
                            "text": "🔙  Все нерешенные заявки",
                            "callback_data": "cb_tickets_all_current0",
                        },
                    ],
                    [
                        {
                            "type": "InlineKeyboardButton",
                            "text": keyboard.BTN_MENU,
                            "callback_data": "cb_menu",
                        }
                    ],
                ],
            }
            bot.edit_message_text(
                chat_id,
                message_id,
                ticket_fmt,
                parse_mode="HTML",
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_entity_(\d+)_set")
async def entity_set(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        params = {"entity": match.group(1), "recursive": 1}
        res = await glpi_api_call("setMyEntity", sender_id, chat, **params)
        if res:
            markup = keyboard.DEFAULT
            entities_text = "Выбранная организация: {}".format(res[0]["completename"])

            bot.edit_message_text(
                chat_id,
                message_id,
                entities_text,
                parse_mode="Markdown",
                reply_markup=json.dumps(markup),
            )


@bot.callback(r"cb_entities")
async def entities(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("listMyEntities", sender_id, chat)
        if res:
            markup = {
                "type": "InlineKeyboardMarkup",
                "inline_keyboard": [
                    [
                        {
                            "type": "InlineKeyboardButton",
                            "text": keyboard.BTN_MENU,
                            "callback_data": "cb_menu",
                        }
                    ]
                ],
            }
            buttons = []
            for entity in res:
                if entity["id"] not in [
                    "12",
                    "13",
                    "14",
                    "15",
                ]:  # FIXME hardcoded entities
                    buttons.append(
                        {
                            "type": "InlineKeyboardButton",
                            "text": "{}".format(entity["name"]),
                            "callback_data": "cb_entity_{}_set".format(entity["id"]),
                        }
                    )
            buttons_group = [
                [one, two] for one, two in zip(buttons[0::2], buttons[1::2])
            ]
            if len(buttons) % 2 != 0:
                buttons_group.append([buttons[-1]])
            markup["inline_keyboard"] = buttons_group + markup["inline_keyboard"]

            bot.edit_message_text(
                chat_id,
                message_id,
                settings.ENTITIES_TEXT,
                parse_mode="Markdown",
                reply_markup=json.dumps(markup),
            )


@bot.callback("cb_my_info")
async def my_info(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("getMyInfo", sender_id, chat)
        if res:
            markup = keyboard.DEFAULT
            my_info = "*{} {}*\n{}\n{}".format(
                res["realname"], res["firstname"], res["usertitles_name"], res["email"]
            )
            bot.edit_message_text(
                chat_id,
                message_id,
                my_info,
                parse_mode="Markdown",
                reply_markup=json.dumps(markup),
            )


@bot.callback("cb_logout")
async def logout(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("doLogout", sender_id, chat)
        if res:
            await utils.set_user_field(pool, sender_id, "glpi_session", "")
            chat.send_text(res["message"])


@bot.callback(r"cb_menu")
async def menu(chat, cq, match):
    sender_id = cq.src["from"]["id"]
    chat_id = chat.message["chat"]["id"]
    message_id = chat.message["message_id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = keyboard.DEFAULT
        bot.edit_message_text(
            chat_id,
            message_id,
            "Меню",
            parse_mode="Markdown",
            reply_markup=json.dumps(markup),
        )


@bot.handle("document")
async def document_add(chat, document):  # FIXME
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        # pprint.pprint(dir(chat))
        # pprint.pprint(chat.message.keys())
        # pprint.pprint(document)
        if "reply_to_message" in chat.message.keys():
            doc_name = ""
            try:
                bot_message_text = chat.message["reply_to_message"]["text"]

                if bot_message_text.startswith("Документ"):
                    content = ""
                    try:
                        content = chat.message["caption"]
                    except KeyError:
                        pass

                    session = await utils.get_user_field(
                        pool, sender_id, "glpi_session"
                    )
                    users_login = await utils.get_user_field(
                        pool, sender_id, "glpi_name"
                    )
                    ticket_id = re.search(r"#(\d+)", bot_message_text)

                    file_id = document["file_id"]
                    doc_name = utils.translit_replace(document["file_name"])

                    local_file = await download_file(
                        settings.DOCS_TMP_PATH, doc_name, file_id
                    )
                    encoded_string = utils.file_to_b64(local_file)

                    params = {
                        "session": session,
                        "ticket": ticket_id.group(1),
                        "name": doc_name,
                        "base64": encoded_string,
                        "content": content,
                        "users_login": users_login,
                        "source": "Telegram",
                    }
                    glpi = glpi_client()
                    res = glpi.addTicketDocument(**params)
                    if res:
                        doc = res["documents"][-1]
                        doc_fmt = settings.DOCUMENT_ADDED.format(
                            doc["tickets_id"], doc["date_mod"], doc["filename"]
                        )
                        chat.delete_message(
                            chat.message["reply_to_message"]["message_id"]
                        )
                        chat.send_text(doc_fmt, parse_mode="HTML")
            except xmlrpc.client.Fault as err:
                if "name" in err.faultString:
                    logger.error("%s (%s)", err.faultString, doc_name)
                    chat.send_text(
                        "❌  Формат файла запрещен к загрузке в настройках GLPI!"
                    )
                else:
                    logger.error("something wrong here")
                    chat.send_text("❌  Что-то пошло не так, документ не добавлен!")
                    raise err
            except:  # noqa
                raise
        else:
            chat.send_text(
                "Что это за файл? Я просто так файлы не принимаю, только через меню заявки!"
            )


@bot.command(r"/newticket\s+(.*)")
async def new_ticket_cmd(chat, match):
    sender_id = chat.sender["id"]
    logger.debug(match.group(1))
    ticket = [part.strip() for part in match.group(1).split("###")]
    logger.debug(ticket)
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        attrs = {"title": ticket[0], "content": ticket[1], "source": "Telegram"}
        res = await glpi_api_call("createTicket", sender_id, chat, **attrs)
        if res:
            chat.send_text(str(res))


@bot.command(r"/ticket\s+(\d+)")
async def ticket_cmd(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("getTicket", sender_id, chat, ticket=match.group(1))
        if res:
            txt = str(res)
            if len(txt) > 4095:
                txt1 = txt[:4095]
                txt2 = txt[4095:]
                for i in txt1, txt2:
                    chat.send_text(i)
            else:
                chat.send_text(txt)


@bot.command(r"/obj\s+(\w+)\s+(\d+)")
async def object_cmd(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        attrs = {"itemtype": match.group(1), "id": match.group(2), "show_name": True}
        res = await glpi_api_call("getObject", sender_id, chat, **attrs)
        if res:
            chat.send_text(str(res))


@bot.command(r"/status")
async def status(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("status", sender_id, chat)
        if res:
            chat.send_text(str(res))


@bot.command(r"/test")
async def test(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("test", sender_id, chat)
        if res:
            chat.send_text(str(res))


@bot.command(r"/profile")
async def profile(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("getMyInfo", sender_id, chat)
        if res:
            chat.send_text(str(res))


@bot.command(r"/logout")
async def logout_cmd(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        res = await glpi_api_call("doLogout", sender_id, chat)
        if res:
            await utils.set_user_field(pool, sender_id, "glpi_session", "")
            chat.send_text(res["message"])


@bot.command(r"/force_test")
async def force_test(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        markup = {"type": "ForceReply", "force_reply": True}
        chat.send_text("Прошу, ответь!", reply_markup=json.dumps(markup))


@bot.command(r"/menu")
@bot.command(r"/start")
async def start(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        if await utils.get_user_field(pool, sender_id, "glpi_session"):
            markup = keyboard.DEFAULT
            chat.send_text("Меню", reply_markup=json.dumps(markup))
        else:
            login_name = await utils.get_user_field(pool, sender_id, "glpi_name")
            markup = keyboard.LOGIN
            if login_name:
                markup["inline_keyboard"][0][0][
                    "switch_inline_query_current_chat"
                ] = "{} ".format(login_name)
            chat.send_text(
                settings.LOGIN_TEXT,
                parse_mode="Markdown",
                reply_markup=json.dumps(markup),
            )
    else:
        chat.send_text("Только для своих")


@bot.default
async def default(chat, match):
    sender_id = chat.sender["id"]
    if str(sender_id) in settings.BOT_USERS_CHAT_ID:
        # pprint.pprint(dir(chat))
        # pprint.pprint(chat.message.keys())
        # pprint.pprint(chat.message['text'])
        if "reply_to_message" in chat.message.keys():
            try:
                session = await utils.get_user_field(pool, sender_id, "glpi_session")
                users_login = await utils.get_user_field(pool, sender_id, "glpi_name")
                bot_message_text = chat.message["reply_to_message"]["text"]
                ticket_id = re.search(r"#(\d+)", bot_message_text)

                if bot_message_text.startswith("Комментарий"):
                    await ticket_followup_add(
                        chat, session, users_login, ticket_id.group(1)
                    )

                if bot_message_text.startswith("Решение"):
                    await ticket_solution_add(chat, session, ticket_id.group(1))
            except:  # noqa
                logger.error("something wrong here")
                chat.send_text("❌  Что-то пошло не так, комментарий не добавлен!")
                raise


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)8s] [%(name)s:%(lineno)s:%(funcName)20s()] --- %(message)s",
        level=logging.DEBUG,
    )
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(bot.loop(), main()))
