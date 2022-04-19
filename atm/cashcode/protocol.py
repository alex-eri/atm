import asyncio
import logging
import serial_asyncio
import serial
import functools
import traceback


RESET = 0x30
STATUS = 0x31
SET_SECURITY = 0x32
POLL = 0x33
SET_BILL_TABLE = 0x34
SET_COIN_TYPES = 0x0c
STACK = 0x35
RETURN = 0x36
IDENTIFICATION = 0x37
HOLD = 0x38
SET_BARCODE_PARAMETERS = 0x39
EXTRACT_BARCODE_DATA = 0x3A
GET_BILL_TABLE = 0x41
GET_COIN_TABLE = 0x10
DOWNLOAD = 0x50
CHECK_CODE = 0x51
STATISTICS = 0x60
ACK = 0x00

NAK = 0xff
ILLEGAL = 0x30

SYNC = 0x02
SYNCb = b'\x02'


STATES = {
    0x10: 'Power UP',
    0x11: 'Power Up with Bill in Validator',
    0x12: 'Power Up with Bill in Stacker',
    0x13: 'Initialize',
    0x14: 'Idling',
    0x15: 'Accepting',
    0x17: 'Stacking',
    0x18: 'Returning',
    0x19: 'Unit Disabled',
    0x1A: 'Holding',
    0x1B: 'Device Busy',
    0x1C: 'Rejecting',
    0x41: 'Drop Cassette Full',
    0x42: 'Drop Cassette out of position',
    0x43: 'Validator Jammed',
    0x44: 'Drop Cassette Jammed',
    0x45: 'Cheated',
    0x46: 'Pause',
    0x47: 'Failed',
    0x80: 'Escrow position',
    0x81: 'Bill stacked',
    0x82: 'Bill returned'
    }

STATE_ESCROW = 0x80
STATE_STACKED = 0x81
STATE_RETURNED = 0x82
STATE_HOLDING = 0x1a

def GetCRC16(data):
    crc = 0
    for b in data:
        crc ^= b
        for j in range(0, 8):
            if (crc & 0x0001):
                crc >>= 1
                crc ^= 0x8408
            else:
                crc >>= 1
    return crc.to_bytes(2,'little')


def command(cmd, param, adr):
    lng = len(param)+6
    data = bytes([SYNC,adr,lng,cmd,*param])
    data += GetCRC16(data)
    return data

async def timeouted(delay, future):
    t = asyncio.get_running_loop().call_later(delay, future.cancel)
    try:
        return await future
    except Exception as e:
        logging.error(traceback.format_exc())
        raise e
    finally:
        t.cancel()

VALIDATOR = 0x03
COIN = 0x02

ASK_EXCEPTIONS = {
    NAK: Exception(NAK, 'NAK response'),
    ILLEGAL: Exception(ILLEGAL, 'ILLEGAL COMMAND')
}


class CCNET:
    def __init__(
            self,
            dev=None,
            baudrate=19200,
            adr=0x03
    ):
        self.nominals = {}
        self.baudrate = baudrate
        self.adr = adr
        self.dev = dev
        self.opened = asyncio.Future()
        self.responces = {}
        self.read_task = None
        self.state = {}
        self.state_param = {}
        self.opened.set_result(False)

    async def enable_coin(self, adr=None):
        adr = adr or self.adr
        return await self.command(SET_COIN_TYPES, b'\xff'*6, adr=adr)


    async def enable(self, adr=None):
        adr = adr or self.adr
        if adr == VALIDATOR or adr == 1:
            return await self.command(SET_BILL_TABLE, b'\xff'*6, adr=adr)
        elif adr == COIN:
            return await self.command(SET_COIN_TYPES, b'\xff'*6, adr=adr)

    async def disable(self, adr=None):
        adr = adr or self.adr
        return await self.command(SET_BILL_TABLE, b'\x00'*6, adr=adr)


    async def close(self):
        self.writer.transport.close()

    async def open(self):
        loop = asyncio.get_running_loop()
        self.opened = asyncio.Future()
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.dev, 
                baudrate=self.baudrate, 
                timeout=5, 
                rtscts=0, 
                parity=serial.PARITY_NONE, 
                stopbits=serial.STOPBITS_ONE 
                )
            self.read_task = loop.create_task(self.readforever(self.reader,  self.writer, self.opened))
        except Exception as e:
            logging.error(repr(e))
            logging.error(traceback.format_exc())
            loop.call_later(5, functools.partial(loop.create_task, self.open()))
        return self.opened

    async def stack_one(self, adr=None):
        adr = adr or self.adr
        resp = await self.wait_state( states=[STATE_ESCROW, STATE_HOLDING, STATE_STACKED], adr=adr)
        if resp.get('credit') and resp['state'] in [STATE_ESCROW, STATE_HOLDING]:
            await self.command(STACK, adr=adr)
            resp = await self.wait_state( states=[STATE_STACKED], adr=adr)
        return resp

    async def wait_state(self, states=[], adr=None):
        adr = adr or self.adr
        resp = None
        while resp is None or resp['state'] not in states:
            resp = await self.poll(adr)
        return resp

    async def poll(self, adr=None):
        adr = adr or self.adr
        if adr == VALIDATOR or adr == 1:
            return await self.command(POLL, adr=adr)
        elif adr == COIN:
            return await self.command(0x0b, adr=adr)

    async def reset(self, adr=None):
        adr = adr or self.adr
        self.state[adr] = 0x00
        s=[]
        if adr == VALIDATOR or adr == 1:
            s.append(await self.command(RESET, adr=adr, void=True))
        elif adr == COIN:
            s.append(await self.command(0x08, adr=adr, void=True))
        while self.state[adr] in [0x00,0x13]:
            await asyncio.sleep(1)
            s.append(await self.poll(adr))
        if adr == VALIDATOR or adr == 1:
            s.append(await self.command(GET_BILL_TABLE, adr=adr))
        elif adr == COIN:
            s.append(await self.command(GET_COIN_TABLE, adr=adr))
        return s

    async def write(self,data):
        await asyncio.sleep(0.1)
        logging.debug('< %s',data.hex())
        self.writer.write(data)
        await self.writer.drain()        

    async def command(self, cmd, param=b'', adr=VALIDATOR, void=False):
        o = await self.opened
        if not o:
            raise Exception('COM not connected')
        if not void:
            resf = asyncio.Future()
            self.responces[adr] = cmd, resf
        data = command(cmd, param, adr)
        await self.write(data)
        if not void:
            result = await timeouted(10, resf)
            return result

    async def on_reply(self, adr, raw):
        data = raw[3:-2]
        logging.debug(data)
        resp = {
            'adr': adr, 'raw': raw
        }

        if len(data) != 1 or data[0] not in [ACK, NAK, ILLEGAL]:
            ack = bytes([SYNC,adr,6,0])
            ack += GetCRC16(ack)
            await self.write(ack)
            logging.debug('ask')
        
        elif len(data) == 1:
            if data[0] == ACK:
                resp['error'] = None
            elif data[0] in ASK_EXCEPTIONS.keys():
                resp['error'] = ASK_EXCEPTIONS[data[0]]
            #return

        logging.debug(resp)
        logging.debug(self.responces)

        if adr in self.responces.keys():
            cmd, respf = self.responces.pop(adr)
            
            if respf.cancelled():
                return #

            resp['cmd'] = cmd

            if cmd == POLL:
                state = self.state[adr] = data[0]
                param = self.state_param[adr] = (data[1:]+b'0x0')[0]
                resp['state'] = self.state[adr]
                resp['state_param'] = self.state_param[adr]
                if state in [STATE_ESCROW, STATE_RETURNED, STATE_STACKED]:
                    resp['credit'] = [self.nominals[adr][param]]
            elif cmd == STATUS:
                resp['bill_types'] = data[0:3]
                resp['security'] = data[3:6]
            elif cmd == GET_BILL_TABLE:
                logging.debug('# %s', data.hex())
                if data[0] == b'0':
                    respf.set_exception(Exception('wrong state'))
                resp['bill_table'] = [ ]
                self.nominals[adr] = [None,] * 24
                for i in range(24):
                    bt = data[i*5:(i+1)*5]
                    bts = (256-bt[4]) * (-1) if bt[4] > 127 else bt[4]
                    btn = {
                        'denomination': bt[0] * 10**bts,
                        'country': bt[1:4].decode()
                    }
                    self.nominals[adr][i] = btn
                    if bt[0]:
                        resp['bill_table'].append(
                            btn
                        )
            respf.set_result(resp)


    async def readforever(self, reader, writer, opened):
        loop = asyncio.get_running_loop()
        try:
            opened.set_result(True)
            while True:
                logging.info('reading')
                data = await reader.readexactly(1)
                if data[0] == SYNC:
                    data += await reader.readexactly(2)
                    _, adr, lng = data
                    if lng:
                        pass
                    else:
                        logging.error('Not implemented long commands')
                    data += await reader.readexactly(lng-3)
                    if data[-2:] == GetCRC16(data[:-2]):
                        logging.debug('> %s', data.hex())
                        loop.create_task(self.on_reply(adr, data))

                else:
                    logging.error(data)

        except serial.SerialException as e:
            logging.error(repr(e))
            logging.error(traceback.format_exc())
            loop.create_task(self.open())
            raise e



async def main():
    c = CCNET('/dev/serial/by-path/pci-0000:02:00.0-usb-0:7:1.0-port0')
    await(await c.open())
    print('opened')
    print(await c.reset())
    print(await c.command(SET_BILL_TABLE, b'\xff'*6))
    #while True:
    print(await c.accept_one())

if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
