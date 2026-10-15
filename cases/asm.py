"""Two-pass assembler for H8/300H normal-mode guest programs.

The syntax follows GNU as for H8: sized mnemonics (``mov.w``), ``#`` immediates,
``@er1``, ``@(4,er1)``, ``@er1+``, ``@-er1``, ``@aa:8``/``:16``/``:24`` and
``@@aa:8``. Absolute operands without a size use ``:16``; branches use ``d:8``
unless the target carries ``:16``. Labels end with ``:``; numeric labels can be
referenced as ``1b`` or ``1f``. Directives: ``.org``, ``.byte``, ``.word``,
``.long``, ``.space``, ``.align``, ``.equ`` (or ``name = expr``) and ``.vector``.
Comments start with ``;``.

Encodings follow REJ09B0213-0300 Table 2.3 and were checked against GNU as 2.43.
"""

from __future__ import annotations

import ast
import re

ROM_SIZE = 0xC000

R8 = {f"r{i}h": i for i in range(8)} | {f"r{i}l": i + 8 for i in range(8)}
R16 = {f"r{i}": i for i in range(8)} | {f"e{i}": i + 8 for i in range(8)}
R32 = {f"er{i}": i for i in range(8)} | {"sp": 7}

CONDITIONS = {
    "ra": 0, "bt": 0, "rn": 1, "bf": 1, "hi": 2, "ls": 3, "cc": 4, "hs": 4,
    "cs": 5, "lo": 5, "ne": 6, "eq": 7, "vc": 8, "vs": 9, "pl": 10, "mi": 11,
    "ge": 12, "lt": 13, "gt": 14, "le": 15,
}
SHIFTS = {
    "shll": (0x10, 0), "shal": (0x10, 8), "shlr": (0x11, 0), "shar": (0x11, 8),
    "rotxl": (0x12, 0), "rotl": (0x12, 8), "rotxr": (0x13, 0), "rotr": (0x13, 8),
}
# (register form opcode, @ERd prefix, @aa:8 prefix, immediate-only, inverting bit).
BITS = {
    "bset": (0x70, 0x60, 0x7D, 0x7F), "bnot": (0x71, 0x61, 0x7D, 0x7F),
    "bclr": (0x72, 0x62, 0x7D, 0x7F), "btst": (0x73, 0x63, 0x7C, 0x7E),
}
BIT_LOGIC = {
    "bor": (0x74, 0, 0x7C, 0x7E), "bior": (0x74, 1, 0x7C, 0x7E),
    "bxor": (0x75, 0, 0x7C, 0x7E), "bixor": (0x75, 1, 0x7C, 0x7E),
    "band": (0x76, 0, 0x7C, 0x7E), "biand": (0x76, 1, 0x7C, 0x7E),
    "bld": (0x77, 0, 0x7C, 0x7E), "bild": (0x77, 1, 0x7C, 0x7E),
    "bst": (0x67, 0, 0x7D, 0x7F), "bist": (0x67, 1, 0x7D, 0x7F),
}


class AsmError(ValueError):
    pass


def evaluate(text: str, symbols: dict, strict: bool) -> int:
    text = text.strip()
    text = re.sub(r"\b0b([01]+)\b", lambda m: str(int(m.group(1), 2)), text)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as error:
        raise AsmError(f"bad expression {text!r}") from error

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            if node.id in symbols:
                return symbols[node.id]
            if strict:
                raise AsmError(f"undefined symbol {node.id}")
            return 0
        if isinstance(node, ast.UnaryOp):
            value = walk(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.Invert):
                return ~value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            a, b = walk(node.left), walk(node.right)
            ops = {
                ast.Add: lambda: a + b, ast.Sub: lambda: a - b,
                ast.Mult: lambda: a * b, ast.FloorDiv: lambda: a // b,
                ast.Div: lambda: a // b, ast.Mod: lambda: a % b,
                ast.LShift: lambda: a << b, ast.RShift: lambda: a >> b,
                ast.BitAnd: lambda: a & b, ast.BitOr: lambda: a | b,
                ast.BitXor: lambda: a ^ b,
            }
            for kind, function in ops.items():
                if isinstance(node.op, kind):
                    return function()
        raise AsmError(f"unsupported expression {text!r}")

    return walk(tree)


def split_operands(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


class Operand:
    """Parsed operand: kind is reg8/reg16/reg32/imm/ind/disp/postinc/predec/abs/mem/ccr."""

    def __init__(self, kind, reg=None, expr=None, size=None):
        self.kind, self.reg, self.expr, self.size = kind, reg, expr, size


def parse_operand(text: str) -> Operand:
    t = text.strip()
    low = t.lower()
    if low == "ccr":
        return Operand("ccr")
    if low in R8:
        return Operand("reg8", R8[low])
    if low in R16:
        return Operand("reg16", R16[low])
    if low in R32:
        return Operand("reg32", R32[low])
    if t.startswith("#"):
        return Operand("imm", expr=t[1:])
    if t.startswith("@@"):
        expr, size = t[2:], 8
        if expr.endswith(":8"):
            expr = expr[:-2]
        return Operand("mem", expr=expr, size=size)
    if t.startswith("@"):
        body = t[1:].strip()
        lb = body.lower()
        if lb in R32:
            return Operand("ind", R32[lb])
        if lb.endswith("+") and lb[:-1] in R32:
            return Operand("postinc", R32[lb[:-1]])
        if lb.startswith("-") and lb[1:] in R32:
            return Operand("predec", R32[lb[1:]])
        if body.startswith("(") and body.endswith(")"):
            inner = split_operands(body[1:-1])
            if len(inner) != 2 or inner[1].lower() not in R32:
                raise AsmError(f"bad displacement operand {t!r}")
            expr, size = inner[0], None
            m = re.fullmatch(r"(.*):(16|24)", expr.strip())
            if m:
                expr, size = m.group(1), int(m.group(2))
            return Operand("disp", R32[inner[1].lower()], expr, size)
        m = re.fullmatch(r"(.*):(8|16|24)", body)
        if m:
            return Operand("abs", expr=m.group(1), size=int(m.group(2)))
        return Operand("abs", expr=body, size=None)
    m = re.fullmatch(r"(.*):(8|16)", t)
    if m:
        return Operand("label", expr=m.group(1), size=int(m.group(2)))
    return Operand("label", expr=t, size=None)


class Assembler:
    def __init__(self, symbols: dict | None = None):
        self.base_symbols = dict(symbols or {})

    def emit(self, image, pc, data):
        if pc < 0 or pc + len(data) > ROM_SIZE:
            raise AsmError(f"code outside ROM at {pc:#x}")
        if self.final and any(self.written[pc:pc + len(data)]):
            raise AsmError(f"overlapping output at {pc:#x}")
        image[pc:pc + len(data)] = data
        self.written[pc:pc + len(data)] = b"\x01" * len(data)

    def value(self, expr: str) -> int:
        expr = expr.strip()
        m = re.fullmatch(r"(\d+)([bf])", expr)
        if m:
            return self.numeric_ref(m.group(1), m.group(2))
        return evaluate(expr, self.symbols, self.final)

    def numeric_ref(self, name, direction):
        if direction == "b":
            for label, address in reversed(self.numeric):
                if label == name:
                    return address
            raise AsmError(f"no previous label {name}")
        # Forward references resolve from the previous pass's full list.
        future = getattr(self, "_numeric_all", [])
        for label, address, idx in future:
            if label == name and idx >= self.index and address >= self.pc:
                return address
        if self.final:
            raise AsmError(f"no following label {name}")
        return self.pc

    def directive(self, name, operands, image, pc):
        if name == ".org":
            return self.value(operands[0])
        if name in (".byte", ".word", ".long"):
            width = {".byte": 1, ".word": 2, ".long": 4}[name]
            data = bytearray()
            for operand in operands:
                data += (self.value(operand) & ((1 << (8 * width)) - 1)).to_bytes(width, "big")
            self.emit(image, pc, data)
            return pc + len(data)
        if name == ".space":
            count = self.value(operands[0])
            fill = self.value(operands[1]) if len(operands) > 1 else 0
            self.emit(image, pc, bytes([fill]) * count)
            return pc + count
        if name == ".align":
            step = self.value(operands[0])
            pad = (-pc) % step
            if pad:
                self.emit(image, pc, bytes(pad))
            return pc + pad
        if name == ".equ":
            self.symbols[operands[0]] = self.value(operands[1])
            return pc
        if name == ".vector":
            number, target = self.value(operands[0]), self.value(operands[1])
            if self.final and any(self.written[2 * number:2 * number + 2]):
                raise AsmError(f"vector {number} assigned twice")
            image[2 * number:2 * number + 2] = (target & 0xFFFF).to_bytes(2, "big")
            self.written[2 * number:2 * number + 2] = b"\x01\x01"
            return pc
        raise AsmError(f"unknown directive {name}")

    # Instruction encoding -------------------------------------------------

    def imm(self, operand, bits, signed_ok=True):
        value = self.value(operand.expr)
        limit = 1 << bits
        if self.final and not (-(limit >> 1) <= value < limit):
            raise AsmError(f"immediate {value} does not fit {bits} bits")
        return value & (limit - 1)

    def abs_size(self, operand, default=16):
        return operand.size or default

    def branch(self, operand, width):
        target = self.value(operand.expr)
        size = operand.size or 8
        length = width if size == 8 else width + 2
        displacement = target - (self.pc + length)
        if size == 8:
            if self.final and not -128 <= displacement <= 127:
                raise AsmError(f"branch target out of d:8 range ({displacement})")
            return size, displacement & 0xFF
        if self.final and not -32768 <= displacement <= 32767:
            raise AsmError("branch target out of d:16 range")
        return size, displacement & 0xFFFF

    def encode(self, mnemonic, ops):
        base, _, suffix = mnemonic.partition(".")
        kinds = tuple(o.kind for o in ops)
        if base == "mov":
            return self.mov(suffix, ops)
        if base in ("push", "pop"):
            if suffix == "w" or (not suffix and kinds == ("reg16",)):
                return bytes((0x6D, (0xF0 if base == "push" else 0x70) | ops[0].reg))
            return bytes((0x01, 0x00, 0x6D, (0xF0 if base == "push" else 0x70) | ops[0].reg))
        if base in ("add", "sub", "cmp"):
            return self.addsub(base, suffix, ops)
        if base in ("addx", "subx"):
            if kinds == ("imm", "reg8"):
                return bytes(((0x90 if base == "addx" else 0xB0) | ops[1].reg, self.imm(ops[0], 8)))
            return bytes((0x0E if base == "addx" else 0x1E, ops[0].reg << 4 | ops[1].reg))
        if base in ("adds", "subs"):
            amount = self.value(ops[0].expr)
            code = {1: 0x00, 2: 0x80, 4: 0x90}[amount]
            return bytes((0x0B if base == "adds" else 0x1B, code | ops[1].reg))
        if base in ("inc", "dec"):
            first = 0x0A if base == "inc" else 0x1A
            second = 0x0B if base == "inc" else 0x1B
            if suffix == "b":
                return bytes((first, ops[-1].reg))
            amount = self.value(ops[0].expr) if len(ops) == 2 else 1
            if suffix == "w":
                return bytes((second, (0x50 if amount == 1 else 0xD0) | ops[-1].reg))
            return bytes((second, (0x70 if amount == 1 else 0xF0) | ops[-1].reg))
        if base in ("and", "or", "xor"):
            return self.logic(base, suffix, ops)
        if base in ("neg", "not", "extu", "exts"):
            table = {
                ("not", "b"): 0x00, ("not", "w"): 0x10, ("not", "l"): 0x30,
                ("extu", "w"): 0x50, ("extu", "l"): 0x70, ("neg", "b"): 0x80,
                ("neg", "w"): 0x90, ("neg", "l"): 0xB0, ("exts", "w"): 0xD0,
                ("exts", "l"): 0xF0,
            }
            return bytes((0x17, table[(base, suffix)] | ops[0].reg))
        if base in SHIFTS:
            opcode, extra = SHIFTS[base]
            size = {"b": 0, "w": 1, "l": 3}[suffix]
            return bytes((opcode, (extra + size) << 4 | ops[0].reg))
        if base in ("daa", "das"):
            return bytes((0x0F if base == "daa" else 0x1F, ops[0].reg))
        if base in ("mulxu", "divxu", "mulxs", "divxs"):
            opcode = {"mulxu": 0x50, "divxu": 0x51}.get(base, 0x50 if base == "mulxs" else 0x51)
            if suffix == "w":
                opcode += 2
            body = bytes((opcode, ops[0].reg << 4 | ops[1].reg))
            if base == "mulxs":
                return b"\x01\xC0" + body
            if base == "divxs":
                return b"\x01\xD0" + body
            return body
        if base in BITS:
            return self.bitop(base, ops)
        if base in BIT_LOGIC:
            opcode, invert, ind, absolute = BIT_LOGIC[base]
            number = self.imm(ops[0], 3) | (invert << 3)
            target = ops[1]
            if target.kind == "reg8":
                return bytes((opcode, number << 4 | target.reg))
            if target.kind == "ind":
                return bytes((ind, target.reg << 4, opcode, number << 4))
            return bytes((absolute, self.value(target.expr) & 0xFF, opcode, number << 4))
        if base.startswith("b") and base[1:] in CONDITIONS and base != "bsr":
            size, displacement = self.branch(ops[0], 2)
            condition = CONDITIONS[base[1:]]
            if size == 8:
                return bytes((0x40 | condition, displacement))
            return bytes((0x58, condition << 4)) + displacement.to_bytes(2, "big")
        if base == "bsr":
            size, displacement = self.branch(ops[0], 2)
            if size == 8:
                return bytes((0x55, displacement))
            return b"\x5C\x00" + displacement.to_bytes(2, "big")
        if base in ("jmp", "jsr"):
            offset = 0 if base == "jmp" else 4
            target = ops[0]
            if target.kind == "ind":
                return bytes((0x59 + offset, target.reg << 4))
            if target.kind == "mem":
                return bytes((0x5B + offset, self.value(target.expr) & 0xFF))
            address = self.value(target.expr) & 0xFFFFFF
            return bytes((0x5A + offset,)) + address.to_bytes(3, "big")
        if base == "rts":
            return b"\x54\x70"
        if base == "rte":
            return b"\x56\x70"
        if base == "sleep":
            return b"\x01\x80"
        if base == "nop":
            return b"\x00\x00"
        if base == "trapa":
            return bytes((0x57, self.imm(ops[0], 2) << 4))
        if base in ("andc", "orc", "xorc"):
            return bytes(({"andc": 6, "orc": 4, "xorc": 5}[base], self.imm(ops[0], 8)))
        if base == "ldc":
            return self.ldc(ops[0])
        if base == "stc":
            return self.stc(ops[1])
        if base == "eepmov":
            return b"\x7B\x5C\x59\x8F" if suffix == "b" else b"\x7B\xD4\x59\x8F"
        raise AsmError(f"unknown instruction {mnemonic}")

    def mov(self, suffix, ops):
        src, dst = ops
        if suffix == "b":
            if src.kind == "imm":
                return bytes((0xF0 | dst.reg, self.imm(src, 8)))
            if src.kind == "reg8" and dst.kind == "reg8":
                return bytes((0x0C, src.reg << 4 | dst.reg))
            return self.mov_memory(0, src, dst)
        if suffix == "w":
            if src.kind == "imm":
                return bytes((0x79, dst.reg)) + self.imm(src, 16).to_bytes(2, "big")
            if src.kind == "reg16" and dst.kind == "reg16":
                return bytes((0x0D, src.reg << 4 | dst.reg))
            return self.mov_memory(1, src, dst)
        if suffix == "l":
            if src.kind == "imm":
                return bytes((0x7A, dst.reg)) + self.imm(src, 32).to_bytes(4, "big")
            if src.kind == "reg32" and dst.kind == "reg32":
                return bytes((0x0F, 0x80 | src.reg << 4 | dst.reg))
            return b"\x01\x00" + self.mov_memory(1, src, dst, long=True)
        raise AsmError("mov needs .b, .w or .l")

    def mov_memory(self, word, src, dst, long=False):
        store = dst.kind not in ("reg8", "reg16", "reg32")
        mem, reg = (dst, src.reg) if store else (src, dst.reg)
        s = 0x80 if store else 0
        if mem.kind == "ind":
            return bytes((0x68 + word, s | mem.reg << 4 | reg))
        if mem.kind in ("postinc", "predec"):
            if (mem.kind == "predec") != store:
                raise AsmError("@ERn+ loads and @-ERn stores only")
            return bytes((0x6C + word, s | mem.reg << 4 | reg))
        if mem.kind == "disp":
            displacement = self.value(mem.expr)
            size = mem.size or (16 if -32768 <= displacement <= 32767 else 24)
            if size == 16:
                return bytes((0x6E + word, s | mem.reg << 4 | reg)) + (displacement & 0xFFFF).to_bytes(2, "big")
            # GNU as sets the 0x78 selector bit for MOV.L stores (see long-displacement-store).
            selector = 0x80 if long and store else 0
            return bytes((0x78, selector | mem.reg << 4, 0x6A + word, (0xA0 if store else 0x20) | reg, 0)) + (
                displacement & 0xFFFFFF).to_bytes(3, "big")
        if mem.kind == "abs":
            address = self.value(mem.expr)
            size = mem.size or 16
            if size == 8:
                if word or long:
                    raise AsmError("@aa:8 is byte-only")
                return bytes(((0x30 if store else 0x20) | reg, address & 0xFF))
            if size == 16:
                return bytes((0x6A + word, (0x80 if store else 0) | reg)) + (address & 0xFFFF).to_bytes(2, "big")
            return bytes((0x6A + word, (0xA0 if store else 0x20) | reg, 0)) + (address & 0xFFFFFF).to_bytes(3, "big")
        raise AsmError("unsupported MOV operands")

    def addsub(self, base, suffix, ops):
        src, dst = ops
        if suffix == "b":
            if src.kind == "imm":
                if base == "sub":
                    raise AsmError("SUB.B has no immediate form")
                return bytes(((0x80 if base == "add" else 0xA0) | dst.reg, self.imm(src, 8)))
            return bytes(({"add": 0x08, "sub": 0x18, "cmp": 0x1C}[base], src.reg << 4 | dst.reg))
        code = {"add": 1, "cmp": 2, "sub": 3}[base]
        if suffix == "w":
            if src.kind == "imm":
                return bytes((0x79, code << 4 | dst.reg)) + self.imm(src, 16).to_bytes(2, "big")
            return bytes(({"add": 0x09, "sub": 0x19, "cmp": 0x1D}[base], src.reg << 4 | dst.reg))
        if src.kind == "imm":
            return bytes((0x7A, code << 4 | dst.reg)) + self.imm(src, 32).to_bytes(4, "big")
        return bytes(({"add": 0x0A, "sub": 0x1A, "cmp": 0x1F}[base], 0x80 | src.reg << 4 | dst.reg))

    def logic(self, base, suffix, ops):
        src, dst = ops
        code = {"or": 4, "xor": 5, "and": 6}[base]
        if suffix == "b":
            if src.kind == "imm":
                return bytes(({"or": 0xC0, "xor": 0xD0, "and": 0xE0}[base] | dst.reg, self.imm(src, 8)))
            return bytes(({"or": 0x14, "xor": 0x15, "and": 0x16}[base], src.reg << 4 | dst.reg))
        if suffix == "w":
            if src.kind == "imm":
                return bytes((0x79, code << 4 | dst.reg)) + self.imm(src, 16).to_bytes(2, "big")
            return bytes((0x60 | code, src.reg << 4 | dst.reg))
        if src.kind == "imm":
            return bytes((0x7A, code << 4 | dst.reg)) + self.imm(src, 32).to_bytes(4, "big")
        return bytes((0x01, 0xF0, 0x60 | code, src.reg << 4 | dst.reg))

    def bitop(self, base, ops):
        reg_form, rn_form, ind, absolute = BITS[base]
        number, target = ops
        if number.kind == "imm":
            opcode, field = reg_form, self.imm(number, 3) << 4
        else:
            opcode, field = rn_form, number.reg << 4
        if target.kind == "reg8":
            return bytes((opcode, field | target.reg))
        if target.kind == "ind":
            return bytes((ind, target.reg << 4, opcode, field))
        if target.kind == "abs":
            address = self.value(target.expr)
            if self.final and (target.size not in (None, 8) or not 0xFF00 <= address <= 0xFFFF):
                raise AsmError("bit operand address must be @aa:8 (0xff00-0xffff)")
            return bytes((absolute, address & 0xFF, opcode, field))
        raise AsmError("bit operand must be Rd, @ERd or @aa:8")

    def ccr_memory(self, operand, store):
        s = 0x80 if store else 0
        if operand.kind == "ind":
            return bytes((0x01, 0x40, 0x69, s | operand.reg << 4))
        if operand.kind == "disp":
            displacement = self.value(operand.expr)
            size = operand.size or (16 if -32768 <= displacement <= 32767 else 24)
            if size == 16:
                return bytes((0x01, 0x40, 0x6F, s | operand.reg << 4)) + (displacement & 0xFFFF).to_bytes(2, "big")
            return bytes((0x01, 0x40, 0x78, operand.reg << 4, 0x6B, 0xA0 if store else 0x20, 0)) + (
                displacement & 0xFFFFFF).to_bytes(3, "big")
        if operand.kind in ("postinc", "predec"):
            return bytes((0x01, 0x40, 0x6D, s | operand.reg << 4))
        if operand.kind == "abs":
            address = self.value(operand.expr)
            if (operand.size or 16) == 16:
                return bytes((0x01, 0x40, 0x6B, s)) + (address & 0xFFFF).to_bytes(2, "big")
            return bytes((0x01, 0x40, 0x6B, (0xA0 if store else 0x20), 0)) + (address & 0xFFFFFF).to_bytes(3, "big")
        raise AsmError("unsupported CCR operand")

    def ldc(self, src):
        if src.kind == "imm":
            return bytes((0x07, self.imm(src, 8)))
        if src.kind == "reg8":
            return bytes((0x03, src.reg))
        return self.ccr_memory(src, False)

    def stc(self, dst):
        if dst.kind == "reg8":
            return bytes((0x02, dst.reg))
        return self.ccr_memory(dst, True)


class Listing(list):
    """Instructions as (address, mnemonic, operands, length) from the final pass."""


def assemble(source: str, symbols: dict | None = None, listing: Listing | None = None):
    """Return a 48 KiB image and the final symbol table.

    Passes repeat until every label and branch size is stable. A supplied
    ``listing`` receives each encoded instruction of the final pass.
    """
    self = Assembler(symbols)
    self._numeric_all = []
    lines = []
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if line:
            lines.append((number, line, raw))
    symbols = dict(self.base_symbols)
    previous = None
    for attempt in range(8):
        final = attempt >= 1
        image, pc = bytearray(ROM_SIZE), 0
        self.written = bytearray(ROM_SIZE)
        self.listing = []
        numeric: list[tuple[str, int]] = []
        collected = []
        for index, (number, line, raw) in enumerate(lines):
            try:
                pc = _statement(self, index, line, symbols, numeric, image, pc, final)
            except AsmError as error:
                raise AsmError(f"line {number}: {raw.strip()}: {error}") from None
            for label, address in numeric[len(collected):]:
                collected.append((label, address, index))
        self._numeric_all = collected
        snapshot = (dict(symbols), list(collected))
        if final and snapshot == previous:
            if listing is not None:
                listing[:] = self.listing
            return bytes(image), symbols
        previous = snapshot
    raise AsmError("label addresses did not converge")


def _statement(self, index, line, symbols, numeric, image, pc, final):
    self.index, self.numeric, self.pc = index, numeric, pc
    self.symbols, self.final = symbols, final
    while True:
        m = re.match(r"^([A-Za-z_.$][\w.$]*|\d+):\s*", line)
        if not m:
            break
        if m.group(1).isdigit():
            numeric.append((m.group(1), pc))
        else:
            symbols[m.group(1)] = pc
        line = line[m.end():]
    if not line:
        return pc
    m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", line)
    if m:
        symbols[m.group(1)] = self.value(m.group(2))
        return pc
    mnemonic, _, rest = line.partition(" ")
    mnemonic = mnemonic.lower()
    operands = split_operands(rest)
    if mnemonic.startswith("."):
        return self.directive(mnemonic, operands, image, pc)
    parsed = [parse_operand(o) for o in operands]
    code = self.encode(mnemonic, parsed)
    self.emit(image, pc, code)
    self.listing.append((pc, mnemonic, [_resolved(self, o) for o in parsed], len(code)))
    return pc + len(code)


def _resolved(self, operand):
    """Operand kind, register and evaluated address or immediate for timing."""
    value = None
    if operand.expr is not None:
        try:
            value = self.value(operand.expr)
        except AsmError:
            value = None
    return (operand.kind, operand.reg, value, operand.size)
