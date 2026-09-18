"""H8 decimal adjustment: primary-source rows and ordinary BCD arithmetic.

REJ09B0213-0300 pp.76/78. Each row is C, high-min/max, H, low-min/max,
byte to add, resulting C. Ranges are inclusive hexadecimal nibbles.
The fixture does not import or recreate an emulator's correction predicates.
"""

DAA = [
    (0,0x0,0x9,0,0x0,0x9,0x00,0),
    (0,0x0,0x8,0,0xa,0xf,0x06,0),
    (0,0x0,0x9,1,0x0,0x3,0x06,0),
    (0,0xa,0xf,0,0x0,0x9,0x60,1),
    (0,0x9,0xf,0,0xa,0xf,0x66,1),
    (0,0xa,0xf,1,0x0,0x3,0x66,1),
    (1,0x1,0x2,0,0x0,0x9,0x60,1),
    (1,0x1,0x2,0,0xa,0xf,0x66,1),
    (1,0x1,0x3,1,0x0,0x3,0x66,1),
]
DAS = [
    (0,0x0,0x9,0,0x0,0x9,0x00,0),
    (0,0x0,0x8,1,0x6,0xf,0xfa,0),
    (1,0x7,0xf,0,0x0,0x9,0xa0,1),
    (1,0x6,0xf,1,0x6,0xf,0x9a,1),
]


def capture(p, expected, value, carry):
    address=0xf800+len(expected)
    # STC precedes every flag-changing store. H and V have no promised values.
    p.code += bytes.fromhex('0209e9dd')
    p.code += bytes((0x6a,0x88,address>>8,address&255,
                     0x6a,0x89,(address+1)>>8,(address+1)&255))
    expected.extend((value,0xd0|carry|(4 if value==0 else 8 if value&0x80 else 0)))
    assert len(expected)<=0x770


def rows(p, expected, opcode, table):
    for carry,high_min,high_max,half,low_min,low_max,add,result_carry in table:
        for high in range(high_min,high_max+1):
            for low in range(low_min,low_max+1):
                value=(high<<4)|low
                # N/Z initially clear and set: neither selects add/subtract,
                # and both must be recomputed. I/UI/U stay set; V is ignored.
                for incoming in [0xd2,0xde]:
                    p.code += bytes((0xf8,value,0x07,incoming|(half<<5)|carry,opcode,0x08))
                    capture(p,expected,(value+add)&255,result_carry)


def cases(program):
    for name,opcode,table in [('daa',0x0f,DAA),('das',0x1f,DAS)]:
        p=program(); expected=bytearray()
        rows(p,expected,opcode,table)
        yield 'decimal-'+name+'-table',p.finish(),{'ram':{'f800':expected.hex()}},None

    p=program(); expected=bytearray()
    # The printed DAA rows exclude upper nibble zero when C=1, although these
    # twenty states arise from valid BCD additions. Decimal arithmetic supplies
    # the extension; don't mislabel it as part of the printed table.
    rows(p,expected,0x0f,[(1,0,0,0,0,9,0x60,1),
                         (1,0,0,0,0xa,0xf,0x66,1),
                         (1,0,0,1,0,3,0x66,1)])
    # Original arithmetic sequences independently exercise the incoming flags.
    # (instruction bytes, adjusted byte, decimal carry/borrow)
    for instructions,value,carry in [
        ('f890f97007d008980f08',0x60,1), # 90+70=160
        ('f885f98507d008980f08',0x70,1), # 85+85=170
        ('f878f98807d008980f08',0x66,1), # 78+88=166 (half carry)
        ('f899f90107d008980f08',0x00,1), # 99+1=100
        ('f809f90907d10e980f08',0x19,0), # 9+9+carry=19
        ('f899f90007d10e980f08',0x00,1), # 99+0+carry=100
        ('f800f90107d018981f08',0x99,1), # 0-1=-1
        ('f810f90107d018981f08',0x09,0), # 10-1=9
        ('f810f90907d11e981f08',0x00,0), # 10-9-borrow=0
        ('f800f90007d11e981f08',0x99,1), # 0-0-borrow=-1
        ('f80107d017881f08',0x99,1),     # -1
        ('f89907d017881f08',0x01,1),     # -99
        ('f80007d017881f08',0x00,0),     # -0
    ]:
        p.code += bytes.fromhex(instructions)
        capture(p,expected,value,carry)
    yield 'decimal-arithmetic-carry',p.finish(),{'ram':{'f800':expected.hex()}},None
