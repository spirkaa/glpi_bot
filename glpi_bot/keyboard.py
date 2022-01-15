import settings

DEFAULT = {
    "type": "InlineKeyboardMarkup",
    "inline_keyboard": [
        [
            {
                "type": "InlineKeyboardButton",
                "text": "🎫  Заявки",
                "callback_data": "cb_tickets",
            }
        ],
        [
            {
                "type": "InlineKeyboardButton",
                "text": "🏘️  Выбрать организацию",
                "callback_data": "cb_entities",
            }
        ],
        [
            {
                "type": "InlineKeyboardButton",
                "text": "ℹ️  Кто я?",
                "callback_data": "cb_my_info",
            }
        ],
        [
            {
                "type": "InlineKeyboardButton",
                "text": "🔗  Открыть сайт GLPI",
                "url": settings.API_BASE,
            }
        ],
        [
            {
                "type": "InlineKeyboardButton",
                "text": "🚪  Выйти из GLPI",
                "callback_data": "cb_logout",
            }
        ],
    ],
}

LOGIN = {
    "type": "InlineKeyboardMarkup",
    "inline_keyboard": [
        [
            {
                "type": "InlineKeyboardButton",
                "text": "🔐  Вход в GLPI",
                "switch_inline_query_current_chat": "",
            }
        ]
    ],
}

BTN_MENU = "🏠  Главное меню"
BTN_TICKETS = "🔙  Заявки"
BTN_DESC = "🔙  Описание"


def pagination(item_count, page_start, page_limit, cb):
    """
    Pagination for Inline Keyboard

    :type item_count: int
    :type page_start: int
    :type page_limit: int
    :type cb: str
    :param item_count: total number of items
    :param page_start: page_start page from this item number
    :param page_limit: limit items on page
    :param cb: callback for buttons
    :return: InlineKeyboardMarkup
    :rtype dict:
    """

    markup = {"type": "InlineKeyboardMarkup", "inline_keyboard": []}
    if item_count > page_limit:
        next_btn = [
            {
                "type": "InlineKeyboardButton",
                "text": "➡️",
                "callback_data": "{}{}".format(cb, page_limit),
            }
        ]
        markup["inline_keyboard"].insert(0, next_btn)
    if page_start >= page_limit:
        prev_start = page_start - page_limit
        next_start = page_start + page_limit
        prev_btn = {
            "type": "InlineKeyboardButton",
            "text": "⬅️",
            "callback_data": "{}{}".format(cb, prev_start),
        }
        markup["inline_keyboard"][0].insert(0, prev_btn)
        markup["inline_keyboard"][0][1]["callback_data"] = "{}{}".format(cb, next_start)
        if next_start >= item_count:
            markup["inline_keyboard"][0].pop()
    return markup
