#!/usr/bin/env python3
"""Build small, original H8 diagnostic images without a cross compiler.

This is a fixture encoder, not an assembler or reference emulator. Expectations
are literal, independently reasoned values. No production Rust is imported.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from flash import cases as flash_cases
from boot import cases as boot_cases
from decimal_adjust import cases as decimal_cases
from sensor_i2c import cases as sensor_i2c_cases

class Program:
    def __init__(self) -> None:
        self.code = bytearray(bytes.fromhex('7907ff80'))
    def byte(self, address: int, value: int) -> None:
        self.code += bytes((0xF8, value, 0x6A, 0x88, address >> 8, address & 255))
    def word(self, address: int, value: int) -> None:
        self.code += bytes((0x79, 0, value >> 8, value & 255, 0x6B, 0x80, address >> 8, address & 255))
    def send(self, value: int) -> None:
        self.byte(0xF0EB, value)
        self.code += bytes.fromhex('6a08f0e4e80847f86a08f0e9')
    def lcd(self, data: bool, values: list[int]) -> None:
        for value in values:
            self.byte(0xffd4, 6 if data else 4)
            self.send(value)
            self.byte(0xffd4, 5)
    def finish(self) -> bytes:
        self.code += bytes.fromhex('40fe')
        image = bytearray(49152)
        image[:2] = bytes.fromhex('0100')
        if len(self.code) > 49152 - 0x100:
            raise ValueError('diagnostic code exceeds target flash')
        image[0x100:0x100 + len(self.code)] = self.code
        return bytes(image)

def handler(image: bytes, vector: int, code: str) -> bytes:
    image = bytearray(image)
    body = bytes.fromhex(code)
    if any(image[0x200:0x200+len(body)]):
        raise ValueError('handler overlaps diagnostic program')
    image[vector*2:vector*2+2] = bytes.fromhex('0200')
    image[0x200:0x200+len(body)] = body
    return bytes(image)


def cases():
    yield from flash_cases()
    yield from boot_cases()
    yield from decimal_cases(Program)
    yield from sensor_i2c_cases(Program)
    # Entry count lives in retained RAM. These physical conditions distinguish
    # a paused CPU, RES re-entry with retained RAM, and volatile charge loss.
    for name,absence,expected in [('short-retention',1000,1),
                                   ('reset-retention',5000,2),
                                   ('long-collapse',20000,1)]:
        p=Program();p.code += bytes.fromhex('6a08f8000a086a88f800')
        p.byte(0xf801,0xa5)
        yield 'power-'+name,p.finish(),{'ram':{'f800':f'{expected:02x}a5'}},f'100,supply,0\n{100+absence},supply,3000\n'
    for mv,duration in [(0,10000),(1000,30000)]:
        for delta,expected in [(-1000,'a5'),(1000,'00')]:
            p=Program();p.byte(0xf800,0xa5)
            # Observe while still below execution voltage; no reboot rewrites RAM.
            elapsed=duration+delta
            yield f'power-retention-{mv}-{elapsed}',p.finish(),{'ram':{'f800':expected}},f'{50000-elapsed},supply,{mv}\n'
    for nop, high in [(False,False),(True,False),(False,True)]:
        p=Program();p.code += bytes.fromhex('f901f8fe6a89ffca')
        if nop:p.code += bytes.fromhex('0000')
        p.code += bytes.fromhex('38f66a08fff66a88f800')
        name='irq-mux-'+('high' if high else 'settled' if nop else 'immediate-clear')
        yield name,p.finish(),{'ram':{'f800':'00' if nop or high else '01'}},f'0,analog,pb0,{3000 if high else 0}\n'

    for clear_source in [False,True]:
        p=Program();p.code=bytearray(bytes.fromhex('7907ff70'))
        for a,v in [(0xfffb,0x44),(0xf0f1,0),(0xf0f2,1)]:p.byte(a,v)
        p.word(0xf0f8,0 if clear_source else 6)
        p.code += bytes.fromhex('7900')+(0xf0f3 if clear_source else 0xf0f2).to_bytes(2,'big')
        # phi clock; leaving GRA=6 occurs seven states after starting, between
        # BCLR's operand read/NEXT and write. GRA=0 sets before its operand read.
        p.code += bytes.fromhex('f980067f00006a89f0f0')
        return_pc=0x100+len(p.code)+4
        p.code += bytes.fromhex('7d007200')
        p.byte(0xf802,0xa5)
        p.code += bytes.fromhex('6a08f0f26a88f803')
        image=handler(p.finish(),35,'6a08f0f36a88f8006a08f0f26a88f801f8006a88f0f35670')
        expected={'ram':{'f800':'0000a571' if clear_source else '7170a570'},'interrupt_entries':0 if clear_source else 1}
        if not clear_source:expected['ram']['ff6e']=f'{return_pc:04x}'
        yield 'irq-'+('source-clear-cancels' if clear_source else 'enable-clear-admission'),image,expected,None

    p=Program();p.code=bytearray(bytes.fromhex('7907ff700735570040fe'))
    image=handler(p.finish(),8,'40fe')
    yield 'exception-ccr-stack-word',image,{'ram':{'ff6c':'35350108'}},None

    p=Program()
    for i,a in enumerate(range(0xf078,0xf080)):
        p.code += bytes((0x6a,8,a>>8,a&255,0x6a,0x88,0xf8,i))
    yield 'iic-reset-map',p.finish(),{'ram':{'f800':'007d38000000ffff'}},None

    p=Program();p.byte(0xf07a,0x88);p.byte(0xf07e,1)
    p.code += bytes.fromhex('6a08f07e6a88f800')
    p.byte(0xf078,0x90);p.byte(0xf07c,0)
    p.code += bytes.fromhex('6a08f07c6a88f801')
    p.byte(0xf07c,0)
    p.code += bytes.fromhex('6a08f07c6a88f802')
    yield 'iic-holding-order-and-flag-clear',p.finish(),{'ram':{'f800':'808000'}},None

    p=Program()
    for a,v in [(0xfffb,0x24),(0xf087,3),(0xf078,0xb0),(0xf079,0xbd),(0xf07e,0xa0)]:p.byte(a,v)
    p.code += bytes.fromhex('6a08f07ce84047f86a08f07c6a88f8006a08f07b6a88f801')
    p.byte(0xf079,0x3d)
    p.code += bytes.fromhex('6a08f07ce80847f86a08f07c6a88f8046a08f0786a88f8026a08f0796a88f803')
    yield 'iic-master-nack-and-stop',p.finish(),{'ram':{'f800':'c002b07dc8'}},None

    def iic_address_input(address):
        edges=[(0,'p90',1),(0,'p91',1),(100,'p91',0)]
        time=120
        for bit in range(7,-1,-1):
            edges += [(time,'p90',0),(time,'p91',int(bool(address&(1<<bit)))),(time+20,'p90',1)]
            time += 40
        edges += [(time,'p90',0),(time,'p91',1),(time+20,'p90',1),(time+40,'p90',0),
                  (time+60,'p91',0),(time+80,'p90',1),(time+100,'p91',1)]
        return ''.join(f'{t},digital,{pin},{v}\n' for t,pin,v in edges)
    for address,expected in [(0x54,'5402807d0a'),(0,'0003807d0b')]:
        p=Program()
        for a,v in [(0xfffb,0x24),(0xf087,3),(0xf07d,0x54),(0xf078,0x80)]:p.byte(a,v)
        p.code += bytes.fromhex('6a08f07ce82047f86a08f07f6a88f8006a08f07c6a88f801')
        p.code += bytes.fromhex('6a08f07ce80847f86a08f07c6a88f8046a08f0786a88f8026a08f0796a88f803')
        yield 'iic-slave-'+('address' if address else 'general-call'),p.finish(),{'ram':{'f800':expected}},iic_address_input(address)

    p=Program()
    for a,v in [(0xfffb,0x24),(0xf087,3),(0xf07d,0x54),(0xf07b,0x20),(0xf078,0x80)]:p.byte(a,v)
    p.code += bytes.fromhex('067f018040fc')
    image=handler(p.finish(),34,'6a08f07f6a88f8006a08f07c6a88f8015670')
    yield 'iic-slave-receive-interrupt',image,{'ram':{'f800':'5402'},'interrupt_entries':1},iic_address_input(0x54)

    p=Program();p.word(0xf0f8,0x1234)
    p.code += bytes.fromhex('6a08f0f86a88f8006a08f0f96a88f801')
    p.byte(0xf0f8,0xab);p.byte(0xf0f9,0xcd)
    p.code += bytes.fromhex('6b00f0f86b80f802')
    yield 'register-native-word-byte-lanes',p.finish(),{'ram':{'f800':'12341234'}},None

    p=Program()
    for i,v in enumerate([3,0xfc]):
        p.byte(0xf088,v)
        p.code += bytes((0x6a,8,0xf0,0x88,0x6a,0x88,0xf8,i))
    p.word(0xf084,0xab12);p.word(0xc000,0xcd34)
    p.code += bytes.fromhex('6b00f0846b80f8026b00c0006b80f80401006b00fffe01006b80f806')
    yield 'register-holes-and-mixed-word',p.finish(),{'ram':{'f800':'00000012000000000100'}},None

    p=Program();p.byte(0xfffb,6);p.byte(0xf0dc,0x80)
    p.code += bytes.fromhex('6a08ffde6a88f800')
    p.byte(0xffbe,8)
    p.code += bytes.fromhex('6a08ffde6a88f801')
    yield 'register-comparator-digital-read',p.finish(),{'ram':{'f800':'1000'}},'0,analog,pb4,3000\n'

    p=Program()
    for a,v in [(0xfffb,0x0c),(0xffc0,0x20),(0xff92,0xfd),(0xff94,0x0f),(0xff95,0x3f)]:p.byte(a,v)
    for i,a in enumerate([0xff92,0xff94,0xff95]):
        p.code += bytes((0x6a,8,a>>8,a&255,0x6a,0x88,0xf8,i))
    p.word(0xff8c,3);p.word(0xff8e,1);p.byte(0xff92,0xff)
    p.code += bytes.fromhex('6b00ff8e6b80f804')
    # PWCK=111 parks the counter; live latches and a valid source resume it.
    p.word(0xff8c,7);p.word(0xff8e,2);p.byte(0xff94,2)
    p.code += bytes.fromhex('6a08ffd4e80447f86a88f806')
    yield 'aec-live-pwm-and-reserved-fields',p.finish(),{'ram':{'f800':'fd0f3f','f804':'000004'}},None

    p=Program();p.byte(0xfffa,7);p.byte(0xf0d0,0x78);p.byte(0xf0d1,0x42)
    p.code += bytes.fromhex('6a08f0d16a88f800')
    p.byte(0xf0d0,0xf8);p.byte(0xf0d0,0xfe)
    p.code += bytes.fromhex('6a08f0d16a88f801')
    p.byte(0xf0d1,0xff);p.byte(0xf0d0,0xf8)
    p.code += bytes.fromhex('6a08fff7e80447f86a88f8026a08f0d16a88f803')
    yield 'timer-b1-live-load-and-mode',p.finish(),{'ram':{'f800':'424204ff'}},None

    for busy_write in [False,True]:
        p=Program();p.byte(0xffb1,0x12);p.byte(0xffb1,0xa2)
        for a,v in [(0xf06c,0x10),(0xf06c,0),(0xf06f,0x0f),(0xf06d,0x7f)]:p.byte(a,v)
        data=[0x59,0x59,0x23,6] if busy_write else [0x1f,0x1a,0x2f,7]
        for i,v in enumerate(data):p.byte(0xf068+i,v)
        p.byte(0xf06c,0xc8)
        p.code += bytes.fromhex('6a08f068e88047f8') # wait for busy entry
        if busy_write:
            p.byte(0xf068,0x12)
            p.code += bytes.fromhex('6a08f0686a88f800')
        p.code += bytes.fromhex('6a08f068e88046f8') # wait for pending commit
        for i,a in enumerate([0xf068,0xf069,0xf06a,0xf06b,0xf067]):
            p.code += bytes((0x6a,8,a>>8,a&255,0x6a,0x88,0xf8,i+1))
        expected='92000000007f' if busy_write else '00101a2f0707'
        name='rtc-calendar-busy-write' if busy_write else 'rtc-calendar-raw-digits-and-alias'
        yield name,p.finish(),{'ram':{'f800':expected}},None

    p=Program();p.byte(0xf06f,0x18);p.byte(0xffc0,2)
    p.code += bytes.fromhex('6a08ffd4e80146f86a88f8006a08ffd4e80147f86a88f8016a08f06c6a88f802')
    yield 'rtc-clock-output-with-run-clear',p.finish(),{'ram':{'f800':'000100'}},None
    for supply,code in [(3300,838),(3000,819),(2700,796),(2400,768)]:
        p=Program();p.byte(0xfffa,0x13);p.byte(0xffbe,7);p.code += bytes(20)
        for slot,(direction,latch,pull) in enumerate([(16,16,0),(16,0,0),(0,16,16)]):
            for a,v in [(0xffeb,direction),(0xffdb,latch),(0xf086,pull)]:p.byte(a,v)
            p.byte(0xffbf,0x80);p.code += bytes.fromhex('6a08ffbfe88046f8')
            p.code += bytes.fromhex('6b00ffbc6b80')+(0xf800+2*slot).to_bytes(2,'big')
        yield f'adc-battery-supply-{supply}',p.finish(),{'ram':{'f800':f'{code<<6:04x}00000000'}},f'0,supply,{supply}\n'

    p=Program();p.byte(0xfffa,0x13);p.code += bytes(20)
    for i,mode in enumerate([0x04,0x14,0x24,0x34,0x00]):
        p.byte(0xffbe,mode);p.byte(0xffbf,0x80)
        p.code += bytes.fromhex('6a08ffbfe88046f8')
        p.code += bytes.fromhex('6b00ffbc6b80')+(0xf800+2*i).to_bytes(2,'big')
    yield 'adc-clock-selections-and-open-mux',p.finish(),{'ram':{'f800':'ffc0'*5}},'0,analog,pb0,3300\n'

    for rising in [False,True]:
        p=Program()
        for a,v in [(0xfffa,0x13),(0xffca,8),(0xfff2,0x20 if rising else 0),
                    (0xffbe,0x64),(0xfff4,0x40)]:p.byte(a,v)
        p.code += bytes.fromhex('067f018040fc')
        image=handler(p.finish(),38,'6b00ffbc6b80f8006a08fff76a88f802f8006a88fff740fe')
        timeline=f'0,analog,pb0,3300\n0,digital,adtrg,{int(not rising)}\n100,digital,adtrg,{int(rising)}\n'
        yield 'adc-trigger-'+('rising' if rising else 'falling'),image,{'ram':{'f800':'ffc040'},'interrupt_entries':1},timeline

    p=Program()
    p.byte(0xfffa,0x13);p.byte(0xffbe,0x64) # TEST pin not selected as ADTRG.
    p.code += bytes(6000)
    p.code += bytes.fromhex('6a08ffbf6a88f8006b00ffbc6b80f802')
    yield 'adc-trigger-pin-gate',p.finish(),{'ram':{'f800':'3f','f802':'0000'}},'0,digital,adtrg,1\n100,digital,adtrg,0\n'

    p=Program()
    for a,v in [(0xfffb,0x44),(0xfff5,0x82),(0xf0f1,0x40),(0xf0f0,0x80)]:p.byte(a,v)
    p.code += bytes(1000)
    # Watch-selected TCNT cannot count while X1 is stopped. OSCF is status.
    p.code += bytes.fromhex('6b00f0f66b80f8006a08fff56a88f802')
    p.byte(0xfff5,0xa2) # ROSC/32 works while SUBSTP stays set; OSCF stays zero.
    p.code += bytes.fromhex('6a08fff56a88f8036b00f0f647fa')
    p.byte(0xf804,0xa5)
    yield 'oscillator-stopped-crystal-and-rosc-mux',p.finish(),{'ram':{'f800':'000080a0a5'}},None

    # REJ09B0152-0300 §12.2 and TN-H8*-A309B/E. These are register
    # observations by original guest code, with explicit instruction alignment.
    def record(p, address, slot):
        p.code += bytes((0x6a, 0x08, address >> 8, address & 255,
                         0x6a, 0x88, 0xf8, slot))
    p=Program()
    for i,a in enumerate(range(0xffb0,0xffb4)):record(p,a,i)
    for i,v in enumerate([0x12,0xa2,0x8e],4):
        p.byte(0xffb1,v);record(p,0xffb1,i)
    p.byte(0xffb3,0x55);record(p,0xffb3,7)
    p.byte(0xffb1,0x5e);record(p,0xffb1,8)
    p.byte(0xffb3,0xc3);record(p,0xffb3,9)
    yield 'watchdog-qualified-controls',p.finish(),{'ram':{'f800':'f0ae5700beba aa00fac3'.replace(' ','')}},None

    p=Program()
    for v in [0x9e,0xa2,0x8e]:p.byte(0xffb1,v)
    slot=0
    for clear in [0x87,0xc7,0x97]:
        p.byte(0xffb2,0x28);record(p,0xffb2,slot);slot+=1
        for pc_bit1 in [0,2]:
            p.code += bytes((0xf8,clear))
            if (0x100+len(p.code))&2 != pc_bit1:p.code += bytes(2)
            p.code += bytes.fromhex('38b2')
            record(p,0xffb2,slot);slot+=1
    p.byte(0xffb2,0x28)
    p.word(0xffb2,0x8700);record(p,0xffb2,9)
    p.byte(0xffb2,0x87);record(p,0xffb2,10)
    yield 'watchdog-interval-clear-alignment',p.finish(),{'ram':{'f800':'7f7f577f7f777f7f5f7f57'}},None

    p=Program()
    for a,v in [(0xffb1,0x5e),(0xffb3,0xff),(0xffb2,0x28),(0xfffb,0)]:p.byte(a,v)
    record(p,0xffb2,0) # Reads OVF=0 before the first ROSC/2048 edge.
    p.code += bytes(8000) # Four thousand NOPs: beyond the first 1.5625-ms edge.
    p.byte(0xffb2,0x7f) # That old read of zero cannot clear a new OVF.
    record(p,0xffb2,1)
    p.byte(0xffb2,0x7f);record(p,0xffb2,2)
    yield 'watchdog-overflow-read-qualification',p.finish(),{'ram':{'f800':'7fff7f'}},None
    for name,enable,expected,timeline in [
        ('sensor-low-g',1,'0a00','0,accel,0,0,0\n'),
        ('sensor-high-g',2,'0500',None),
        ('sensor-self-test-input',1,'0a00',None),
    ]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
            p.byte(a,v)
        for a,v in [(0x0b,enable),(0x0c,32),(0x0d,0),(0x0e,32),(0x0f,0)]:
            p.byte(0xffdc,0);p.send(a);p.send(v);p.byte(0xffdc,1)
        if name=='sensor-self-test-input':
            p.byte(0xffdc,0);p.send(0x0a);p.send(8);p.byte(0xffdc,1)
        p.code += bytes(20000)
        for slot in range(2):
            p.byte(0xffdc,0);p.send(0x89);p.send(0);p.code += bytes((0x6a,0x88,0xf8,slot));p.byte(0xffdc,1)
            p.byte(0xffdc,0);p.send(0x0a);p.send(0x40);p.byte(0xffdc,1)
        yield name,p.finish(),{'ram':{'f800':expected}},timeline
    for name in ['sensor-self-test-completion','sensor-image-update','sensor-autowake-asleep','sensor-autowake-awake']:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
            p.byte(a,v)
        timeline=None
        if name.startswith('sensor-autowake'):
            for a,v in [(0x0b,0),(0x15,0x81),(0x0a,1)]:
                p.byte(0xffdc,0);p.send(a);p.send(v);p.byte(0xffdc,1)
            irq=Program();irq.byte(0xffdc,0);irq.send(0x80);irq.send(0)
            irq.code += bytes.fromhex('6a88f800');irq.byte(0xffdc,1)
            image=handler(p.finish(),7,(irq.code[4:]+bytes.fromhex('40fe')).hex())
            awake=name.endswith('-awake')
            timeline=f'{21000 if awake else 1000},nmi,0\n'
            expected='02' if awake else 'ff'
        elif name=='sensor-self-test-completion':
            p.byte(0xffdc,0);p.send(0x0a);p.send(4);p.byte(0xffdc,1)
            p.code += bytes(20000)
            p.byte(0xffdc,0);p.send(0x89)
            for slot in range(2):
                p.send(0);p.code += bytes((0x6a,0x88,0xf8,slot))
            p.byte(0xffdc,1);image=p.finish();expected='8000'
        else:
            p.byte(0xffdc,0);p.send(0x0a);p.send(0x30);p.byte(0xffdc,1)
            p.byte(0xffdc,0);p.send(0x8b);p.send(0);p.code += bytes.fromhex('6a88f800');p.byte(0xffdc,1)
            p.byte(0xffdc,0);p.send(0x0b);p.send(0);p.byte(0xffdc,1)
            p.code += bytes(2000)
            p.byte(0xffdc,0);p.send(0x8b);p.send(0);p.code += bytes.fromhex('6a88f801');p.byte(0xffdc,1)
            image=p.finish();expected='ff03'
        yield name,image,{'ram':{'f800':expected}},timeline
    p=Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
        p.byte(a,v)
    p.code += bytes(12000) # First complete cold vector, still +1 g.
    p.byte(0xffdc,0);p.send(0x86);p.send(0)
    p.code += bytes.fromhex('6a88f800');p.byte(0xffdc,1)
    p.byte(0xffdc,0);p.send(0x0a);p.send(0x20);p.byte(0xffdc,1)
    p.code += bytes(14000) # Image reload and analog settling at -1 g.
    for slot,address in [(1,7),(2,6),(3,7)]:
        p.byte(0xffdc,0);p.send(0x80|address);p.send(0)
        if slot==2:p.code += bytes.fromhex('e8c0') # Freshness can change between these reads.
        p.code += bytes((0x6a,0x88,0xf8,slot));p.byte(0xffdc,1)
    yield 'sensor-image-keeps-read-pair',p.finish(),{'ram':{'f800':'012000e0'}},'4000,accel,0,0,-1000000\n'

    for pulse in [False, True]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
            p.byte(a,v)
        p.byte(0xffdc,0);p.send(0x14);p.send(6);p.byte(0xffdc,1) # +/-2 g, 1500 Hz.
        p.byte(0xffdc,0);p.send(0x15);p.send(0x88);p.byte(0xffdc,1) # Unshadowed MSB reads.
        p.byte(0xf800,0)
        p.code += bytes.fromhex('79020200') # Poll through the pulse's decay.
        loop=len(p.code)
        p.byte(0xffdc,0);p.send(0x83);p.send(0) # X MSB only; no freshness bit.
        p.code += bytes.fromhex('e8ff4706') # Any nonzero sample latches the witness.
        p.byte(0xf800,1)
        p.byte(0xffdc,1)
        p.code += bytes.fromhex('1b52') # DEC.W #1,R2; BNE loop.
        p.code += bytes((0x46,(loop-len(p.code)-2)&255))
        timeline='3200,accel,1000000,0,1000000\n3250,accel,0,0,1000000\n' if pulse else None
        yield 'sensor-between-conversion-'+('pulse' if pulse else 'control'),p.finish(),{'ram':{'f800':'01' if pulse else '00'}},timeline

    for name,reg14,offset,expected,timeline in [
        ('sensor-factory-defaults',None,None,{'f800':'031496a0960000a20d0e80'},None),
        ('sensor-offset-2g',6,0x40,{'f800':'014264'},None),
        ('sensor-offset-4g',14,0x40,{'f800':'012164'},None),
        ('sensor-offset-8g',22,0x40,{'f800':'811064'},None),
        ('sensor-temperature',6,None,{'f800':'014082'},'0,temperature,35000\n'),
    ]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
            p.byte(a,v)
        for address,value in ([(0x14,reg14)] if reg14 is not None else []) + ([(0x0a,0x10),(0x18,offset)] if offset is not None else []):
            p.byte(0xffdc,0);p.send(address);p.send(value);p.byte(0xffdc,1)
        p.code += bytes(20000) # More than 3 ms cold acquisition time.
        p.byte(0xffdc,0);p.send(0x8b if reg14 is None else 0x86)
        for byte in range(11 if reg14 is None else 3):
            p.send(0);p.code += bytes((0x6a,0x88,0xf8,byte))
        p.byte(0xffdc,1)
        yield name,p.finish(),{'ram':expected},timeline
    p = Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
        p.byte(a,v)
    p.byte(0xffdc,0)
    for value in [0x0c,0x20,0x0d,2]: p.send(value)
    p.byte(0xffdc,1);p.byte(0xffdc,0);p.send(0x8c)
    for address in [0xf800,0xf801]:
        p.send(0)
        p.code += bytes((0x6a,0x88,address>>8,address&255))
    p.byte(0xffdc,1)
    yield 'sensor-paired-writes',p.finish(),{'ram':{'f800':'2002'}},None

    p = Program()
    p.byte(0xffe4,7);p.byte(0xffd4,5) # LCD/EEPROM deselected.
    p.byte(0xffdc,3);p.byte(0xffec,7) # GPIO CS/SCK/SDI, mode-3 idle.
    def gpio_byte(value):
        for bit in range(7,-1,-1):
            data=((value>>bit)&1)<<2
            p.byte(0xffdc,data);p.byte(0xffdc,data|2)
    p.byte(0xffdc,2)
    gpio_byte(0x15);gpio_byte(0) # Select three-wire, same write protocol.
    p.byte(0xffdc,3);p.byte(0xffdc,2)
    gpio_byte(0x80)
    p.byte(0xffec,3) # Release SDI/SDA before turnaround.
    p.byte(0xffdc,0);p.byte(0xffdc,2) # Ninth edge launches D7.
    for bit in range(16):
        p.byte(0xffdc,0)
        p.code += bytes((0x6a,0x08,0xff,0xdc,0x6a,0x88,0xf8,bit))
        p.byte(0xffdc,2)
    p.byte(0xffdc,3)
    yield 'sensor-three-wire-gpio',p.finish(),{'ram':{'f800':'00000000000004000000000400000000'}},None

    for name in ['lcd-bitplanes', 'lcd-segment-reversal', 'lcd-duty-override', 'lcd-icon-reset']:
        p = Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
            p.byte(a,v)
        p.lcd(False, [0x44,32,0x48,64,0xab,0x2f,0xe8,0xaf])
        if name == 'lcd-bitplanes':
            p.lcd(True, [1,0,0,1,1,1])
            expected = {'pixels':{'0000':'02010300'}, 'display_on':True}
        elif name == 'lcd-segment-reversal':
            p.lcd(False, [0x17,0x0d,0xa1])
            p.lcd(True, [1,1,0,1,1,0])
            expected = {'pixels':{'0000':'02010300'}, 'lcd':{'00fa':'010100010100'}}
        elif name == 'lcd-duty-override':
            p.lcd(False, [0x48,16,0xa7,0xa5,0x48,0xff])
            expected = {'pixels':{'0000':'03030303','05ff':'03000000'}}
        else:
            p.lcd(False, [0xa3])
            p.lcd(True, [0xfe,0xff])
            p.lcd(False, [0xa2])
            p.lcd(True, [0xff])
            p.lcd(False, [0xb0])
            p.lcd(True, [0x55])
            p.lcd(False, [0x40,64,0xe2])
            p.lcd(True, [0xaa])
            expected = {'icons':{'0000':'00010100'}, 'lcd':{'0000':'aa000055'},
                        'display_on':True, 'display_start':0}
        yield name,p.finish(),expected,None
    p = Program()
    p.code += bytes.fromhex('7a0011223344f0aaf8bb7908ccdd01006b80f800')
    yield 'register-aliases', p.finish(), {'ram': {'f800': 'ccddaabb'}}, None
    p = Program()
    # GNU gas movlh.s / h8300.exp golden bytes, also MOV.L manual p.127.
    p.code += bytes.fromhex('7a010000f8007a0011223344010078906ba000000020')
    p.code += bytes.fromhex('02096a89f800')
    yield 'long-displacement-store', p.finish(), {'ram': {'f800': '80', 'f820': '11223344'}}, None
    p = Program()
    p.code += bytes.fromhex('f880888002096a88f8006a89f801')
    yield 'add-byte-flags', p.finish(), {'ram': {'f800': '0087'}}, None
    p = Program()
    p.code += bytes.fromhex('f82a5e0001206a88f80040fe')
    p.code += bytes(0x20-len(p.code))
    p.code += bytes.fromhex('88015470')
    yield 'call-return-stack', p.finish(), {'ram': {'f800': '2b', 'ff7e': '010a'}}, None
    p = Program()
    p.code += bytes.fromhex('7a00f8a540fe01006b80f8205a00f820')
    yield 'execute-from-ram', p.finish(), {'er0': 0xF8A540A5}, None
    p = Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),(0xffec,1),(0xffdc,1)]:
        p.byte(a,v)
    p.byte(0xffd4,1); p.send(6); p.byte(0xffd4,5)
    p.byte(0xffd4,1)
    for value in [2,0,0x7e,0xaa,0xbb,0xcc,0xdd]: p.send(value)
    p.byte(0xffd4,5)
    yield 'serial-eeprom-page-wrap', p.finish(), {'eeprom': {'007e':'aabb','0000':'ccdd'}, 'nv_commits':1}, None
    p = Program()
    for a,v in [(0xffd6,1),(0xffe6,5),(0xfffa,0x43),(0xff91,0xd0),(0xff99,1),
                (0xffa7,0x80),(0xff9a,0x20),(0xff9b,0xa5),(0xffd6,0)]:
        p.byte(a,v)
    yield 'infrared-transmit', p.finish(), {'ir_events':10}, None
    p = Program()
    for a,v in [(0xffd6,1),(0xffe6,5),(0xfffa,0x43),(0xff91,0xd1),(0xff99,1),
                (0xffa7,0x80),(0xff9a,0x10),(0xffd6,0)]: p.byte(a,v)
    p.code += bytes.fromhex('6a08ff9ce84047f86a08ff9d6a88f800')
    bits = [0] + [(0xa5 >> i) & 1 for i in range(8)] + [1]
    rows = ['# Nominal SIR pulses; digital software fixture, not a hardware capture.']
    for i,one in enumerate(bits):
        if not one:
            at = 500 + round(i*64*1_000_000/3_686_400)
            rows.extend([f'{at},ir,1',f'{at+3},ir,0'])
    yield 'infrared-receive', p.finish(), {'ram':{'f800':'a5'}}, '\n'.join(rows)+'\n'

    p=Program()
    p.byte(0xffe6,5)
    for value in [4,5,1,0]:p.byte(0xffd6,value)
    p.byte(0xfffa,0x43);p.byte(0xff91,0xd0)
    p.code += bytes.fromhex('6a08ffd66a88f800') # PCR output reads latch, despite SCI's high TXD.
    p.byte(0xff91,0xd2);p.byte(0xff91,0xc0)
    yield 'sci-gpio-optical-mux',p.finish(),{'ram':{'f800':'02'},'ir_events':4},None

    for name,smr,data,parity,stop,expected in [
        ('sci-five-n',0x24,0xf5,None,1,'8415'),
        ('sci-five-even',0x64,0xf5,1,1,'8415'),
        ('sci-five-odd',0x74,0xf5,0,1,'8415'),
        ('sci-parity-error',0x20,0xa5,1,1,'8ca5'),
        ('sci-framing-error',0,0xa5,None,0,'94a5'),
    ]:
        p=Program()
        for a,v in [(0xfffa,0x43),(0xff98,smr),(0xff99,0),(0xff9a,0x10)]:p.byte(a,v)
        p.code += bytes.fromhex('6a08ff9ce87847f8') # Wait for data OR a receive error.
        if name.startswith('sci-five'):
            p.code += bytes.fromhex('6a08ff9d6a88f8016a08ff9c6a88f800')
        else:
            p.code += bytes.fromhex('6a08ff9c6a88f8006a08ff9d6a88f801')
        bits=[0]+[(data>>i)&1 for i in range(5 if smr&4 else 8)]
        if parity is not None:bits.append(parity)
        bits.append(stop)
        rows=['0,digital,p31,1']
        for i,bit in enumerate(bits):rows.append(f'{500+round(i*32*1_000_000/3_686_400)},digital,p31,{bit}')
        yield name,p.finish(),{'ram':{'f800':expected}},'\n'.join(rows)+'\n'

    p=Program()
    for a,v in [(0xfffa,0x43),(0xff99,0),(0xff9a,0x10)]:p.byte(a,v)
    p.code += bytes(5000)
    p.code += bytes.fromhex('6a08ff9c6a88f8006a08ff9d6a88f8016a08ff9c6a88f802')
    rows=['0,digital,p31,1']
    for start,value in [(500,0xa5),(800,0x3c)]:
        for i,bit in enumerate([0]+[(value>>i)&1 for i in range(8)]+[1]):
            rows.append(f'{start+round(i*32*1_000_000/3_686_400)},digital,p31,{bit}')
    yield 'sci-overrun-retains-rdr',p.finish(),{'ram':{'f800':'e4a5a4'}},'\n'.join(rows)+'\n'

    p=Program()
    for a,v in [(0xfffa,0x43),(0xff91,0xd0),(0xff98,0x80),(0xff99,0),
                (0xff9a,0x32),(0xff9b,0xa5)]:p.byte(a,v)
    rows=['0,digital,p30,1','0,digital,p31,0']
    for i in range(8):
        p.code += bytes.fromhex('6a08ffd6e80146f86a08ffd6')
        p.code += bytes((0x6a,0x88,0xf8,i))
        p.code += bytes.fromhex('6a08ffd6e80147f8')
        at=500+i*100
        rows += [f'{at},digital,p31,{(0x3c>>i)&1}',f'{at},digital,p30,0',f'{at+50},digital,p30,1']
    p.code += bytes.fromhex('6a08ff9c6a88f8106a08ff9d6a88f811')
    yield 'sci-external-synchronous',p.finish(),{'ram':{'f800':'0400060202060004','f810':'c43c'}},'\n'.join(rows)+'\n'

    # MOV stores must sample an aliased register *after* predecrement.
    # ADE-602-053A pp.121,123,125. Literal expectations are not obtained
    # by executing HachiStep or importing its decoder.
    for suffix, opcode, address, expected in [
        ('byte', '6ca2', 'f7ff', 'f7'),
        ('word', '6da2', 'f7fe', 'f7fe'),
        ('long', '01006da2', 'f7fc', '1122f7fc'),
    ]:
        p=Program();p.code += bytes.fromhex('7a021122f800' + opcode)
        yield 'predecrement-alias-'+suffix, p.finish(), {'ram':{address:expected}}, None

    p=Program()
    p.byte(0xfffb,0x44);p.byte(0xffe4,7);p.byte(0xffd4,4)
    p.word(0xf0f6,0x1234);p.byte(0xf0f4,0x8c);p.byte(0xf0f2,1);p.byte(0xffd4,5)
    p.code += bytes.fromhex('067f018040fc')
    image=handler(p.finish(),35,'6b00f0f86b80f7806a08f0f3f8006a88f0f35670')
    yield 'timer-w-gpio-capture',image,{'ram':{'f780':'1234'},'interrupt_entries':1},None

    p=Program();p.byte(0xfffb,6);p.byte(0xf0dc,0xc8)
    p.code += bytes(128) # settle before arming the comparator through CMDR
    p.code += bytes.fromhex('6a08f0de067f018040fc')
    image=handler(p.finish(),21,'f8016a88f7806a08f0def8006a88f0de5670')
    timeline='0,analog,pb4,1000\n200,analog,pb4,2100\n'
    yield 'comparator-read-armed-wake',image,{'ram':{'f780':'01'},'interrupt_entries':1},timeline

    p=Program()
    for a,v in [(0xfffb,6),(0xf0dc,0xc8),(0xf0dd,0xc8)]:p.byte(a,v)
    p.code += bytes(128)+bytes.fromhex('6a08f0de067f018040fc')
    image=bytearray(p.finish())
    for channel,vector in enumerate([21,22]):
        address=0x200+channel*0x40
        image[vector*2:vector*2+2]=address.to_bytes(2,'big')
        code=bytes.fromhex('f8')+bytes([vector])+bytes.fromhex('6a88')+(0xf800+channel).to_bytes(2,'big')
        code+=bytes.fromhex('6a08f8040a086a88f8046a88')+(0xf805+channel).to_bytes(2,'big')
        code+=bytes.fromhex('6a08f0de6a88')+(0xf802+channel).to_bytes(2,'big')
        code+=bytes.fromhex('f8')+bytes([0xef if channel==0 else 0xdf])+bytes.fromhex('6a88f0de5670')
        image[address:address+len(code)]=code
    image[72:74]=bytes.fromhex('0280') # reserved-vector sentinel
    image[0x280:0x28a]=bytes.fromhex('f8ee6a88f81040fe0000')
    timeline='0,analog,pb4,1000\n0,analog,pb5,1000\n200,analog,pb4,2100\n200,analog,pb5,2100\n'
    yield 'comparator-channel-priority',bytes(image),{'ram':{'f800':'15163323020102','f810':'00'},'interrupt_entries':2},timeline

    p=Program()
    # Select external reference, retain prohibited CMLS and disabled CRS bits.
    for a,v in [(0xfffb,6),(0xffc2,1),(0xf0dc,0xbf)]:p.byte(a,v)
    p.code+=bytes(128)+bytes.fromhex('6a08f0dc6a88f8006a08f0de6a88f801')
    p.byte(0xfffb,4)
    p.code+=bytes(128)+bytes.fromhex('6a08f0dc6a88f8026a08f0de6a88f803')
    p.byte(0xfffb,6)
    p.code+=bytes(128)+bytes.fromhex('6a08f0dc6a88f8046a08f0de6a88f805')
    timeline='0,analog,vcref,1500\n0,analog,pb4,1000\n'
    yield 'comparator-live-external-gating',p.finish(),{'ram':{'f800':'bf00bf00bf00'}},timeline

    for gate_irq in [False,True]:
        p=Program()
        for a,v in [(0xfffb,12),(0xffc0,8),(0xffc0,0x28),(0xff92,0x10),(0xff95,0x17),
                    (0xfff3 if gate_irq else 0xfff4,4 if gate_irq else 1)]:p.byte(a,v)
        p.code += bytes.fromhex('067f018040fc')
        isr='f8016a88f7802895f8173895f80038'+('f6' if gate_irq else 'f7')+'5670'
        image=handler(p.finish(),18 if gate_irq else 32,isr)
        rows=['0,digital,p11,0','0,digital,p12,1']
        if gate_irq:rows += ['100,digital,p12,0']
        else:
            for i in range(256):rows += [f'{100+10*i},digital,p11,1',f'{105+10*i},digital,p11,0']
        yield 'aec-gate-interrupt' if gate_irq else 'aec-external-overflow',image,{
            'ram':{'f780':'01'},'interrupt_entries':1},'\n'.join(rows)+'\n'

    p=Program();p.code += bytes.fromhex('0780018040fc')
    image=handler(p.finish(),7,'6a08f7800a086a88f7805670')
    yield 'nmi-masked-sleep',image,{'ram':{'f780':'02'},'interrupt_entries':2},'100,nmi,0\n300,nmi,1\n500,nmi,0\n'

    # Complete both clock transitions through SLEEP and the ordinary vector
    # 13 handler. Neither merely stopping instruction issue nor changing the
    # programmed SYSCR registers is enough to perform a direct transition.
    p=Program();p.code += bytes.fromhex('067f')
    p.byte(0xfff0,0xaf);p.byte(0xfff1,0xeb)
    p.code += bytes.fromhex('0180')
    p.byte(0xfff0,0xa7);p.byte(0xfff1,0xeb)
    p.code += bytes.fromhex('0180')
    p.byte(0xf781,0xa5)
    image=handler(p.finish(),13,'6a08f7800a086a88f7805670')
    yield 'direct-clock-transitions',image,{'ram':{'f780':'02a5'},'interrupt_entries':2},None

    p=Program() # reset CCR.I remains set
    p.byte(0xfff0,0xaf);p.byte(0xfff1,0xeb)
    p.code += bytes.fromhex('0180')
    p.byte(0xf781,0xa5)
    image=handler(p.finish(),13,'6a08f7800a086a88f7805670')
    yield 'direct-clock-masked',image,{'ram':{'f780':'0000'},'interrupt_entries':0},None

    # A store's NEXT fetch precedes its data write. The overwritten first word
    # must execute from the pipeline; the following extension remains live.
    p=Program()
    body=bytes.fromhex('7900f82a6b80f828f8116a88f80040fe')
    for offset in range(0,len(body),2):
        p.word(0xf820+offset,int.from_bytes(body[offset:offset+2],'big'))
    p.code += bytes.fromhex('5a00f820')
    yield 'prefetch-before-self-modifying-store',p.finish(),{'ram':{'f800':'11','f828':'f82a'}},None

    # JSR @aa:24 fetches the target before pushing the return PC. Here the
    # stack aliases that target, making the bus order visible in plain RAM.
    p=Program()
    body=bytes.fromhex('f8116a88f80040fe')
    for offset in range(0,len(body),2):
        p.word(0xf822+offset,int.from_bytes(body[offset:offset+2],'big'))
    p.code += bytes.fromhex('7907f8245e00f822')
    yield 'call-prefetch-before-stack-write',p.finish(),{'ram':{'f800':'11'}},None

    # The manual defines these flags and continued execution even when the
    # quotient/remainder bits are unspecified. Do not certify those bits.
    p=Program()
    divisions=[
        (False,False,0x1234,0,0xf7), (False,True,0x12345678,0,0xf7),
        (True,False,0xffff,0,0xff), (True,True,0xffffffff,0,0xff),
        (False,False,0xffff,1,0xf3), (False,True,0xffffffff,1,0xf3),
        (True,False,0x8000,0xff,0xf3), (True,True,0x80000000,0xffff,0xf3),
        (True,False,0xffff,2,0xfb), (True,True,0xffffffff,2,0xfb),
        (False,True,0x10000,0x8000,0xfb),
    ]
    for index,(signed,word,dividend,divisor,flags) in enumerate(divisions):
        p.code += bytes.fromhex('7a01')+dividend.to_bytes(4,'big')
        p.code += bytes.fromhex('7900')+divisor.to_bytes(2,'big')+bytes.fromhex('07f3')
        if signed:p.code += bytes.fromhex('01d0')
        p.code += bytes.fromhex('5301' if word else '5181')
        p.code += bytes.fromhex('020a6a8a')+(0xf800+index).to_bytes(2,'big')
    p.byte(0xf820,0xa5)
    yield 'division-flags-and-continuation',p.finish(),{'ram':{
        'f800':bytes(row[4] for row in divisions).hex(),'f820':'a5'}},None

    for name,enable in [('ssu-receive-single',0x60),('ssu-receive-overrun',0x40)]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf087,8),(0xf0e0,0x8c),(0xf0e1,0x40),
                    (0xf0e2,0xa6),(0xf0e3,enable)]:p.byte(a,v)
        p.code += bytes.fromhex('6a08f0e9') # dummy read starts receive-only clocks
        mask=2 if enable==0x60 else 0x40
        p.code += bytes.fromhex('6a08f0e4e8')+bytes([mask])+bytes.fromhex('47f8')
        p.byte(0xf0e3,0) # RE clear retains unread data and ORER
        p.code += bytes.fromhex('6a08f0e46a88f8006a08f0e96a88f8016a08f0e46a88f802')
        yield name,p.finish(),{'ram':{'f800':'06ff04' if enable==0x60 else '46ff44'}},None

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf087,8),(0xf0e0,0x8c),(0xf0e1,0x40),
                (0xf0e2,0x80),(0xf0e3,0xc0)]:p.byte(a,v)
    p.send(0x35) # complete first byte and consume SSRDR
    p.code += bytes.fromhex('6a08f0e4')
    p.byte(0xf0e4,8) # read-qualified TDRE clear repeats unchanged SSTDR
    p.code += bytes.fromhex('6a08f0e4e80247f8')
    p.byte(0xf0e3,0)
    p.byte(0xf0e1,0x60) # SRES keeps status/data registers
    p.code += bytes.fromhex('6a08f0e46a88f8006a08f0e96a88f8016a08f0eb6a88f802')
    yield 'ssu-repeat-and-sequencer-reset',p.finish(),{'ram':{'f800':'0eff35'}},None

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x80),
                (0xf0e3,0x80),(0xf0eb,0x11),(0xf0eb,0x22),(0xf0eb,0x33)]:p.byte(a,v)
    p.code += bytes.fromhex('6a08f0e4e80847f86a08f0e46a88f8006a08f0eb6a88f801')
    yield 'ssu-replace-queued-byte',p.finish(),{'ram':{'f800':'0c33'}},None

    # External edges, not completed bytes, enter the package. Test all four
    # SPI phases, the alternate package mux, and clocked-sync LSB-first.
    for suffix,mode,mux,four_line in [
        ('mode-0',0xe0,0,True),('mode-1',0xc0,0,True),
        ('mode-2',0xa0,0,True),('mode-3',0x80,0,True),
        ('alternate-pins',0xa0,0x10,True),('clocked-lsb',0,0,False),
    ]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xffec,1),(0xffdc,1),(0xf085,mux),
                    (0xf0e0,0x0d),(0xf0e1,0x40 if four_line else 0),
                    (0xf0e2,mode),(0xf0e3,0x40)]:p.byte(a,v)
        p.code += bytes.fromhex('6a08f0e4e80247f86a08f0e96a88f800')
        p.code += bytes(256) # allow the final half-clock and deselection
        p.code += bytes.fromhex('6a08f0e46a88f801')
        cs,clk,data=('p93','p92','p91') if mux else ('p90','p91','p92')
        idle=0 if mode&0x40 else 1
        rows=[f'0,digital,{cs},1',f'0,digital,{clk},{idle}',f'500,digital,{cs},0']
        for i in range(8):
            bit=(0x96 >> (7-i if mode&0x80 else i))&1
            rows += [f'{515+20*i},digital,{data},{bit}',
                     f'{520+20*i},digital,{clk},{1-idle}',f'{530+20*i},digital,{clk},{idle}']
        rows += [f'680,digital,{cs},1']
        # Clocked-sync inputs use SSI instead of the four-line slave's SSO.
        if not four_line:rows=[row.replace(',p92,',',p93,') for row in rows]
        yield 'ssu-slave-'+suffix,p.finish(),{'ram':{'f800':'9604'}},'\n'.join(rows)+'\n'

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x0d),(0xf0e1,0x40),(0xf0e2,0x80),
                (0xf0e3,0xc0),(0xf0eb,0x3c)]:p.byte(a,v)
    p.code += bytes.fromhex('6a08f0e4e80147f86a08f0e46a88f8006a08f0e96a88f801')
    rows=['0,digital,p90,1','0,digital,p91,1','500,digital,p90,0']
    for i in range(3):rows += [f'{520+20*i},digital,p91,0',f'{530+20*i},digital,p91,1']
    rows += ['580,digital,p90,1']
    yield 'ssu-slave-deselect-in-frame',p.finish(),{'ram':{'f800':'0500'}},'\n'.join(rows)+'\n'

    for suffix,high,mux,expected in [('normal',0x0d,0,'0e961d0a'),
                                   ('alternate',0x0d,0x10,'0e961d05'),
                                   ('bidirectional',0x4d,0,'0c005d06')]:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf085,mux),(0xf0e0,high),(0xf0e1,0x40),
                    (0xf0e2,0x80),(0xf0e3,0x80 if high&0x40 else 0xc0),
                    (0xf0eb,0x35)]:p.byte(a,v)
        p.code += bytes.fromhex('6a08f0e4e80847f86a08f0e46a88f8006a08f0e96a88f801')
        p.code += bytes.fromhex('6a08f0e06a88f8026a08ffdc6a88f803')
        cs,clk,data=('p93','p92','p91') if mux else ('p90','p91','p92')
        rows=[f'0,digital,{cs},1',f'0,digital,{clk},1',f'500,digital,{cs},0']
        for i in range(8):
            rows += [f'{515+20*i},digital,{data},{(0x96>>(7-i))&1}',
                     f'{520+20*i},digital,{clk},0',f'{530+20*i},digital,{clk},1']
        rows += [f'800,digital,{cs},1']
        yield 'ssu-slave-transmit-'+suffix,p.finish(),{'ram':{'f800':expected}},'\n'.join(rows)+'\n'

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8e),(0xf0e1,0x40),(0xf0e2,0x86),
                (0xf0e3,0x80),(0xf0eb,0x11)]:p.byte(a,v)
    p.code += bytes.fromhex('6a08f0e4e80147f86a08f0e46a88f8006a08f0e06a88f801')
    yield 'ssu-master-selection-conflict',p.finish(),{'ram':{'f800':'010e'}},'0,digital,p90,0\n'

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf087,4),(0xf0e0,0xcc),(0xf0e1,0x40),
                (0xf0e2,0xa6),(0xf0e3,0x60)]:p.byte(a,v)
    p.code += bytes.fromhex('6a08f0e96a08f0e4e80247f86a08f0e96a88f800')
    p.byte(0xf0e3,0)
    yield 'ssu-bidirectional-receive',p.finish(),{'ram':{'f800':'ff'}},None

    p=Program()
    for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e3,0x80)]:p.byte(a,v)
    # SOL reads the actual retained serial output, including the documented
    # SOLP 0->1 write-protection transition. Open-drain high releases the pin.
    for index,value in enumerate([0x94,0x8c,0x9c,0xb4]):
        p.byte(0xf0e0,value)
        p.code += bytes.fromhex('6a08f0e06a88')+(0xf800+2*index).to_bytes(2,'big')
        p.code += bytes.fromhex('6a08ffdc6a88')+(0xf801+2*index).to_bytes(2,'big')
    p.byte(0xf087,4)
    p.code += bytes.fromhex('6a08ffdc6a88f808')
    yield 'ssu-output-level-and-open-drain',p.finish(),{'ram':{'f800':'9c078c038c03bc0307'}},None

    for name in ['eeprom-wel-during-write','eeprom-overlong-status',
                 'eeprom-power-before-cs','eeprom-reset-during-write']:
        p=Program()
        for a,v in [(0xfffb,0x14),(0xf0e0,0x8c),(0xf0e1,0x40),(0xf0e2,0x86),
                    (0xf0e3,0xc0),(0xffe4,7),(0xffd4,5),(0xf087,8),
                    (0xffec,1),(0xffdc,1)]:p.byte(a,v)
        p.byte(0xffd4,1);p.send(6);p.byte(0xffd4,5)
        p.byte(0xffd4,1)
        command=[1,0x8c,0] if name=='eeprom-overlong-status' else [2,0,0x20,0xa5]
        for byte in command:p.send(byte)
        if name!='eeprom-power-before-cs':p.byte(0xffd4,5)
        timeline=None
        if name in ['eeprom-wel-during-write','eeprom-overlong-status']:
            p.byte(0xffd4,1);p.send(5);p.send(0)
            p.code += bytes.fromhex('6a88f800')
            p.byte(0xffd4,5)
            expected={'ram':{'f800':'03' if name=='eeprom-wel-during-write' else '02'},
                      'nv_commits':1 if name=='eeprom-wel-during-write' else 0}
        elif name=='eeprom-power-before-cs':
            timeline='1000,power,0\n'
            expected={'eeprom':{'0020':'ff'},'nv_commits':0}
        else:
            timeline='1000,reset,0\n'
            expected={'eeprom':{'0020':'a5'},'nv_commits':1}
        yield name,p.finish(),expected,timeline


def expectation_metadata(name: str) -> dict:
    if name.startswith('power-'):
        return {'kind':'software_reasoned','source':'REJ09B0152-0300 §§19.2,21.2; RAM retention Table21.2; original constant-rail circuit calculation',
                'question':'Do short and sustained rail collapses distinguish stopped execution, RC reset, and retained or lost volatile data?',
                'limitation':'Nominal unmeasured board realization: 100kOhm/100nF RES, 0.8VCC threshold, retention exposure 15000mV.ms below 1.5V. These are model-calibration expectations, not universal silicon measurements.',
                'physical_device':'power-interruption fixture; preserve user nonvolatile data separately'}
    if name.startswith('boot-'):
        return {'kind':'software_reasoned' if name.startswith('boot-invalid') else 'documented',
                'source':'REJ09B0152-0300 §6.3/Table6.2 and §6.4; TN-H8*-A414A/E target geometry',
                'question':'Does physical 2400-baud boot erase all six blocks when nonblank, accept an odd RAM payload and retain BRR/SCI/GPIO handoff state?',
                'physical_device':'Boot mode erases all nonblank flash; use only on an authorized sacrificial device.',
                'limitation':'No manufacturer-ROM instruction count or erase-retry timing is asserted. Invalid lengths echo and wait for reset in the selected bounded-loader inference.'}
    if name.startswith('flash-'):
        return {'kind':'software_reasoned' if name in ('flash-verify-early-latch','flash-module-wake') else 'documented',
                'source':'REJ09B0152-0300 §§6.2–6.7 and Table21.11; TN-H8*-A414A/E pp.3–4; H8/300H §2.8',
                'question':'Do RAM-executed control, pulse, verify, protection and target block operations preserve the flash contract?',
                'limitation':'Early reads retain the old verify latch; module standby initializes controller state and unavailable reads return FF in the selected circuit model. Retry count and partial cell thresholds are not asserted.',
                'physical_device':'destructive flash modification; explicit sacrificial-device authorization required'}
    if name.startswith('irq-') or name == 'exception-ccr-stack-word':
        return {'kind':'documented','source':'REJ09B0152-0300 §§3.7–3.8.4,10.4; H8/300H software manual §1.1; H8/3318 §2.3.2',
                'question':'Do exception stack contents, enable-clear admission, source-clear cancellation and pin-selection flag settling follow the target contract?',
                'limitation':'Timer match is seven phi states after start, strictly between BCLR operand read and write; CCR duplication follows the explicitly inherited H8/300 stack format.'}
    if name.startswith('iic-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §16.3–16.5; TN-MC*-A022A/E and A023A/E',
                'question':'Do byte-wide registers, shared-vector interrupt, physical address frames, read-qualified flags and STOP sequencing follow the IIC2 contract?',
                'limitation':'Clocked input gives ample filter/setup margin; no inferred subcycle race is asserted.'}
    if name.startswith('register-'):
        return {'kind':'software_reasoned','source':'REJ09B0152-0300 §§2.3.2,2.5–2.6,8.5.1,8.5.3; TN-H8*-A414A/E memory map',
                'question':'Do ordinary lane/alignment/wrap accesses complete without invented faults, and do comparator-enabled PB pins retain digital read access?',
                'limitation':'Word-only byte reads select a lane, byte writes do not qualify the word latch, and unassigned bus reads are zero in the chosen decoder model. The comparator/ADC mux rule is documented.'}
    if name.startswith('rtc-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§8.1.4,11.3–11.5; REJ06B0514 RCS=1xxx table',
                'question':'Do calendar updates preserve raw digit fields and a pending busy update, and does TMOW drive P10 independently of RUN?',
                'limitation':'Busy-write precedence and malformed digit carry are local counter/latch inferences; no exact initial busy phase is asserted.'}
    if name.startswith('timer-b1-'):
        return {'kind':'software_reasoned','source':'REJ09B0152-0300 §§9.2–9.4 TLB/TCB path and shared clock selection',
                'question':'Do live TLB/mode writes continue counting and preserve the reload/overflow relationship?',
                'limitation':'Writing TLB while counting is outside recommended programming; both connected latches accept the write in this selected circuit model.'}
    if name.startswith('adc-battery-'):
        return {'kind':'software_reasoned','source':'REJ09B0152-0300 Fig17.1/17.6; lumirth/pw BatterySample and BatteryCheckLow',
                'question':'Does P84 drive qualify battery sensing, with a supply-following AVCC and midpoint ADC quantization?',
                'limitation':'Selected nominal sense path has an effective 600 mV drop, not a measured board netlist. Pull-up alone does not enable it.'}
    if name.startswith('adc-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§17.3–17.4,17.7.3; Fig17.1 sample-and-hold circuit',
                'question':'Do all clock selectors complete, do PMRB/AMR/IEGR qualify physical triggers and vector38, and does an open mux retain its sampled charge?',
                'limitation':'Open-mux charge retention is a circuit inference; Full-scale input assumes AVCC at or below 3.3 V; no battery-network transfer is asserted.'}
    if name.startswith('oscillator-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§4.1.1,4.3.4,5.5; Table10.3',
                'question':'Does SUBSTP stop the crystal, can ROSC/32 clock Timer W with that crystal stopped, and is OSCF read-only?'}
    if name.startswith('watchdog-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §12.2; TN-H8*-A309B/E rev.2 (2005-10-04)',
                'question':'Do old-latch protection, actual MOV.B addressing/alignment, and OVF read qualification preserve each independent register field?',
                'limitation':'Alignment assertions use the absolute-8 MOV.B form shown in the erratum; other MOV.B forms follow ordinary write qualification.'}
    if name.startswith('sci-') or name.startswith('infrared-'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§8.2,14.3–14.8; TN-H8*-A333B/E corrected five-bit formats; lumirth/pw IrConfigure and IrStartSend for transceiver polarity',
                'question':'Do physical serial pins, corrected framing, status/data transfer, and transceiver shutdown obey their independent hardware contracts?',
                'limitation':'IR input pulses have generous timing margins; no analog receiver response or measured pulse phase is asserted.'}
    if name.startswith('decimal-'):
        return {'kind':'software_reasoned' if name=='decimal-arithmetic-carry' else 'documented',
                'source':'REJ09B0213-0300 pp.76-79 DAA/DAS tables; ordinary packed-BCD arithmetic for the twenty omitted carry states',
                'question':'Do byte results and defined CCR bits agree with every table row, independent incoming N/Z, and actual ADD/ADDX/SUB/SUBX/NEG sequences?',
                'limitation':'H/V are masked because the manufacturer gives no guaranteed value; carry-table extension is labeled separately.'}
    if name.startswith('sensor-i2c-'):
        return {'kind':'software_reasoned' if name=='sensor-i2c-sleep-wake-and-reset' else 'documented',
                'source':'Bosch BMA150 Rev1.6 §§3.3.3,3.3.6–7,4.1.1,4.2–4.2.1; H8/38602R §8.4',
                'question':'Do GPIO SDA/clock edges implement the fixed address, paired writes, incrementing reads, ACK protection, aborts and live CSB selection?',
                'limitation':'Sleep/wake bus ACK and retaining the final reset ACK are circuit inferences; no pad slew or exact sub-edge propagation is asserted.'}
    if name.startswith('sensor-between-conversion-'):
        return {'kind':'software_reasoned','source':'Bosch BMA150 Rev1.6 sections 3.1.3 and 8.1: second-order 1500-Hz analog stage before a 3-kHz ADC scan',
                'question':'Does a 50-us acceleration pulse between nominal X conversion apertures leave an observable decaying response, while zero input stays zero?',
                'limitation':'Uses nominal 3-ms startup and T/X/Y/Z phase. Qualitative analog response, not a measured Bosch damping or impulse amplitude.'}
    if name.startswith('sensor-'):
        return {'kind':'documented','source':'Bosch BMA150 Rev1.6 register map, §§3.2,3.5,4.1; Bosch bma150_calc_new_offset and set_range',
                'question':'Do serial transfers, qualification/status, defaults, temperature, and offset/range produce their specified observations?'}
    if name.startswith('lcd-'):
        return {'kind':'documented','source':'Novatek NT7508 V1.0 pp.15–17,29,34–41,44–46; lumirth/pw DisplayFill for plane order',
                'question':'Do serial LCD commands preserve physical RAM, map both planes before viewport cropping, and obey display/duty/reset priority?'}
    if name.startswith('eeprom-'):
        return {'kind':'documented','source':'ST M95512 DS4192 Rev24 §§5.1,6.3.2,6.4,6.6',
                'question':'Do WEL, exact WRSR length, chip-select acceptance, and the external reset domain follow the EEPROM protocol?'}
    if name == 'long-displacement-store':
        return {'kind':'documented','source':'REJ09B0213-0300 §2.2.35 p.127; GNU gas h8300/movlh.s and h8300.exp (8ea833b70679)',
                'question':'Does the assembler-emitted MOV.L displacement store execute with its high selector bit?'}
    if name.startswith('ssu'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§15.3–15.5; §8.4 and Appendix B.3 for the package mux',
                'question':'Do the serial pins, selection, shift/holding/receive registers, and qualified flags follow the SSU contract?'}
    if name.startswith('direct-clock'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§5.3.2,5.3.5',
                'question':'Does SLEEP enter each programmed clock mode and complete direct-transition exception handling?'}
    if name.startswith('prefetch') or name.startswith('call-prefetch'):
        return {'kind':'documented','source':'REJ09B0213-0300 §2.8 Table 2.10 pp.239–241',
                'question':'Does a real prefetched opcode survive a later write to its RAM address?'}
    if name.startswith('division'):
        return {'kind':'documented','source':'REJ09B0213-0300 §§2.2.26–2.2.27 pp.83–95',
                'question':'Do all division widths continue with documented operand-sign and zero-divisor flags?',
                'limitation':'Undefined zero-divisor/overflow destination bits are deliberately not asserted.'}
    if name.startswith('predecrement'):
        return {'kind':'documented','source':'ADE-602-053A MOV.B/W/L usage notes pp.121/123/125',
                'question':'Does predecrement precede sampling an aliased source field?'}
    if name == 'aec-live-pwm-and-reserved-fields':
        return {'kind':'software_reasoned','source':'REJ09B0152-0300 §§13.3–13.6',
                'question':'Do documented writable reserved fields read back, and do live PWM changes resume physical output after a disconnected source?',
                'limitation':'PWCK111 disconnects the clock and ECPWDR reads zero in the selected local model; these values are not guaranteed by the manual.'}
    if name.startswith('aec'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§13.3–13.5',
                'question':'Do actual package inputs produce the specified AEC count/gate interrupt?'}
    if name.startswith('timer-w'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§10.4.3,10.6',
                'question':'Does a rising capture record a stopped counter and request vector 35?'}
    if name.startswith('comparator'):
        return {'kind':'software_reasoned' if name=='comparator-live-external-gating' else 'documented','source':'REJ09B0152-0300 Table3.1, §§18.3–18.5; internal/external-reference comparator application notes',
                'question':'Does CMDR read arm comparison and permit a settled difference to wake via the separate COMP0/COMP1 vectors 21/22?',
                'limitation':'Large voltage/time margins avoid relying on provisional analog response delay.'}
    if name.startswith('nmi'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§3.4.1,3.5.1,5.2',
                'question':'Does each selected NMI edge wake despite I=1, without retriggering a held level?'}
    return {'kind':'software_reasoned','source':'Original diagnostic; see README.md',
            'question':'Check the named CPU/protocol mechanism against its literal expected result.'}


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output',type=Path)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'blank-eeprom.bin').write_bytes(bytes([255])*65536)
    manifest={'schema':2,'target':'H8/38606F','basis':'Documented and software-reasoned expectations; no physical captures',
              'eeprom':{'file':'blank-eeprom.bin','sha256':hashlib.sha256(bytes([255])*65536).hexdigest()},'cases':[]}
    for name,image,expected,timeline in cases():
        (args.output/f'{name}.bin').write_bytes(image)
        if timeline: (args.output/f'{name}.csv').write_text(timeline)
        manifest['cases'].append({'name':name,'firmware':f'{name}.bin','sha256':hashlib.sha256(image).hexdigest(),
                                  'milliseconds':2200 if name.startswith('boot-') else 50 if name.startswith('power-') else 1100 if name.startswith('rtc-calendar') else 1000 if name.startswith('flash-erase') else 400 if name=='flash-program-retry' else 23 if name.startswith('sensor-autowake') else 20 if name.startswith('decimal-') else 8,'expected':expected,'input':f'{name}.csv' if timeline else None,
                                  'input_sha256':hashlib.sha256(timeline.encode()).hexdigest() if timeline else None,
                                  'expectation':expectation_metadata(name)})
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Built {len(manifest["cases"])} independent diagnostic images in {args.output}')
if __name__=='__main__': main()
