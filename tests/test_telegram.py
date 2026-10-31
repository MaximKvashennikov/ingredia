"""Telegram flow tests using fake Bot API transport and synthetic media."""

import asyncio
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, SendDocument, SendMessage
from aiogram.types import Chat, File, Message, PhotoSize, Update, User

from ingredia.adapters.telegram import create_dispatcher
from ingredia.recognition.service import PhotoTrial


class FakeSession(BaseSession):
    """A Telegram session recording calls without any network requests."""

    def __init__(self, image):
        """Inject the file to download and capture outgoing methods."""
        super().__init__()
        self.image = image
        self.methods = []

    async def close(self):
        """Close the fake transport."""

    async def make_request(self, bot, method, timeout=None):
        """Return deterministic Telegram method results."""
        self.methods.append(method)
        if isinstance(method, GetFile):
            return File(file_id="test-photo", file_unique_id="unique", file_path="test.jpg")
        if isinstance(method, SendMessage | SendDocument):
            return Message(
                message_id=100,
                date=datetime.now(UTC),
                chat=Chat(id=1, type="private"),
            )
        raise AssertionError(type(method).__name__)

    async def stream_content(self, url, **kwargs):
        """Yield synthetic photo data as a downloaded Telegram file."""
        yield self.image


class FakeRecognizer:
    """Return a known recognition result."""

    def __init__(self, result):
        """Initialize the expected result and a call counter."""
        self.result = result
        self.calls = 0

    async def recognize(self, photo):
        """Return expected observations."""
        self.calls += 1
        return self.result


def photo_update():
    """Create a non-personal Telegram update."""
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="Synthetic"),
            photo=[PhotoSize(file_id="test-photo", file_unique_id="unique", width=32, height=24)],
        ),
    )


def test_telegram_photo_returns_json_document(jpeg, recognition):
    """A photo produces validated JSON and duplicate delivery does not call AI twice."""

    async def run():
        session = FakeSession(jpeg)
        bot = Bot("123456:TEST", session=session)
        fake = FakeRecognizer(recognition)
        dispatcher = create_dispatcher(PhotoTrial(fake, None, cooldown_seconds=0))
        await dispatcher.feed_update(bot, photo_update())
        documents = [method for method in session.methods if isinstance(method, SendDocument)]
        assert len(documents) == 1
        assert documents[0].document.data.decode() == recognition.model_dump_json(indent=2)
        assert fake.calls == 1
        await dispatcher.feed_update(bot, photo_update())
        assert fake.calls == 1
        await bot.session.close()

    asyncio.run(run())


def test_telegram_denies_before_download(jpeg, recognition):
    """An unlisted sender receives a safe reply without downloading or calling AI."""

    async def run():
        session = FakeSession(jpeg)
        bot = Bot("123456:TEST", session=session)
        fake = FakeRecognizer(recognition)
        dispatcher = create_dispatcher(PhotoTrial(fake, frozenset()))
        await dispatcher.feed_update(bot, photo_update())
        assert not any(isinstance(method, GetFile | SendDocument) for method in session.methods)
        assert fake.calls == 0
        assert any(isinstance(method, SendMessage) for method in session.methods)
        await bot.session.close()

    asyncio.run(run())


def test_group_photo_is_not_processed(jpeg, recognition):
    """A photo in a group does not expose recognition data or consume quota."""

    async def run():
        session = FakeSession(jpeg)
        bot = Bot("123456:TEST", session=session)
        fake = FakeRecognizer(recognition)
        dispatcher = create_dispatcher(PhotoTrial(fake, None))
        update = photo_update()
        update = update.model_copy(
            update={
                "message": update.message.model_copy(update={"chat": Chat(id=-1, type="group")})
            }
        )
        await dispatcher.feed_update(bot, update)
        assert not session.methods
        assert fake.calls == 0
        await bot.session.close()

    asyncio.run(run())
