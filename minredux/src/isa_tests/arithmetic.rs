use super::*;

pub(super) fn check(h: &mut Harness) {
    byte_binary(h);
    unary(h);
    shifts(h);
    scalar_to_memory(h);
    memory_arithmetic(h);
    comparisons(h);
    carry_arithmetic(h);
}

fn byte_binary(h: &mut Harness) {
    // (register forms, writeback forms); mode order I/Z/B/T/R.
    let families = [
        ([0x3a, 0x3b, 0x3c, 0x3d, 0x3e], [0x3f, 0x40, 0x41, 0x42], 0),
        ([0x43, 0x44, 0x45, 0x46, 0x47], [0x48, 0x49, 0x4a, 0x4b], 1),
        ([0x4c, 0x4d, 0x4e, 0x4f, 0x50], [0x51, 0x52, 0x53, 0x54], 2),
        ([0xb0, 0xb1, 0xb2, 0xb3, 0xb4], [0xb5, 0xb6, 0xb7, 0xb8], 3),
        ([0xcc, 0xcd, 0xce, 0xcf, 0xd0], [0xd1, 0xd2, 0xd3, 0xd4], 4),
        ([0xe8, 0xe9, 0xea, 0xeb, 0xec], [0, 0, 0, 0], 5),
    ];
    let pairs = [
        (0, 0),
        (0, 1),
        (1, 0),
        (0xff, 1),
        (1, 0xff),
        (0x80, 0x80),
        (0x0f, 1),
        (0xf0, 0x10),
        (0x55, 0xaa),
    ];
    for (register, memory, kind) in families {
        for writeback in [false, true] {
            if kind == 5 && writeback {
                continue;
            }
            for (i, mode) in [I, Z, B, T, R].into_iter().enumerate() {
                if writeback && i == 0 {
                    continue;
                }
                let opcode = if writeback {
                    memory[i - 1]
                } else {
                    register[i]
                };
                for (profile, &(a, b)) in pairs.iter().enumerate() {
                    let mut c = Case::new(opcode, a, 15, profile);
                    let addr = c.operand(mode, false, b as u32, 1);
                    if matches!(opcode, 0x52 | 0x54) {
                        c.xor_erratum = Some((addr, b));
                    }
                    c.clocks = 2 + mode.read_clocks();
                    if writeback && kind == 4 {
                        c.clocks += 1;
                    }
                    if kind == 2 {
                        c.clocks += 4;
                    }
                    if kind == 2 && matches!(mode, Z | T) && writeback {
                        c.clocks -= 1;
                    }
                    h.check(c, |c| {
                        let (lhs, rhs) = if writeback && kind == 4 {
                            (b, a)
                        } else {
                            (a, b)
                        };
                        let result = match kind {
                            0 => lhs & rhs,
                            1 => lhs | rhs,
                            2 => lhs ^ rhs,
                            3 => lhs.wrapping_add(rhs),
                            _ => lhs.wrapping_sub(rhs),
                        };
                        if kind >= 3 {
                            c.alu_flags(
                                result,
                                if kind == 3 {
                                    lhs as u16 + rhs as u16 > 255
                                } else {
                                    lhs >= rhs
                                },
                            );
                        }
                        if kind != 5 {
                            c.a = result;
                        }
                        if writeback {
                            c.write(addr, result as u32, 1);
                        }
                        if kind == 2
                            && !(writeback && matches!(mode, Z | T))
                            && !(c.fixed_rom && matches!(opcode, 0x52 | 0x54))
                        {
                            c.write(0xff, if opcode == 0x54 { result } else { a & b } as u32, 1);
                        }
                    });
                }
            }
        }
    }
}

const VALUES: [u32; 16] = [
    0, 1, 0xff, 0x100, 0xffff, 0x10000, 0xffffff, 0xffffffff, 0x7fffffff, 0x80000000, 0x12345678,
    0x00ff00ff, 0x01010101, 0xfffffffe, 0x80008000, 0xf0f00f0f,
];

fn mask(width: usize) -> u32 {
    if width == 4 {
        u32::MAX
    } else {
        (1u32 << (8 * width)) - 1
    }
}

fn unary(h: &mut Harness) {
    // kind: NOT, NEG, INC, DEC. Multi-byte flags describe the last ALU byte,
    // not an invented aggregate 16/32-bit zero/negative result.
    for (opcodes, kind) in [
        ([0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33], 0),
        ([0x34, 0x35, 0x36, 0x37, 0x38, 0x39], 1),
        ([0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9], 2),
        ([0xaa, 0xab, 0xac, 0xad, 0xae, 0xaf], 3),
    ] {
        for (form, &opcode) in opcodes.iter().enumerate() {
            let (mode, width) = match form {
                0 => (I, 1),
                1 => (Z, 1),
                2 => (B, 1),
                3 => (Z, 2),
                4 => (B, 2),
                _ => (Z, 4),
            };
            for (n, &value) in VALUES.iter().enumerate() {
                let v = value & mask(width);
                let mut c = Case::new(opcode, v as u8, 15, n);
                let addr = if form == 0 {
                    0
                } else {
                    c.operand(mode, false, v, width)
                };
                c.clocks = if form == 0 {
                    if kind < 2 { 4 } else { 3 }
                } else {
                    mode.read_clocks() + 3
                };
                if width > 1 {
                    c.clocks += 2 * (width as u64 - 1);
                }
                let result = match kind {
                    0 => !v,
                    1 => v.wrapping_neg(),
                    2 => v.wrapping_add(1),
                    _ => v.wrapping_sub(1),
                } & mask(width);
                let mut last = width - 1;
                if width == 4 && kind >= 2 {
                    last = (0..4)
                        .find(|&i| {
                            if kind == 2 {
                                (v >> (8 * i)) as u8 != 255
                            } else {
                                (v >> (8 * i)) as u8 != 0
                            }
                        })
                        .unwrap_or(3);
                    c.clocks = 6 + 2 * last as u64;
                    if last == 3 {
                        c.clocks -= 1;
                    }
                    c.check_a = false; // ISA leaves A unspecified on early exit
                }
                h.check(c, |c| {
                    if form != 0 {
                        c.write(addr, result, width);
                    }
                    if c.check_a {
                        c.a = (result >> (8 * last)) as u8;
                    }
                    if kind != 0 {
                        let out = (result >> (8 * last)) as u8;
                        let carry = if kind == 1 {
                            v == 0
                        } else if kind == 2 {
                            v & mask(last + 1) == mask(last + 1)
                        } else {
                            v & mask(last + 1) != 0
                        };
                        c.alu_flags(out, carry);
                    }
                });
            }
        }
    }
}

fn rotate_left(a: u8, carry: bool, count: usize) -> (u8, bool) {
    let nine = ((carry as u16) << 8) | a as u16;
    let n = count % 9;
    let out = ((nine << n) | (nine >> (9 - n))) & 0x1ff;
    (out as u8, out & 0x100 != 0)
}

fn shifts(h: &mut Harness) {
    for a in 0..=255u8 {
        for cin in [false, true] {
            for (first, kind) in [(0x05, 0), (0x0d, 1), (0x16, 2)] {
                for n in 0..8 {
                    let opcode = first + n;
                    let mut c = Case::new(opcode, a, if cin { 15 } else { 11 }, n as usize);
                    c.clocks = match (kind, n) {
                        (_, 0) => 2,
                        (0 | 1, _) => n as u64 + 2,
                        (2, 1) => 10,
                        (2, 2..=5) => 15,
                        (2, 6) => 13,
                        (2, 7) => 5,
                        _ => unreachable!(),
                    };
                    h.check(c, |c| {
                        if n == 0 {
                            return;
                        }
                        let (r, carry) = if kind == 0 {
                            (((a as u16) << n) as u8, ((a as u16) << n) & 256 != 0)
                        } else if kind == 1 {
                            rotate_left(a, cin, n as usize)
                        } else {
                            (a >> n, if n == 1 { a & 1 != 0 } else { false })
                        };
                        c.a = r;
                        if kind == 2 && (2..=5).contains(&n) {
                            c.write(0xff, a as u32, 1);
                        }
                        if kind == 2 && n == 6 {
                            let (tmp, carry) = rotate_left(a, false, 3);
                            c.write(0xff, tmp as u32, 1);
                            c.alu_flags(tmp, carry);
                        } else if kind == 2 && n == 7 {
                            c.alu_flags(a.wrapping_mul(2), a & 128 != 0);
                        } else {
                            c.alu_flags(r, carry);
                        }
                    });
                }
            }
            let mut c = Case::new(0x15, a, if cin { 15 } else { 11 }, a as usize);
            c.clocks = 10;
            h.check(c, |c| {
                c.a = (a >> 1) | if cin { 128 } else { 0 };
                c.alu_flags(c.a, a & 1 != 0);
            });
        }
    }
    for (opcode, kind, mode, width) in [
        (0x1e, 0, Z, 1),
        (0x1f, 0, B, 1),
        (0x20, 0, Z, 2),
        (0x21, 0, B, 2),
        (0x22, 0, Z, 4),
        (0x23, 0, B, 4),
        (0x24, 2, Z, 1),
        (0x25, 2, B, 1),
        (0x26, 1, Z, 1),
        (0x27, 1, B, 1),
        (0x28, 1, Z, 2),
        (0x29, 1, B, 2),
        (0x2a, 1, Z, 4),
        (0x2b, 1, B, 4),
        (0x2c, 3, Z, 1),
        (0x2d, 3, B, 1),
    ] {
        for (n, &value) in VALUES.iter().enumerate() {
            for cin in [false, true] {
                let v = value & mask(width);
                let mut c = Case::new(opcode, 0x69, if cin { 15 } else { 11 }, n);
                let addr = c.operand(mode, false, v, width);
                c.clocks = mode.read_clocks() + 2 * width as u64;
                if kind >= 2 {
                    c.clocks += 7;
                }
                h.check(c, |c| {
                    let (r, carry) = if kind <= 1 {
                        let sum = (v as u64) * 2 + u64::from(kind == 1 && cin);
                        ((sum as u32) & mask(width), sum > mask(width) as u64)
                    } else {
                        (
                            (v >> 1) | if kind == 3 && cin { 128 } else { 0 },
                            v & 1 != 0,
                        )
                    };
                    c.write(addr, r, width);
                    c.a = (r >> (8 * (width - 1))) as u8;
                    c.alu_flags(c.a, carry);
                });
            }
        }
    }
}

/// Scalar add/sub to a byte/word/long destination. Word paths always inspect
/// the high byte; long paths stop as soon as carry/borrow propagation ends.
fn scalar_case(
    h: &mut Harness,
    opcode: u8,
    source: Option<Mode>,
    dest: Mode,
    width: usize,
    subtract: bool,
) {
    for (n, &v) in VALUES.iter().enumerate() {
        for scalar in [0u8, 1, 0x7f, 0x80, 0xff] {
            let v = v & mask(width);
            let mut c = Case::new(opcode, scalar, 15, n);
            let src = source.map(|m| c.operand(m, false, scalar as u32, 1));
            let dst = c.operand(dest, true, v, width);
            let low_clocks = if let Some(s) = source {
                2 + s.read_clocks() + dest.read_clocks()
            } else {
                2 + dest.read_clocks() + u64::from(subtract)
            };
            c.clocks = low_clocks;
            if width == 2 {
                c.clocks += 3;
            }
            if width == 4 {
                c.check_a = false;
            }
            h.check(c, |c| {
                let scalar = if let (Some(mode), Some(addr)) = (source, src) {
                    if matches!(mode, I) {
                        scalar
                    } else {
                        c.read(addr, 1) as u8
                    }
                } else {
                    scalar
                };
                let v = c.read(dst, width);
                let r = if subtract {
                    v.wrapping_sub(scalar as u32)
                } else {
                    v.wrapping_add(scalar as u32)
                } & mask(width);
                c.write(dst, r, width);
                if width == 1 {
                    c.a = r as u8;
                    c.alu_flags(
                        c.a,
                        if subtract {
                            (v as u8) >= scalar
                        } else {
                            (v as u8 as u16) + scalar as u16 > 255
                        },
                    );
                } else if width == 2 {
                    c.a = (r >> 8) as u8;
                    c.alu_flags(
                        c.a,
                        if subtract {
                            v >= scalar as u32
                        } else {
                            v + scalar as u32 > 65535
                        },
                    );
                } else {
                    let mut last = 0;
                    let mut propagate = if subtract {
                        (v as u8) < scalar
                    } else {
                        (v as u8 as u16) + scalar as u16 > 255
                    };
                    if propagate {
                        for i in 1..4 {
                            last = i;
                            propagate = if subtract {
                                (v >> (8 * i)) as u8 == 0
                            } else {
                                (v >> (8 * i)) as u8 == 255
                            };
                            if !propagate {
                                break;
                            }
                        }
                    }
                    c.clocks = low_clocks
                        + match last {
                            0 => 1,
                            1 => 4,
                            2 => 6,
                            _ => 7,
                        };
                    // The final (fourth) byte is written without FI.
                    let flag_byte = last.min(2);
                    let carry = if subtract {
                        v & mask(flag_byte + 1) >= scalar as u32
                    } else {
                        (v & mask(flag_byte + 1)) as u64 + scalar as u64
                            > mask(flag_byte + 1) as u64
                    };
                    c.alu_flags((r >> (8 * flag_byte)) as u8, carry);
                }
            });
        }
    }
}

fn scalar_to_memory(h: &mut Harness) {
    for (base, subtract) in [(0xbc, false), (0xd8, true)] {
        for (i, mode) in [Z, B, T, R].into_iter().enumerate() {
            scalar_case(h, base + i as u8, Some(I), mode, 1, subtract);
        }
    }
    for (base, subtract) in [(0xc0, false), (0xdc, true)] {
        for (i, (mode, width)) in [(Z, 2), (B, 2), (Z, 4)].into_iter().enumerate() {
            scalar_case(h, base + i as u8, Some(I), mode, width, subtract);
        }
    }
    for (base, subtract) in [(0xb9, false), (0xd5, true)] {
        for (i, (mode, width)) in [(Z, 2), (B, 2), (Z, 4)].into_iter().enumerate() {
            scalar_case(h, base + i as u8, None, mode, width, subtract);
        }
    }
}

fn memory_arithmetic(h: &mut Harness) {
    for (base, subtract) in [(0xc3, false), (0xdf, true)] {
        for (i, (source, dest, width)) in [
            (Z, Z, 1),
            (Z, T, 1),
            (Z, Z, 2),
            (Z, Z, 4),
            (B, B, 1),
            (B, B, 2),
            (T, Z, 1),
            (T, T, 1),
        ]
        .into_iter()
        .enumerate()
        {
            scalar_case(h, base + i as u8, Some(source), dest, width, subtract);
        }
    }
    for (opcode, subtract) in [(0xcb, false), (0xe7, true)] {
        for (n, &lhs) in VALUES.iter().enumerate() {
            for rhs in [0, 1, 0xff, 0x100, 0x7fff, 0x8000, 0xffff] {
                let mut c = Case::new(opcode, 0x69, 15, n);
                let src = c.operand(Z, false, lhs & 65535, 2);
                let dst = c.operand(Z, true, rhs, 2);
                c.clocks = 14;
                h.check(c, |c| {
                    // Both low bytes are sampled before writing; high bytes
                    // are read afterwards, preserving observable aliasing.
                    let left = c.read(src, 1);
                    let right = c.read(dst, 1);
                    let low = if subtract {
                        right.wrapping_sub(left)
                    } else {
                        right + left
                    };
                    c.write(dst, low & 255, 1);
                    let carry = if subtract { right >= left } else { low > 255 };
                    let hi_src = c.read(src.wrapping_add(1), 1);
                    let hi_dst = c.read(dst.wrapping_add(1), 1);
                    let hi = if subtract {
                        hi_dst as i32 - hi_src as i32 - i32::from(!carry)
                    } else {
                        (hi_dst + hi_src + u32::from(carry)) as i32
                    };
                    c.write(dst.wrapping_add(1), hi as u32 & 255, 1);
                    c.a = hi as u8;
                    c.alu_flags(c.a, if subtract { hi >= 0 } else { hi > 255 });
                });
            }
        }
    }
}

fn comparisons(h: &mut Harness) {
    for (opcode, source, dest) in [
        (0xed, I, Z),
        (0xee, I, B),
        (0xef, I, T),
        (0xf0, I, R),
        (0xf3, Z, Z),
        (0xf4, Z, T),
        (0xf5, B, B),
        (0xf6, T, Z),
        (0xf7, T, T),
    ] {
        for n in 0..32 {
            let a = [0, 1, 0x7f, 0x80, 0xff, 0x55, 0xaa, 0x10][n % 8];
            let b = [0, 0xff, 0x80, 1][n / 8];
            let mut c = Case::new(opcode, 0x69, 15, n);
            let src = c.operand(source, false, a, 1);
            let dst = c.operand(dest, true, b, 1);
            c.clocks = 2 + source.read_clocks() + dest.read_clocks();
            h.check(c, |c| {
                let src = if matches!(source, I) {
                    a as u8
                } else {
                    c.read(src, 1) as u8
                };
                let dst = c.read(dst, 1) as u8;
                c.a = if opcode == 0xee {
                    dst.wrapping_sub(src)
                } else {
                    dst
                };
                c.alu_flags(dst.wrapping_sub(src), dst >= src);
            });
        }
    }
    for (opcode, source, dest, unequal, equal) in [
        (0xf1, I, Z, 10, 12),
        (0xf2, I, B, 13, 16),
        (0xf8, Z, Z, 11, 14),
    ] {
        for (n, &a) in VALUES.iter().enumerate() {
            for b in [0, 1, 0xff, 0x100, 0x7fff, 0xffff, a & 65535] {
                let a = a & 65535;
                let mut c = Case::new(opcode, 0x69, 15, n);
                let src = c.operand(source, false, a, 2);
                let dst = c.operand(dest, true, b, 2);
                h.check(c, |c| {
                    let a = if matches!(source, I) {
                        a
                    } else {
                        c.read(src, 2)
                    };
                    let b = c.read(dst, 2);
                    let high_equal = (a >> 8) == (b >> 8);
                    let lhs = if high_equal { b as u8 } else { (b >> 8) as u8 };
                    let rhs = if high_equal { a as u8 } else { (a >> 8) as u8 };
                    c.clocks = if high_equal { equal } else { unequal };
                    c.a = lhs;
                    c.alu_flags(lhs.wrapping_sub(rhs), lhs >= rhs);
                });
            }
        }
    }
}

fn carry_arithmetic(h: &mut Harness) {
    for (opcode, mode, writeback, subtract) in [
        (0xf9, I, false, false),
        (0xfa, Z, false, false),
        (0xfb, Z, true, false),
        (0xfc, I, false, true),
        (0xfd, Z, false, true),
        (0xfe, Z, true, true),
    ] {
        for a in [0u8, 1, 0x7f, 0x80, 0xfe, 0xff] {
            for b in [0u8, 1, 0x7f, 0x80, 0xfe, 0xff] {
                for cin in [false, true] {
                    let mut c = Case::new(opcode, a, if cin { 15 } else { 11 }, a as usize);
                    let dst = c.operand(mode, false, b as u32, 1);
                    c.clocks = 2 + mode.read_clocks() + u64::from(writeback && subtract);
                    h.check(c, |c| {
                        let (lhs, rhs) = if writeback && subtract {
                            (b, a)
                        } else {
                            (a, b)
                        };
                        let r = if subtract {
                            lhs as i32 - rhs as i32 - i32::from(!cin)
                        } else {
                            lhs as i32 + rhs as i32 + i32::from(cin)
                        };
                        c.a = r as u8;
                        if writeback {
                            c.write(dst, c.a as u32, 1);
                        }
                        c.alu_flags(c.a, if subtract { r >= 0 } else { r > 255 });
                    });
                }
            }
        }
    }
}

#[test]
fn exhaustive_immediate_logic_preserves_flags_and_xor_scratch() {
    let mut m = cpu(&[]);
    for (opcode, clocks) in [(0x3a, 3), (0x43, 3), (0x4c, 7)] {
        for a in 0..=255u8 {
            for b in 0..=255u8 {
                m.ram[0xff] = 0x96;
                let cycles = execute(&mut m, 0x8000, &[opcode, b], a, 15);
                let result = match opcode {
                    0x3a => a & b,
                    0x43 => a | b,
                    _ => a ^ b,
                };
                assert_eq!(cycles, clocks);
                assert_eq!(m.ar, result, "opcode={opcode:02x} a={a:02x} b={b:02x}");
                assert_eq!(m.fr, F_R | 15);
                assert_eq!(m.ram[0xff], if opcode == 0x4c { a & b } else { 0x96 });
                assert_eq!((m.pc, m.mar), (0x8002, 0x8002));
            }
        }
    }
}

#[test]
fn exhaustive_word_unary_operations_cross_the_zero_page_boundary() {
    let mut m = cpu(&[]);
    for (opcode, clocks) in [(0xa7, 7), (0xad, 7), (0x37, 7), (0x20, 6), (0x28, 6)] {
        for cin in [false, true] {
            for value in 0..=65535u32 {
                m.ram[0xff] = value as u8;
                m.ram[0x100] = (value >> 8) as u8;
                m.ram[0xfe] = 0x55;
                m.ram[0x101] = 0xaa;
                m.ram[0] = 0x5a;
                let cycles = execute(
                    &mut m,
                    0x8000,
                    &[opcode, 0xff],
                    0x69,
                    if cin { 15 } else { 11 },
                );
                let raw = match opcode {
                    0xa7 => value + 1,
                    0xad => value.wrapping_sub(1),
                    0x37 => value.wrapping_neg(),
                    0x20 => value * 2,
                    0x28 => value * 2 + u32::from(cin),
                    _ => unreachable!(),
                };
                let result = raw & 65535;
                let carry = match opcode {
                    0xad => value != 0,
                    0x37 => value == 0,
                    _ => raw > 65535,
                };
                assert_eq!(cycles, clocks);
                assert_eq!(
                    (m.ram[0xff], m.ram[0x100]),
                    (result as u8, (result >> 8) as u8),
                    "opcode={opcode:02x} v={value:04x} carry={cin}"
                );
                assert_eq!(m.fr, F_R | byte_flags((result >> 8) as u8, carry));
                assert_eq!(m.ar, (result >> 8) as u8);
                assert_eq!((m.ram[0xfe], m.ram[0x101], m.ram[0]), (0x55, 0xaa, 0x5a));
                assert_eq!((m.pc, m.mar), (0x8002, 0x8002));
            }
        }
    }
}

#[test]
fn word_comparison_checks_every_destination_against_six_thresholds() {
    let mut m = cpu(&[]);
    for threshold in [0u16, 0xff, 0x100, 0x7fff, 0x8000, 0xffff] {
        for value in 0..=65535u32 {
            m.ram[0xff] = value as u8;
            m.ram[0x100] = (value >> 8) as u8;
            let code = [0xf1, threshold as u8, (threshold >> 8) as u8, 0xff]; // CIV imm16,zp
            let clocks = execute(&mut m, 0x80ff, &code, 0x69, 15);
            let high_equal = value >> 8 == (threshold as u32) >> 8;
            let lhs = if high_equal {
                value as u8
            } else {
                (value >> 8) as u8
            };
            let rhs = if high_equal {
                threshold as u8
            } else {
                (threshold >> 8) as u8
            };
            assert_eq!(clocks, if high_equal { 12 } else { 10 });
            assert_eq!(m.fr, F_R | byte_flags(lhs.wrapping_sub(rhs), lhs >= rhs));
            assert_eq!(m.ar, lhs);
            assert_eq!(
                (m.ram[0xff], m.ram[0x100]),
                (value as u8, (value >> 8) as u8)
            );
            assert_eq!((m.pc, m.mar), (0x8103, 0x8103));
        }
    }
}
