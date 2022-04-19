import logging
import asyncio
from . import web

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(web.main())
    loop.run_forever()
