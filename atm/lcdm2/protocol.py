import asyncio
import serial
from operator import xor
from functools import reduce
import time
import logging
import struct

SOH = 0x01
STX = 0x02
ETX = 0x03
EOT = 0x04
ACK = 0x06
NCK = 0x15
ID = 0x50

# commands
PRURGE = 0x44
UPPER_DISPENSE = 0x45
STATUS = 0x46
ROMVERSION = 0x47
LOWER_DISPENSE = 0x55
UPPER_LOWER_DISPENSE = 0x56
TEST_UPPER_DISPENSE = 0x76
TEST_LOWER_DISPENSE = 0x77

ERRORS = {
    0x30: "Good",
    0x31: "Normal stop",
    0x32: "Pickup error",
    0x33: "JAM at CHK1,2 Sensor",
    0x34: "Overflow bill",
    0x35: "JAM at EXIT Sensor or EJT Sensor",
    0x36: "JAM at DIV Sensor",
    0x37: "Undefined command",
    0x38: "Upper Bill- End",
    0x3A: "Counting Error(between CHK3,4 Sensor and DIV Sensor)",
    0x3B: "Note request error",
    0x3C: "Counting Error(between DIV Sensor and EJT Sensor)",
    0x3D: "Counting Error(between EJT Sensor and EXIT Sensor)",
    0x3F: "Reject Tray is not recognized",
    0x40: "Lower Bill-End",
    0x41: "Motor Stop",
    0x42: "JAM at Div Sensor",
    0x43: "Timeout (From DIV Sensor to EJT Sensor)",
    0x44: "Over Reject",
    0x45: "Upper Cassette is not recognized",
    0x46: "Lower Cassette is not recognized",
    0x47: "Dispensing timeout",
    0x48: "JAM at EJT Sensor",
    0x49: "Diverter solenoid or SOL Sensor error",
    0x4A: "SOL Sensor error",
    0x4C: "JAM at CHK3,4 Sensor",
    0x4E: "Purge error(Jam at Div Sensor)"
}



def sensors_parse(data):
    d = int.from_bytes(data,'little')

    return {
        'chk1': bool(d & 1),
        'chk2': bool(d & 2),
        'div1': bool(d & 4),
        'div2': bool(d & 8),
        'ejt': bool(d & 16),
        'exit': bool(d & 32),
        'nearend0' : bool(d & 64),
        'always1': bool(d & 128),
        'sol': bool(d & 256),
        'cassette0': bool(d & 512),
        'cassette1': bool(d & 1024),
        'chk3': bool(d & 2048),
        'chk4': bool(d & 4096),
        'nearend1': bool(d & 8192),
        'reject': bool(d & 16384),
        'unused': bool(d & 32768)
    }    


async def timeouted(delay, future):
    t = asyncio.get_running_loop().call_later(delay, future.cancel)
    try:
        return await future
    except Exception as e:
        raise e
    finally:
        t.cancel()

def command(cmd, data=b''):
    CMD = bytes([EOT,ID,STX,cmd,*list(data),ETX])
    CMD += bytes([reduce(xor, CMD)])
    print(CMD)
    return CMD

import serial_asyncio

class LCDM():
    def __init__(self, dev=None, upper_nominal=0, lower_nominal=0):
        self.dev = dev
        self.nominals = [lower_nominal, upper_nominal]
        self.ask = asyncio.Future()
        self.ask.set_exception(Exception('Open first'))
        self.responces = {}
        self.read_task = None

    async def open(self):
        self.ask = asyncio.Future()
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.dev, baudrate=19200, timeout=5, rtscts=0, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE )
            self.read_task = asyncio.get_running_loop().create_task(self.readforever(self.reader,  self.writer))
            self.ask.set_result(None)
        except Exception as e:
            logging.error(repr(e))
            loop = asyncio.get_running_loop()
            loop.call_later(10, loop.create_task(self.open()))
        return self.ask

    async def load(self, upper_count, lower_count):
        self.counters = [lower_count, upper_count]

    async def dispense(self, ammount):
        out = 0
        errors = []

        for dispense_cmd, nominal in sorted(
                zip( [self.lower_dispense, self.upper_dispense], self.nominals ),
                reverse=True,
                key=lambda x: x[1]
        ):
            result = {'error': 0}
            if nominal:
                count, _ = divmod(ammount, nominal)
                while count:
                    if count > 60:
                        to_out = 50
                    else:
                        to_out = count
                    try:
                        result = await dispense_cmd(to_out)
                    except serial.SerialException as e:
                        result = {
                            'exit': 0,
                            'error': -1,
                            'ok': False,
                            'description': repr(e)
                        }
                    except Exception as e:
                        result={
                            'exit': 0,
                            'error': -2,
                            'description': repr(e),
                            'ok': False
                        }
                    count -= result['exit']
                    out += nominal * result['exit']
                    ammount -= nominal * result['exit']
                    if not result['ok']:
                        errors.append((result['error'], result['description']))
                        print('break 1')
                        break
            if result['error'] in [0, 0x30, 0x31, 0x38, 0x40]:
                pass
            else:
                print('break2',result)
                break
        
        return { 'out': out, 'ok': ammount==0, 'errors': errors }

    async def command_count(self, cmd, count):
        param = str(count).encode().rjust(2,b'0')
        return await self.command(cmd,param)


    async def command(self, cmd, param):
        await self.ask
        ask = self.ask = asyncio.Future()
        resf = self.responces[cmd] = asyncio.Future()
        data = command(cmd, param)
        self.writer.write(data)
        await self.writer.drain()
        await timeouted(2, ask)
        result = await  timeouted(60, resf)
        return result

    async def upper_dispense(self, count):
        return await self.command_count(UPPER_DISPENSE, count)
    
    async def lower_dispense(self, count):
        return await self.command_count(LOWER_DISPENSE, count)

    async def status(self):
        return await self.command(STATUS,b'')

    async def set_results(self,cmd,data):
        print(cmd, data.hex())

        if cmd == STATUS:
            resp = {
                'data':data, 
                'cmd': cmd, 
                'error': data[1], 
                'description':ERRORS[data[1]], 
                'ok':data[1] in [0x30,0x31],
                'sensors': sensors_parse(data[2:])
                }
        elif cmd in [UPPER_DISPENSE, LOWER_DISPENSE, TEST_LOWER_DISPENSE, TEST_UPPER_DISPENSE]:
            resp = {
                'data': data, 
                'cmd': cmd, 
                'check': int(data[0:2]),
                'exit': int(data[2:4]),
                'error': data[5],
                'description':ERRORS[data[5]], 
                'status': data[6],
                'nearend': data[6] == 0x31,
                'enough': data[6] == 0x30,
                'reject': int(data[6:8]),
                'ok': data[5] in [0x30,0x31]
            }
        else:
            resp = data.hex()
        if self.responces.get(cmd):
            self.responces.get(cmd).set_result(resp)



    async def readforever(self, reader, writer):
        try:
            while True:
                h = await reader.readexactly(1)
                print(h)
                h = h[0]
                if h == ACK:
                    self.ask.set_result(True)
                elif h == NCK:
                    self.ask.set_result(False)
                elif h == SOH:
                    i,s,c =  await reader.readexactly(3)
                    data = await reader.readuntil(bytes([ETX]))
                    b = await reader.readexactly(1)
                    bcc = bytes([reduce(xor, [h,i,s,c,*list(data)])])
                    if b==bcc:
                        writer.write(bytes([ACK]))
                        await self.set_results(c,data[:-1])
                    else:
                        writer.write(bytes([NCK]))
                    await writer.drain()
                else:
                    pass
        except serial.SerialException as e:
            print(repr(e))
            loop = asyncio.get_running_loop()
            loop.call_later(10, loop.create_task(self.open()))



async def main():
    l = LCDM('/dev/ttyUSB1', 100, 1000)

    await l.open()
    print(await l.status())
    print(await l.dispense(36000))

    
loop = asyncio.get_event_loop()
loop.create_task(main())
loop.run_forever()
loop.close()

"""
ser = serial.Serial('/dev/ttyUSB0', 19200, timeout=5, rtscts=0, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE)
#ser.open()
#ser.reset_input_buffer()

#resp = ser.read_until(bytes([ETX])) + ser.read()

#print(resp)

#ser.write(ACK)
while True:
    #ser.send_break(0.5)

    #8041b0f82f9affff5303021103002d00a2a36a610000000003aa00008dffffff0800000008000000000000000000000000000000000000000000000000000000 0450024530310311
    #4048b0f82f9affff4303821103002d00a7a36a610000000072fa0200000000000f0000000f000000000000000000000000000000000000000002000000000000 015002453031303131303030031415
    ser.write( command(UPPER_DISPENSE,b'02') )
    #ser.write( command(0x47) )
    ret = ser.read()
    print(ret)

    if not ret:
        print('timeout')
    elif ret[0] == NCK:
        print('NCK')
        continue
    elif ret[0] == ACK:
        print('ACK')
        ser.timeout = 60
        resp = ser.read_until(ETX.to_bytes(1,'big')) + ser.read()
        ser.timeout = 2
        print(resp)
        ser.write(ACK)
    else:
        resp=ser.read(255)
        print(resp)
    break

"""
