import os

from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERS_CHAT_ID = os.getenv("BOT_USERS_CHAT_ID").split(",")
BOT_PROXY_URL = os.getenv("BOT_PROXY_URL")

API_BASE = os.getenv("API_BASE")
API_USER = os.getenv("API_USER")
API_PASS = os.getenv("API_PASS")

LOGIN_THUMB_URL = os.getenv("LOGIN_THUMB_URL")

DOCS_TMP_PATH = os.getenv("DOCS_TMP_PATH")

# noqa
LOGIN_TEXT = """
Нажми кнопку *🔐  Вход в GLPI* под сообщением и вводи данные, \
чтобы получилась такая строка:

`@kapotnya_glpi_bot user password login`

*user и password* - замени на свои
*login* - специальное слово, прямо так и написать login
*1 пробел* между частями заклинания

Если всё сделал правильно, всплывет такая карточка:
```
  | |  Вход в GLPI
  |_|  Привет, Имя Отчество!
```
Нажми на неё, чтобы продолжить работу с GLPI через бота!

_P.S. Если заходишь через десктоп, то не нажимай Enter, иначе отправишь свой пароль в чат. \
В данном случае это не страшно, просто удали сообщение с ним._
"""

ENTITIES_TEXT = (
    "Укажи организацию. От организации зависит, какие заявки и активы будут доступны"
)

DOCUMENT_TEXT = """
<b>{}</b>, {}
💾  {}
"""

FOLLOWUP_TEXT = """
<b>{}</b>, {}
💬  {}
"""

FOLLOWUP_ADDED = """
✅  Комментарий добавлен!

На всякий случай, это последний комментарий из заявки #{}:

<b>{}</b>
💬  {}

🗑️  Можешь удалить это и предыдущее сообщение, \
чтобы чат стал чище!
"""

DOCUMENT_ADDED = """
✅  Документ добавлен!

На всякий случай, это последний документ из заявки #{}:
<b>{}</b>
💾  {}

🗑️  Можешь удалить это и предыдущее сообщение, \
чтобы чат стал чище!
"""

HISTORY_TEXT = """
*{}*, {}
{}, {}
"""

TICKET_TEXT = """
<b><a href="{}/front/ticket.form.php?id={}">🔗  {}</a></b>
<b>Описание:</b> {}
<b>Срок:</b> {}
<b>Категория:</b> {}
<b>Организация:</b> {}
<b>Автор:</b> {}
<b>Назначено:</b> {}
"""
