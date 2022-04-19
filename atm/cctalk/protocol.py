import asyncio
import serial_asyncio
import traceback
import functools
import logging
import serial

def add_status(text, n=1):
    def parse(resp, head):
        resp.setdefault('status',[])
        resp['status'].append({'code':head[0], "description": text})
        return n, resp
    return parse

def currencys_data(evtype, text, sign = 1):
    def parse(resp, head):
        resp.setdefault('status',[])
        resp.setdefault(evtype,[])
        resp['status'].append({'code':head[0], "description": text})
        number = head[1]
        n = 2 + number * 7
        while number>0:
            number-=1
            curr = head[2+number*7:][:7]
            resp[evtype].append({
                'denomination': sign * int.from_bytes(curr[:4], 'little')/100,
                'country': curr[4:],
                'code': head[0]
            })
        return n, resp
    return parse

def currency_data(evtype, text, sign = 1):
    def parse(resp, head):  
        resp.setdefault(evtype,[])
        curr = head[1:][:7]
        resp[evtype].append({
                'denomination': sign * int.from_bytes(curr[:4], 'little')/100,
                'country': curr[4:],
                'code': head[0]
            })
        return 8, resp
    return parse




status_c_parsers = {
    0x00: add_status('Idle'),
    0x01: currencys_data('processing', 'Dispensing'),
    0x02: currencys_data('credit', 'Dispensed', -1),
    0x03: add_status('Coins Low'),
    0x04: add_status('Empty'),
    0x05: currencys_data('processing','Jammed'),
    0x06: currencys_data('processing','Halted'),
    0x07: currencys_data('processing','Floating'),
    0x08: currencys_data('processing','Floated'),
    0x09: currencys_data('processing','Timeout'),
    0x0a: currencys_data('processing','Incomplete payout'),
    0x0b: currencys_data('processing','Incomplete float'),
    0x0c: currencys_data('credit','Cashbox paid'),
    0x0d: currency_data('credit','Coin credit'),
    0x11: add_status('Disabled'),
    0x13: add_status('Slave reset'),
    0x24: add_status('Calibration fault', 2),
}



class Commands:
    Address_Change = 251
    Address_Clash = 252
    Address_Poll = 253
    Address_Random = 250
    Empty = 24
    Float_Amount = 23
    Float_Amount_c = 40
    Float_By_Denomination = 33
    Float_By_Denomination_c = 45
    Get_Cashbox_Operation_Data = 52
    Get_Denomination_Amount = 26
    Get_Denomination_Amount_c = 42
    Get_Device_Setup = 28
    Get_Device_Setup_c = 46
    Get_Inhibit_Peripheral_Device_Value = 53
    Get_Master_Inhibit_Status = 227
    Get_Minimum_Payout = 25
    Get_Minimum_Payout_c = 41
    Get_Payout_Options = 31
    Get_Peripheral_Device_Master_Inhibit = 49
    Get_Routing = 21
    Get_Routing_c = 38
    Modify_Bill_Operating_Mode = 153
    Payout_Amount = 22
    Payout_Amount_c = 39
    Payout_By_Denomination = 32
    Payout_by_denomination_c = 44
    Pump_RNG = 161
    Read_Barcode_Data = 129
    Read_Buffered_Bill_Events = 159
    Request_Address_Mode = 169
    Request_Bill_id = 157
    Request_Bill_Operating_Mode = 152
    Request_Bill_Position = 155
    Request_Build_Code = 192
    Request_Cipher_Key = 160
    Request_Comms_Revision = 4
    Request_Country_Scaling_Factor = 156
    Request_Currency_Revision = 145
    Request_Data_Storage_Capability = 216
    Request_Encrypted_Status = 109
    Request_Encryption_Support = 111
    Request_Equipment_Category_ID = 245
    Request_Last_Mod_Date = 195
    Request_Manufacturer_ID = 246
    Request_Note_Channel_inhibits = 230
    Request_Option_Flags = 213
    Request_Polling_Priority = 249
    Request_Product_Code = 244
    Request_Serial_Number = 242
    Request_Software_Revision = 241
    Request_Status = 29
    Request_Status_c = 47
    Reset_Device = 1
    Route_Bill = 154
    Run_Unit_Calibration = 34
    Set_Bezel_Mode = 35
    Set_Denomination_Amount = 27
    Set_Denomination_Amount_c = 43
    Set_Inhibit_Peripheral_Device_Value = 50
    Set_Master_Inhibit_Status = 228
    Set_Note_Inhibit_Channels = 231
    Set_Payout_Options = 30
    Set_Peripheral_Device_Master_Inhibit = 48
    Set_Route_c = 37
    Set_Routing = 20
    Simple_Poll = 254
    Smart_Empty = 51
    Store_encryption_code = 136
    Switch_DES_key = 110
    Switch_Encryption_Code = 137





def checksum(a, useccitt=False):
    if useccitt:
        return b'Not implemented'
    else:
        return a[:-1]+bytes([(256 - sum(a)) % 256])


def splitby(it, n):
    for a in range(0, len(it), n):
        yield it[a:a+n]


ADDRESS_POLL = 253 
ADDRESS_CLASH = 252
ADDRESS_CHANGE = 251


GET_SERIAL = 242
GET_CATEGORY = 245

async def timeouted(delay, future):
    t = asyncio.get_running_loop().call_later(delay, future.cancel)
    try:
        return await future
    except Exception as e:
        logging.error(traceback.format_exc())
        raise e
    finally:
        t.cancel()


class CCTalk():
    def __init__(self,dev,baudrate=9600,adr=2):
        self.dev = dev
        self.adr = adr
        self.myadr = 1
        self.baudrate = baudrate
        self.opened = asyncio.Future()
        self.responce = None, None
        self.opened.set_result(False)
        self.eventids = {}
        self.coins = {}
        self.device_infos = {}
        self.reader, self.writer, self.read_task = None, None, None
        self.pollers = {}


    async def open(self):
        loop = asyncio.get_running_loop()
        self.opened = asyncio.Future()
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
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
    

    async def status(self, **kw):
        return await self.command(Commands.Request_Status_c, **kw)

    async def enable(self, **kw):
        adr = kw.pop('adr', self.adr)
        # if self.pollers.get(adr):
        #     self.pollers[adr].cancel()
        # self.pollers[adr] = loop.create_task(self.poll(adr=adr, **kw))
        await self.command(Commands.Set_Master_Inhibit_Status, b'\x01', **kw) # master enable
        await self.command(Commands.Set_Peripheral_Device_Master_Inhibit, b'\x00\x01')


    async def disable(self, **kw):
        adr = kw.pop('adr', self.adr)
        # if self.pollers.get(adr):
        #     self.pollers[adr].cancel()
        await self.command(Commands.Set_Master_Inhibit_Status, b'\x00', **kw)
        await self.command(Commands.Set_Peripheral_Device_Master_Inhibit, b'\x00\x00')

    async def init(self, **kw):
        loop = asyncio.get_running_loop()
        #await self.command(1, adr=adr) # reset
        #await asyncio.sleep(5)
        if kw.get('adr'):
            ar = [kw.pop('adr')]
        elif kw.get('adrs'):
            ar = kw.pop('adrs')
        else:
            ar = range(1,256)
            
        for adr in ar:
            try:
                await self.command(Commands.Simple_Poll, adr=adr, **kw)
            except:
                continue
        


            self.device_infos.setdefault(adr,{})
            for cmd in [
                    Commands.Request_Manufacturer_ID,
                    Commands.Request_Equipment_Category_ID,
                    Commands.Request_Product_Code,
                    Commands.Request_Serial_Number,
                    Commands.Request_Software_Revision
                ]:
                try:
                    data = await self.command(cmd, adr=adr, **kw)
                except:
                    continue
                self.device_infos[data['adr']][cmd] = data


            if self.device_infos[adr][245]['raw'] == b'SMART_HOPPER': 
                dr = await self.command(46, adr=adr)
                d = dr.get('raw')
                count , d = d[0], d[1:]
                for i in range(count):
                    n = d[7*i:7*i+7]
                    r = int.from_bytes(n[:-3],'little')/100
                    b = {
                        'denomination': r,
                        'country': n[-3:].decode()
                    }
                    self.coins.setdefault(adr, {})
                    self.coins[adr][i] = b
                    
            # if False:      
            #     await self.command(231, b'\xff\xff', adr=adr, **kw) # coins enable

            #     coins = [ (i,await self.command(184, bytes([i]), **kw)) for i in range(1,16)  ]
            #     for i, dr in coins:
            #         d = dr.get('raw')
            #         if not d:
            #             continue
            #         n = d[2:-1]
            #         v = d[-1:]
            #         r, c = ([0]+n.split(b'K'))[-2:]
            #         try:
            #             r = (int(r)*1000+int(c))/100
            #         except:
            #             continue
            #         b = {
            #             'variant': v,
            #             'denomination': r,
            #             'country': d[:2].decode()
            #         }
            #         self.coins.setdefault(adr,{})
            #         self.coins[adr][i]=b
            #     logging.debug(self.coins)


    async def poll(self, **kw):
        while True:
            await asyncio.sleep(2)
            await self.status(**kw)

    async def waitf(self, timeout):
        old_cmd, old_resf = self.responce
        if old_resf and not old_resf.done():
            await asyncio.wait_for(old_resf, timeout=timeout)
    
    async def command(self, cmd, data=b'', adr=None, timeout=1):
        if adr is None:
            adr = self.adr
        payload = bytes([adr, len(data), self.myadr, cmd])+data+b'\x00'
        payload = checksum(payload)
        resf = asyncio.Future()

        await self.waitf(timeout)

        self.responce = cmd, resf
        await self.write(payload)

        return await asyncio.wait_for(resf, timeout=timeout)


    async def write(self, data):
        await asyncio.sleep(0)
        logging.debug('< %s',data.hex())
        self.writer.write(data)
        await self.writer.drain()  

    async def on_event(self, adr, evdata):
        denomination = self.coins[adr].get(evdata[0],{})
        denomination['raw'] = evdata
        return denomination


    async def stack_one(self,**kw):
        while True:
            await asyncio.sleep(0.5)
            print('!')
            out = await self.status(**kw)
            if out.get('credit'):
                return out
            

    def parse_status_c(self, resp):
        data = resp['raw']
        i = 0
        while i < len(data):
            code = data[i]
            b, resp =  status_c_parsers[code](resp, data[i:])
            i += b
        return resp


    async def on_reply(self, adr, data):
        cmd, resf = self.responce
        resp = {
            'adr': adr, 'raw': data, 'cmd': cmd
        }
        logging.debug('>>'+str(resp))
        if cmd == Commands.Request_Status_c:
            resp = self.parse_status_c(resp)
        elif cmd == 229:
            newcount = data[0] - self.eventids.get(adr, 0)
            self.eventids[adr] = data[0]
            if newcount < 0:
                newcount = newcount % 256 - 1
            logging.debug(newcount)
            events = splitby(data[1:1+newcount*2],2)

            resp['events'] = []
            for evdata in events:
                resp['events'].append(
                    await self.on_event(adr, evdata)
                )

        resf.set_result(resp)


    async def readforever(self, reader, writer, opened):
        loop = asyncio.get_running_loop()
        try:
            opened.set_result(True)
            while True:
                to,lng,fro,head = await reader.readexactly(4)
                data = await reader.readexactly(lng)
                crc = await reader.readexactly(1)
                #print([to,lng,fro,head,*data,*crc])
                raw = bytes([to,lng,fro,head,*data,*crc])

                if to != self.myadr:
                    continue

                if checksum(raw)[-1] == 0:
                    adr = fro
                elif raw == checksum(bytes([to,lng,0,head,*data,0]), useccitt=True) :
                    adr = 0
                else:
                    continue

                if lng == 0 and head == 0: # ACK
                    pass

                logging.debug('> %s', raw.hex())
                loop.create_task(self.on_reply(adr, data))


        except serial.SerialException as e:
            logging.error(repr(e))
            logging.error(traceback.format_exc())
            loop = asyncio.get_running_loop()
            loop.create_task(self.open())
            raise e


async def main():
    import sys
 
    c = CCTalk(sys.argv[1], adr=3)
    

    
    await(await c.open())
    # await c.command(Commands.Reset_Device)
    # await asyncio.sleep(15)

    print('opened')

    #print(await c.command(253, adr=0))

    #print('address poll', await c.command(253))
    await c.init(adr=3)
    #coins = [ await c.command(184, bytes([i])) for i in range(1,16)  ]

    print(c.coins)
    
    await c.command(Commands.Run_Unit_Calibration)
    #print(await c.stack_one())
    
    await c.enable()
    await c.stack_one()
    await c.disable()
    await c.status()
    await c.command(Commands.Empty)

    return 

    while True:
        #await asyncio.sleep(0.25)
        out = await c.command(229,adr=2)
        if out['events']:
            print('out',out)



if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
    #loop.run_forever()
