import aiohttp
from aiohttp import web
from . import protocol
import logging
import asyncio
import json


def dumps(o):
    def enc(w):
        if type(w) == bytes:
            return w.hex()
        else:
            return repr(w)
    return json.dumps(o, default=enc)


class HTTPUnreachable(web.HTTPError):
    status_code = 523


async def enable(request):
    cc = request.app.cc
    try:
        data = await cc.enable()
    except asyncio.CancelledError as e:
        raise HTTPUnreachable(content_type="application/json", text=json.dumps({"error": repr(e)}))
    return web.json_response(data, dumps=dumps)

async def disable(request):
    cc = request.app.cc
    try:
        data = await cc.disable()
    except asyncio.CancelledError as e:
        raise HTTPUnreachable(content_type="application/json", text=json.dumps({"error": repr(e)}))
    return web.json_response(data, dumps=dumps)

async def status(request):
    cc = request.app.cc
    try:
        data = await cc.poll()
    except asyncio.CancelledError as e:
        raise HTTPUnreachable(content_type="application/json", text=json.dumps({"error": repr(e)}))
    return web.json_response(data, dumps=dumps)


async def get_bill(request):
    cc = request.app.cc
    try:
        data = await protocol.timeouted(30, asyncio.ensure_future(cc.stack_one()))
    except Exception as e:
        data = {'error': str(e)}
    return web.json_response(data, dumps=dumps)

async def setup(app, config):
    port = config.get('com')
    baudrate = config.get('baudrate', 9600)
    addr = config.get('adr', 3)
    assert port, "No port in config"
    app.cc = protocol.CCNET(port, adr=addr, baudrate=9600)
    await (await app.cc.open())
    s = await app.cc.reset()
    logging.info(s)
    logging.info(await app.cc.command(0x31))
    logging.info(await app.cc.command(0x37))
    logging.info(await app.cc.command(0x32, b'\xff\xff\xff'))
    app.router.add_post('/atm/cashcode/status', status)
    app.router.add_post('/atm/cashcode/get_bill', get_bill)
    app.router.add_post('/atm/cashcode/enable', enable)
    app.router.add_post('/atm/cashcode/disable', disable)

async def main():
    app = web.Application()
    import toml
    config = toml.load('config.ini').get('cashcode', {})
    await setup(app, config)
    runner = web.AppRunner(app)
    await runner.setup()
    config = toml.load('config.ini').get('web', {})
    site = web.TCPSite(runner, config.get('host', '0.0.0.0'), config.get('port', 4801))
    await site.start()
    return site


