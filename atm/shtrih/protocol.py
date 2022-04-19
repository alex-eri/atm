import pyshtrih

def test():
    device = pyshtrih.ShtrihAllCommands("rfc2217://127.0.0.1:5555", baudrate=115200, timeout=None)
    device.open_shift()

    text, quantity, price = 'test', 1, 1

    phone = pyshtrih.FD({1008: u'+79313587439'})
    email = pyshtrih.FD({1008: u'm0x3@mail.ru'})
    cashier = pyshtrih.FD({1021: u'Кассир: Пупкин В.И.'})

    item = (text, quantity*1000, price*100)


    device.open_check(0)
    device.send_tlv_struct(cashier.dump())
    device.sale( item )
    device.close_check(price*100)

    device.open_check(2)
    device.return_sale( item )
    device.close_check(price*100)

    device.open_check(0)
    device.operation_v2(1, item, subject=4)
    # >>> bytearray(b'Y')
    device.close_check(price*100)

    device.open_check(2)
    device.operation_v2(2, item, subject=4)
    device.close_check(price*100)

    device.z_report()

def main():
    pass

if __name__ == "__main__":
    main()