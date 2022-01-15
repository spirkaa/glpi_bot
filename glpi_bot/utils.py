import base64
import datetime
import hashlib
import logging
import os
import re
import time

from transliterate import translit

logger = logging.getLogger("__name__")


def unix_time(time_):
    return int(time.mktime(time_.timetuple()))


def norm_time(ts):
    return datetime.datetime.fromtimestamp(ts)


def format_date(dt):
    """
    :type dt: str
    :param dt: datetime string
    :return: date string
    """
    fmt = datetime.datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    return fmt.strftime("%d.%m.%Y")


def dict_to_keys(**sender):
    keys = []
    for k, v in sender.items():
        if k == "id":
            keys.insert(0, v)
        if v is False:
            v = "False"
        if v is True:
            v = "True"
        else:
            keys.append(k)
            keys.append(v)
    return keys


async def set_user(pool, glpi_user, **sender):
    now = unix_time(datetime.datetime.now())
    with await pool as redis:
        await redis.select(0)
        pairs = dict_to_keys(**sender)
        tr = redis.multi_exec()
        logger.debug(pairs)
        logger.debug(glpi_user)
        tr.hmset(*pairs)
        tr.hmset(*glpi_user)
        tr.hsetnx(pairs[0], "created", now)
        tr.hset(pairs[0], "modified", now)
        await tr.execute()
        logger.debug("%s: {%s}", pairs[0], await redis.hgetall(pairs[0]))


async def set_user_field(pool, sender_id, key, value):
    with await pool as redis:
        await redis.select(0)
        await redis.hset(sender_id, key, value)
        res = await redis.hget(sender_id, key)
        logger.debug("%s: {%s: %s}", sender_id, key, res)


async def get_user_field(pool, sender_id, key):
    with await pool as redis:
        await redis.select(0)
        value = await redis.hget(sender_id, key)
        logger.debug("%s: {%s: %s}", sender_id, key, value)
        return value


def translit_replace(string):
    string = re.sub(r'[\\/*?:"<>|\s]', "_", string)
    string = re.sub(r"_+", "_", string)
    return translit(string, "ru", reversed=True)


def file_to_b64(file):
    """
    Encodes given file to base64 string

    :type file: str
    :param file: path to file
    :return: base64 string
    :rtype: str
    """
    with open(file, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def b64_to_file(path, filename, b64_str, sha1sum_orig, buf_size=65536):
    """
    Decodes base64 string and saves to file, then checks sha1 sum

    :type path: str
    :type filename: str
    :type b64_str: str
    :type sha1sum_orig: str
    :type buf_size: int
    :param path: path of the file
    :param filename: name of the file
    :param b64_str: string with base64 encoded file
    :param sha1sum_orig: SHA1 sum
    :param buf_size: size of read buffer
    :return: path to file
    :rtype: str
    """

    sha1 = hashlib.sha1()

    if not os.path.exists(path):
        os.makedirs(path)

    doc_path = os.path.join(path, filename)

    if os.path.exists(doc_path):
        pass

    with open(doc_path, "wb") as f:
        f.write(base64.b64decode(b64_str))

    with open(doc_path, "rb") as f:
        while True:
            data = f.read(buf_size)
            if not data:
                break
            sha1.update(data)
        sha1sum_calc = sha1.hexdigest()
        logger.debug("[Checksum] calc: %s get: %s", sha1sum_calc, sha1sum_orig)
        if sha1sum_calc == sha1sum_orig:
            return doc_path
        else:
            logger.error("Error! sha1 sums don't match")
            return False
