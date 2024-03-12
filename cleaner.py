import os
import json

from time import sleep, time
from datetime import datetime, timedelta

from pyrogram import Client
from pyrogram.raw.functions.messages import Search
from pyrogram.raw.types import InputPeerSelf, InputMessagesFilterEmpty
from pyrogram.raw.types.messages import ChannelMessages
from pyrogram.errors import FloodWait, UnknownError

cachePath = os.path.abspath(__file__)
cachePath = os.path.dirname(cachePath)
cachePath = os.path.join(cachePath, "cache")

if os.path.exists(cachePath):
    with open(cachePath, "r") as cacheFile:
        cache = json.loads(cacheFile.read())
    
    API_ID = cache["API_ID"]
    API_HASH = cache["API_HASH"]
else:
    API_ID = os.getenv('TG_API_ID', None) or int(input('Enter your Telegram API id: '))
    API_HASH = os.getenv('TG_API_HASH', None) or input('Enter your Telegram API hash: ')

app = Client("client", api_id=API_ID, api_hash=API_HASH)

if not os.path.exists(cachePath):
    with open(cachePath, "w") as cacheFile:
        cache = {"API_ID": API_ID, "API_HASH": API_HASH}
        cacheFile.write(json.dumps(cache))


class Cleaner:
    def __init__(self, chats=None, search_chunk_size=100, delete_chunk_size=100):
        self.chats = chats or []
        self.time = None
        if search_chunk_size > 100:
            # https://github.com/gurland/telegram-delete-all-messages/issues/31
            #
            # The issue is that pyrogram.raw.functions.messages.Search uses
            # pagination with chunks of 100 messages. Might consider switching
            # to search_messages, which handles pagination transparently.
            raise ValueError('search_chunk_size > 100 not supported')
        self.search_chunk_size = search_chunk_size
        self.delete_chunk_size = delete_chunk_size
        self.skip_memes = False
        # deep clean is probably outdated, as the client SHOULD properly return all the IDs even when leaving-joining group
        self.deep_clean = False

    @staticmethod
    def chunks(l, n):
        """Yield successive n-sized chunks from l.
        https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks#answer-312464"""
        for i in range(0, len(l), n):
            yield l[i:i + n]

    @staticmethod
    async def get_all_chats():        
        async with app:
            dialogs = []
            async for dialog in app.get_dialogs():
                dialogs.append(dialog.chat)
            return dialogs

    async def select_groups(self):
        chats = await self.get_all_chats()
        # Hmm??? groups = [c for c in chats if c.type in ('group', 'supergroup')]
        groups = [c for c in chats if c.type.name in ('GROUP, SUPERGROUP')]

        print('Make a selection. Remove the sent messages in:')
        for i, group in enumerate(groups):
            print(f'  {i+1}. {group.title}')

        print (f'  -----------------------------------------------------------')
        print(
            f'  {len(groups) + 1}. '
            '(!) DELETE ALL YOUR MESSAGES IN ALL OF THOSE GROUPS (!)\n'
        )

        nums_str = input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), nums_str.split(','))

        for n in nums:
            if not 1 <= n <= len(groups) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            if n == len(groups) + 1:
                print('\nTHIS WILL DELETE ALL YOUR MESSSAGES IN ALL GROUPS!')
                answer = input('Please type "I understand" to proceed: ')
                if answer.upper() != 'I UNDERSTAND':
                    print('Better safe than sorry. Aborting...')
                    exit(-1)
                self.chats = groups
                break
            else:
                self.chats.append(groups[n - 1])
        
        groups_str = ', '.join(c.title for c in self.chats)
        print(f'\nSelected {groups_str}.\n')

    async def run(self):
        for chat in self.chats:
            chat_id = chat.id
            message_ids = []
            add_offset = 0
            skipped_date = 0
            skipped_meme = 0
            if input('Deep Clean? y/N: ').upper() == 'Y':
                self.deep_clean = True

            if input('Skip memes? y/N: ').upper() == 'Y':
                self.skip_memes = True

            while True:
                q = await self.search_messages(chat_id, add_offset)

                for msg in q:
                    if (msg.date < self.time):
                        if (self.skip_memes and hasattr(msg, 'caption') and msg.caption is not None):
                            # print(f'S???:', msg.caption)
                            if msg.caption[:6].upper() != "#MEMES": # ignore memes?
                                message_ids.append(msg.id)
                            else:
                                skipped_meme += 1
                        else:
                            message_ids.append(msg.id)
                    else:
                        skipped_date += 1

                # ↑ replaced the following:
                # message_ids.extend(msg.id for msg in q if %CONDITION%)

                messages_count = len(q)
                print(f'Found {messages_count} of messages in "{chat.title}" older than the selected time.')
                if messages_count < self.search_chunk_size:
                    break
                add_offset += self.search_chunk_size
            if (skipped_meme + skipped_date) > 0:
                print(f'Omitting', skipped_date, f' messages due to date cutoff and', skipped_meme, f' messages due to meme bypass.')

            if self.deep_clean:
                n_start = int(input('starting ID: '))
                n_end = int(input('end ID: '))
                for msgid in range(n_start, n_end):
                    message_ids.append(msgid)
            answer = input('Last chance to stop!')
            await self.delete_messages(chat_id=chat.id, message_ids=message_ids)

    async def delete_messages(self, chat_id, message_ids):
        print('\nThis will irreversibly delete', len(message_ids), 'messages older than the cutoff time in the selected group(s).')
        answer = input('Please type "Y" to proceed: ')
        if answer.upper() != 'Y':
            print('Better safe than sorry. Aborting...')
            exit(-1)
        print(f'Deleting {len(message_ids)} messages with message IDs:')
        print(message_ids)
        for chunk in self.chunks(message_ids, self.delete_chunk_size):
            try:
                async with app:
                    await app.delete_messages(chat_id=chat_id, message_ids=chunk)
            except FloodWait as flood_exception:
                sleep(flood_exception.x)

    async def search_messages(self, chat_id, add_offset):
        async with app:
            messages = []
            print(f'Searching messages. OFFSET: {add_offset}')
            async for message in app.search_messages(
                chat_id=chat_id,
                offset=add_offset,
                from_user="me",
                limit=self.search_chunk_size):
                messages.append(message)
            return messages

    def select_time(self):
        days_amount = int(input('Type in the amount of the last days to ignore (the deletion cutoff): ') or 7);
        now = datetime.now()
        current_time = now.strftime("%d.%m.%Y, %H:%M:%S")
        print("Current system date and time is:", current_time)
        cutoff_time = now - timedelta(days=days_amount)
        cutoff_time_display = cutoff_time.strftime("%d.%m.%Y, %H:%M:%S")
        print("Message deletion cutoff time is set to be ", days_amount, " days before the current system time, which is:", cutoff_time_display)
        answer = input('\nIf this cutoff time is correct, please type "Y" to proceed: ')
        if answer.upper() != 'Y':
            print('Better safe than sorry. Aborting...')
            exit(-1)
        self.time = cutoff_time

    async def select_bot(self):
        chats = await self.get_all_chats()
        bots = [c for c in chats if c.type.name in ('BOT')]
        
        print('Make a selection.:')
        for i, bot in enumerate(bots):
            print(f'  {i+1}. {bot.username} {bot.first_name} {bot.last_name}')

        nums_str = input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), nums_str.split(','))

        for n in nums:
            if not 1 <= n <= len(bots) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            self.chats.append(bots[n - 1])
        
        bots_str = ', '.join(c.username for c in self.chats)
        print(f'\nSelected {bots_str}.\n')

    async def run_spam(self):
        async with app:
            for chat in self.chats:
                peer = await app.resolve_peer(chat.id)
                count = int(input("How many?"))
                sent = 0
                last_id = 0
                while (sent < count):
                    if (sent % 10 == 0):
                        print(f'Sending #{sent}...')
                    
                    await app.send_message(chat.id, "🔟🎫")
                    sent += 1

                    sleep(15)

async def main():
    try:
        deleter = Cleaner()
        mode = input('Mode?')
        if mode.upper() != 'SPAM':
            await deleter.select_groups()
            deleter.select_time()
            await deleter.run()
        else:
            await deleter.select_bot()
            await deleter.run_spam()

    except UnknownError as e:
        print(f'UnknownError occured: {e}')
        print('Probably API has changed, ask developers to update this utility')

app.run(main())