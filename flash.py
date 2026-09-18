"""Original RAM-resident flash diagnostics, from Renesas section 6 and A414A/E.

No emulator code or cell-distribution parameters supply expected observations.
"""
from __future__ import annotations

class Body:
    def __init__(self):
        self.code=bytearray()
        self.labels={}
        self.jumps=[]
    def emit(self,hex_bytes): self.code += bytes.fromhex(hex_bytes)
    def word(self,value): self.code += value.to_bytes(2,'big')
    def write(self,address,value):
        self.code += bytes((0xf8,value,0x6a,0x88,address>>8,address&255))
    def delay(self,count):
        self.emit('7902');self.word(count);self.emit('1b5246fc')
    def read(self,address,result):
        self.emit('6a08');self.word(address);self.emit('6a88');self.word(result)
    def mark(self,name): self.labels[name]=0xf980+len(self.code)
    def jump(self,name):
        self.emit('5a00');self.jumps.append((len(self.code),name));self.word(0)
    def copy(self,source,dest,length):
        self.emit('7905');self.word(source)
        self.emit('7906');self.word(dest)
        self.emit('7904');self.word(length);self.emit('7bd4598f')
    def setup(self):
        self.write(0xf02b,0x80);self.write(0xf020,0x40);self.delay(1)
    def finish(self, patches=()):
        self.emit('40fe')
        for at,name in self.jumps:self.code[at:at+2]=self.labels[name].to_bytes(2,'big')
        if len(self.code)>0x580:raise ValueError('flash diagnostic exceeds RAM body window')
        # All later instruction fetches, delay loops and result stores stay in RAM.
        loader=Body();loader.emit('7907ff70');loader.copy(0x400,0xf980,len(self.code))
        loader.emit('5a00f980')
        image=bytearray(49152);image[:2]=bytes.fromhex('0100')
        image[0x100:0x100+len(loader.code)]=loader.code
        image[0x400:0x400+len(self.code)]=self.code
        for address,data in patches:image[address:address+len(data)]=data
        return bytes(image)

def cases():
    b=Body();result=0xf900
    def read(a):
        nonlocal result
        b.read(a,result);result+=1
    read(0xf02b);b.write(0xf022,255);b.write(0xf02b,255);read(0xf02b)
    for a in range(0xf020,0xf024):read(a)
    b.write(0xf020,0xbf);read(0xf020);b.write(0xf021,255);read(0xf021)
    b.write(0xf022,255);read(0xf022);b.write(0xf020,0xc0);read(0xf020)
    for value in [0x20,0x40,0x80,0x21]:b.write(0xf023,value);read(0xf023)
    b.write(0xf023,0x20);b.write(0xf02b,0)
    for a in [0xf020,0xf023,0xf022]:b.write(a,0)
    b.write(0xf02b,0x80)
    for a in [0xf020,0xf023,0xf022]:read(a)
    b.write(0xf020,0);read(0xf020);read(0xf023)
    yield 'flash-register-contract',b.finish(),{'ram':{'f900':'00800000000000008040204080004020800000'}},None

    values=bytes.fromhex('123456789abcdef0')
    for early in [False,True]:
        b=Body();b.setup();b.write(0xf020,0x44);b.delay(2)
        b.write(0x9000,255);b.delay(1)
        b.emit('01006b00900001006b80f900')
        if early:
            b.emit('79019004f8ff6898691269136b82f9046b83f906')
            expected='1234567812349abc'
        else:
            b.write(0x9004,255);b.delay(1);b.emit('01006b00900401006b80f904')
            expected='123456789abcdef0'
        b.write(0xf020,0x40);b.delay(1);b.write(0xf020,0);b.delay(61)
        b.copy(0x9000,0xf910,8)
        yield 'flash-verify-'+('early-latch' if early else 'settled'),b.finish([(0x9000,values)]),{'ram':{'f900':expected,'f910':values.hex()}},None

    for address in [0x9000,0x8000]:
        b=Body();b.setup();b.write(0xf023,0x20)
        b.write(0xf020,0x50);b.delay(31);b.write(0xf020,0x51)
        b.emit('6a08');b.word(address)
        for i,a in enumerate([0xf021,0xf020,0xf023]):b.read(a,0xf900+i)
        b.write(0xf021,0);b.write(0xf020,0x50);b.delay(3)
        b.write(0xf020,0x40);b.delay(3);b.read(0xf021,0xf903)
        b.write(0xf020,0x44);b.delay(2);b.write(0x9000,255);b.delay(1)
        b.emit('01006b00900001006b80f904');b.write(0xf908,0xa5)
        yield 'flash-protection-'+('selected' if address==0x9000 else 'other-block'),b.finish([(0x9000,bytes([255])*128)]),{'ram':{'f900':'80512080ffffffffa5'}},None

    b=Body();b.setup();b.write(0xf022,0x80);b.write(0xf023,0x20)
    b.emit('79019000');b.write(0xfffa,1);b.write(0xfffa,3);b.emit('681b')
    b.delay(12);b.emit('681c6a8bf9006a8cf901')
    for i,a in enumerate([0xf020,0xf021,0xf023,0xf02b,0xf022]):b.read(a,0xf902+i)
    yield 'flash-module-wake',b.finish([(0x9000,bytes([0xd3]))]),{'ram':{'f900':'ffd30000008080'}},None

    # The retry mask follows table 6.4: wanted | ~verified. Attempt count is
    # bounded but never asserted; a physical part need not match a model's speed.
    wanted=bytes(i^0xa5 for i in range(128))
    b=Body();b.copy(0xa00,0xf780,128);b.copy(0xa00,0xf800,128);b.setup()
    b.emit('790303e8');b.mark('retry');b.copy(0xf800,0x9000,128)
    b.write(0xf020,0x50);b.delay(31)
    b.emit('792303e34504');b.jump('short-pulse')
    b.write(0xf020,0x51);b.delay(121);b.write(0xf020,0x50);b.jump('pulse-recovery')
    b.mark('short-pulse');b.write(0xf020,0x51);b.delay(16);b.write(0xf020,0x50)
    b.mark('pulse-recovery');b.delay(3);b.write(0xf020,0x40);b.delay(3)
    b.write(0xf020,0x44);b.delay(2)
    b.emit('790190007905f7807906f8007907f88079040020');b.mark('verify')
    b.emit('f8ff6898');b.delay(1)
    b.emit('01006910010069521fa047027073') # Long sense, wanted, compare, mark failure.
    # Strengthening = previous retry | verified; R7 traverses RAM, with I=1
    # and NMI high throughout this call-free body.
    b.emit('0100696201f06402010069f20b9701006d52')
    # NOT.L ER0; OR.L ER2,ER0; MOV.L ER0,@ER6; ADDS #4,ER6.
    b.emit('173001f06420010069e00b96')
    b.emit('0b911b544704');b.jump('verify') # ADD.L #4,ER1; DEC.W R4; loop.
    b.write(0xf020,0x40);b.delay(1)
    b.emit('0d3079607fff792003e34404');b.jump('strengthened')
    b.copy(0xf880,0x9000,128)
    b.write(0xf020,0x50);b.delay(31);b.write(0xf020,0x51);b.delay(4)
    b.write(0xf020,0x50);b.delay(3);b.write(0xf020,0x40);b.delay(3)
    b.mark('strengthened')
    b.emit('73734604');b.jump('done')
    b.emit('72731b534704');b.jump('retry')
    b.write(0xf900,0xee);b.jump('halt')
    b.mark('done');b.write(0xf020,0);b.delay(61);b.copy(0x9000,0xf800,128)
    b.write(0xf900,0xa5);b.read(0xf021,0xf901);b.read(0x8fff,0xf902);b.read(0x9080,0xf903)
    b.mark('halt')
    yield 'flash-program-retry',b.finish([(0xa00,wanted),(0x8f80,bytes([255])*384)]),{'ram':{'f800':wanted.hex(),'f900':'a500ffff'}},None

    for select,start,end,expected in [(0x10,0x1000,0x8000,'00ffffffff0000'),(0x20,0x8000,0xc000,'0000000000ffff')]:
        b=Body();b.setup();b.write(0xf023,select);b.emit('79030064');b.mark('retry')
        b.write(0xf020,0x60);b.delay(61);b.write(0xf020,0x62);b.delay(6142)
        b.write(0xf020,0x60);b.delay(6);b.write(0xf020,0x40);b.delay(6)
        b.write(0xf020,0x48);b.delay(12)
        b.emit('7901');b.word(start);b.emit('7904');b.word((end-start)//4);b.mark('verify')
        b.emit('f8ff6898');b.delay(1)
        b.emit('010069107a20ffffffff47067073');b.jump('verify-end')
        b.emit('0b911b544704');b.jump('verify');b.mark('verify-end')
        b.write(0xf020,0x40);b.delay(2)
        b.emit('73734604');b.jump('done')
        b.emit('72731b534704');b.jump('retry')
        b.write(0xf900,0xee);b.jump('halt')
        b.mark('done');b.write(0xf020,0);b.delay(61);b.write(0xf900,0xa5)
        for i,a in enumerate([0xfff,0x1000,0x3fff,0x4000,0x7fff,0x8000,0xbfff]):b.read(a,0xf901+i)
        b.mark('halt')
        yield f'flash-erase-eb{4 if select==16 else 5}',b.finish(),{'ram':{'f900':'a5'+expected}},None
