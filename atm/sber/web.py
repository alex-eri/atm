from .protocol import Pilot
from aiohttp import web
import asyncio
import logging

async def acquiring(request):
    req = await request.json()
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, request.app.sb_pilot.exec_acquiring, req['ammount'])
    return web.json_response(res)

async def sync(request):
    req = await request.json()
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, request.app.sb_pilot.exec_sync)
    return web.json_response(res)

async def runcmd(request):
    req = await request.json()
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, request.app.sb_pilot.run, req['command'])
    return web.json_response(res)   

async def setup(app, config={}):
    app.sb_pilot = Pilot(config)
    loop = asyncio.get_running_loop()
    loop.call_soon(app.sb_pilot.run, 7)
    app.router.add_post('/atm/sber/acquiring', acquiring)
    app.router.add_post('/atm/sber/run', runcmd)
    app.router.add_post('/atm/sber/sync', sync)