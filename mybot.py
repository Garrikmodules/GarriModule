from pyrogram.errors import FloodWait
 
from pyrogram.types import ChatPermissions
 
import time
from time import sleep
import random
import pyrogram
from pyrogram import Client, filters
app = Client("my_account")
@app.on_message(filters.command("testo", prefixes="%") & filters.me)
async def testo(client, message):
    await message.edit_text("Works good")
    app.run()