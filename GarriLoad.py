#    Friendly Telegram (telegram userbot)
#    Copyright (C) 2018-2019 The Authors

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import importlib
import sys
import uuid
import asyncio
import urllib
import os
import re
import requests

from importlib.machinery import ModuleSpec
from importlib.abc import SourceLoader

from .. import loader, utils

logger = logging.getLogger(__name__)

VALID_URL = r"[-[\]_.~:/?#@!$&'()*+,;%<=>a-zA-Z0-9]+"
VALID_PIP_PACKAGES = re.compile(r"^\s*# requires:(?: ?)((?:{url} )*(?:{url}))\s*$".format(url=VALID_URL), re.MULTILINE)
USER_INSTALL = "PIP_TARGET" not in os.environ and "VIRTUAL_ENV" not in os.environ


class StringLoader(SourceLoader):  # pylint: disable=W0223 # False positive, implemented in SourceLoader
    """Load a python module/file from a string"""
    def init(self, data, origin):
        if isinstance(data, str):
            self.data = data.encode("utf-8")
        else:
            self.data = data
        self.origin = origin

    def get_code(self, fullname):
        source = self.get_source(fullname)
        if source is None:
            return None
        return compile(source, self.origin, "exec", dont_inherit=True)

    def get_filename(self, fullname):
        return self.origin

    def get_data(self, filename):  # pylint: disable=W0221,W0613
        # W0613 is not fixable, we are overriding
        # W0221 is a false positive assuming docs are correct
        return self.data


def unescape_percent(text):
    i = 0
    ln = len(text)
    is_handling_percent = False
    out = ""
    while i < ln:
        char = text[i]
        if char == "%" and not is_handling_percent:
            is_handling_percent = True
            i += 1
            continue
        if char == "d" and is_handling_percent:
            out += "."
            is_handling_percent = False
            i += 1
            continue
        out += char
        is_handling_percent = False
        i += 1
    return out


@loader.tds
class GarriLoad(loader.Module):
    """Модуль для загрузки других модулей"""
    strings = {"name": "Loader",
               "repo_config_doc": "<b>[GarriOwO] Вставь полную ссылку</b>",
               "avail_header": "<b>[GarriOwO] Модули которые доступны в репо</b>",
               "select_preset": "<b>Please select a preset</b>",
               "no_preset": "<b>Preset not found</b>",
               "preset_loaded": "<b>Preset loaded</b>",
               "no_module": "<b>[⚡️ GarriOwO] Не найден модуль в репо</b>",
               "no_file": "<b>[⚡️ GarriOwO] </b><i>Файл не найден.</i>",
               "provide_module": "<b>Provide a module to load</b>",
               "bad_unicode": "<b>Invalid Unicode formatting in module</b>",
               "load_failed": "<b>[⚡️ GarriOwO] </b><i>😡 Ошибка! Смотри логи чтобы узнать проблемы</i> (<code> .logs error </code>)" ,
               "loaded": "<b>[⚡️ GarriOwO] </b><i>Модуль успешно загружен!</i>",
               "no_class": "<b>[⚡️ GarriOwO] </b></i>Что выгрузить надо? \nУкажи название и попробуй заново.</i>",
               "unloaded": "<b>[⚡️ GarriOwO] </b><i>Модуль успешно выгружен.</i>",

"not_unloaded": "<b>[⚡️ GarriOwO] </b><i>😡 Модуль не был выгружен.\nВозможно вы ошиблись в его названии.</i>",
               "requirements_failed": "<b>[⚡️ GarriOwO] Дополнение не установлено!</b>",
               "requirements_installing": "<b>[⚡️ GarriOwO] Устанавливаю дополнения...</b>",
               "requirements_restart": "<b>[⚡️ GarriOwO] Дополнения успешно установлены! Перезагрузись</b>"}

    def init(self):
        super().__init__()
        self.config = loader.ModuleConfig("MODULES_REPO",
                                          "https://gitlab.com/friendly-telegram/modules-repo/-/raw/master",
                                          lambda m: self.strings("repo_config_doc", m))

    @loader.owner
    async def loadcmd(self, message):
        """.dlmod <ссылка на модуль> - установить модуль"""
        args = utils.get_args(message)
        if args:
            if await self.download_and_install(args[0], message):
                self._db.set(__name__, "loaded_modules",
                             list(set(self._db.get(__name__, "loaded_modules", [])).union([args[0]])))
        else:
            text = utils.escape_html("\n".join(await self.get_repo_list("full")))
            await utils.answer(message, "<b>" + self.strings("avail_header", message)
                               + "</b>\n<code>" + text + "</code>")

    @loader.owner
    async def dlpresetcmd(self, message):
        """Set preset. Defaults to full"""
        args = utils.get_args(message)
        if not args:
            await utils.answer(message, self.strings("select_preset", message))
            return
        try:
            await self.get_repo_list(args[0])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                await utils.answer(message, self.strings("no_preset", message))
                return
            else:
                raise
        self._db.set(__name__, "chosen_preset", args[0])
        self._db.set(__name__, "loaded_modules", [])
        self._db.set(__name__, "unloaded_modules", [])
        await utils.answer(message, self.strings("preset_loaded", message))

    async def _get_modules_to_load(self):
        todo = await self.get_repo_list(self._db.get(__name__, "chosen_preset", None))
        todo = todo.difference(self._db.get(__name__, "unloaded_modules", []))
        todo.update(self._db.get(__name__, "loaded_modules", []))
        return todo

    async def get_repo_list(self, preset=None):
        if preset is None:
            preset = "minimal"
        r = await utils.run_sync(requests.get, self.config["MODULES_REPO"] + "/" + preset + ".txt")
        r.raise_for_status()
        return set(filter(lambda x: x, r.text.split("\n")))

    async def download_and_install(self, module_name, message=None):
        if urllib.parse.urlparse(module_name).netloc:
            url = module_name
        else:
            url = self.config["MODULES_REPO"] + "/" + module_name + ".py"
        r = await utils.run_sync(requests.get, url)
        if r.status_code == 404:
            if message is not None:
                await utils.answer(message, self.strings("no_module", message))
            return False
        r.raise_for_status()
        return await self.load_module(r.content.decode("utf-8"), message, module_name, url)

@loader.owner
    async def unloadmodcmd(self, message):
        """Unload module by class name"""
        args = utils.get_args(message)
        if not args:
            await utils.answer(message, self.strings("no_class", message))
            return
        clazz = args[0]
        worked = self.allmodules.unload_module(clazz)
        without_prefix = []
        for mod in worked:
            assert mod.startswith("friendly-telegram.modules."), mod
            without_prefix += [unescape_percent(mod[len("friendly-telegram.modules."):])]
        it = set(self._db.get(__name__, "loaded_modules", [])).difference(without_prefix)
        self._db.set(__name__, "loaded_modules", list(it))
        it = set(self._db.get(__name__, "unloaded_modules", [])).union(without_prefix)
        self._db.set(__name__, "unloaded_modules", list(it))
        if worked:
            await utils.answer(message, self.strings("unloaded", message))
        else:
            await utils.answer(message, self.strings("not_unloaded", message))

    async def _update_modules(self):
        todo = await self._get_modules_to_load()
        await asyncio.gather(*[self.download_and_install(mod) for mod in todo])

    async def client_ready(self, client, db):
        self._db = db
        self._client = client
        await self._update_modules()
