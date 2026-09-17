#!/usr/bin/env python3
"""Build small, original H8 diagnostic images without a cross compiler.

This is a fixture encoder, not an assembler or reference emulator. Expectations
are literal, independently reasoned values. No production Rust is imported.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

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
    for a,v in [(0xfffa,0x43),(0xff91,0xd0),(0xff99,1),(0xffa7,0x80),(0xff9a,0x20),(0xff9b,0xa5)]:
        p.byte(a,v)
    yield 'infrared-transmit', p.finish(), {'ir_events':10}, None
    p = Program()
    for a,v in [(0xfffa,0x43),(0xff91,0xd0),(0xff99,1),(0xffa7,0x80),(0xff9a,0x10)]: p.byte(a,v)
    p.code += bytes.fromhex('6a08ff9ce84047f86a08ff9d6a88f800')
    bits = [0] + [(0xa5 >> i) & 1 for i in range(8)] + [1]
    rows = ['# Nominal SIR pulses; digital software fixture, not a hardware capture.']
    for i,one in enumerate(bits):
        if not one:
            at = 500 + round(i*64*1_000_000/3_686_400)
            rows.extend([f'{at},ir,1',f'{at+3},ir,0'])
    yield 'infrared-receive', p.finish(), {'ram':{'f800':'a5'}}, '\n'.join(rows)+'\n'

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
    image=handler(p.finish(),36,'f8016a88f7806a08f0def8006a88f0de5670')
    timeline='0,analog,pb4,1000\n200,analog,pb4,2100\n'
    yield 'comparator-read-armed-wake',image,{'ram':{'f780':'01'},'interrupt_entries':1},timeline

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
    if name.startswith('aec'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§13.3–13.5',
                'question':'Do actual package inputs produce the specified AEC count/gate interrupt?'}
    if name.startswith('timer-w'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§10.4.3,10.6',
                'question':'Does a rising capture record a stopped counter and request vector 35?'}
    if name.startswith('comparator'):
        return {'kind':'documented','source':'REJ09B0152-0300 §§18.3–18.4',
                'question':'Does CMDR read arm comparison and permit a settled difference to wake via vector 36?',
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
                                  'milliseconds':8,'expected':expected,'input':f'{name}.csv' if timeline else None,
                                  'input_sha256':hashlib.sha256(timeline.encode()).hexdigest() if timeline else None,
                                  'expectation':expectation_metadata(name)})
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Built {len(manifest["cases"])} independent diagnostic images in {args.output}')
if __name__=='__main__': main()
