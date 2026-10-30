use super::*;

pub(super) fn check(h: &mut Harness) {
    loads_and_stores(h);
    moves(h);
    indexed(h);
    clear(h);
    banked(h);
}

fn loads_and_stores(h: &mut Harness) {
    for (opcode, mode) in [(0x76, I), (0x77, Z), (0x78, B), (0x79, T), (0x7a, R)] {
        for profile in 0..4 {
            let mut c = Case::new(opcode, 0x69, 15, profile);
            c.operand(mode, false, 0x96, 1);
            c.clocks = 1 + mode.read_clocks();
            h.check(c, |c| c.a = 0x96);
        }
    }
    for (opcode, mode) in [(0x7f, Z), (0x80, B), (0x81, T), (0x82, R)] {
        for profile in 0..4 {
            let mut c = Case::new(opcode, 0x96, 15, profile);
            let addr = c.operand(mode, true, 0x69, 1);
            c.clocks = 1 + mode.read_clocks();
            h.check(c, |c| c.write(addr, 0x96, 1));
        }
    }
}

fn moves(h: &mut Harness) {
    for (i, dest) in [Z, B, T, R].into_iter().enumerate() {
        for profile in 0..4 {
            let mut c = Case::new(0x84 + i as u8, 0x13, 15, profile);
            c.emit(0x69, 1);
            let dst = c.operand(dest, true, 0xa5, 1);
            c.clocks = 2 + dest.read_clocks();
            h.check(c, |c| {
                c.write(dst, 0x69, 1);
                c.a = 0x69;
            });
        }
    }
    for (i, source) in [Z, B, T, R].into_iter().enumerate() {
        for (j, dest) in [Z, B, T, R].into_iter().enumerate() {
            for profile in 0..4 {
                let mut c = Case::new(0x8a + (4 * i + j) as u8, 0x13, 15, profile);
                let src = c.operand(source, false, 0x96, 1);
                let dst = c.operand(dest, true, 0x69, 1);
                c.clocks = 1 + source.read_clocks() + dest.read_clocks();
                h.check(c, |c| {
                    let v = c.read(src, 1);
                    c.write(dst, v, 1);
                    c.a = v as u8;
                });
            }
        }
    }
    for (opcode, immediate, source, dest, clocks) in [
        (0x88, true, I, Z, 6),
        (0x89, true, I, B, 13),
        (0x9a, false, Z, Z, 7),
        (0x9b, false, B, Z, 9),
    ] {
        for profile in 0..4 {
            let mut c = Case::new(opcode, 0x13, 15, profile);
            let src = c.operand(source, false, 0x963c, 2);
            let dst = c.operand(dest, true, 0xa569, 2);
            c.clocks = clocks;
            h.check(c, |c| {
                let v = if immediate { 0x963c } else { c.read(src, 2) };
                c.write(dst, v, 2);
                c.a = (v >> 8) as u8;
            });
        }
    }
}

fn indexed(h: &mut Harness) {
    for profile in 0..4 {
        for index in [0, 1, 0x7f, 0xff] {
            let mut c = Case::new(0x7b, index, 15, profile); // LAP
            c.emit(0x23, 1);
            c.write(0x2300 | index as u16, 0x69, 1);
            c.clocks = 4;
            h.check(c, |c| c.a = 0x69);
            for (opcode, zp_index) in [(0x7c, false), (0x7e, true)] {
                let mut c = Case::new(opcode, index, 15, profile);
                if zp_index {
                    c.operand(Z, false, index as u32, 1);
                }
                c.emit(0x23ff, 2);
                c.write(0x23ff + index as u16, 0x69, 1);
                c.clocks = if zp_index { 7 } else { 5 } + if index != 0 { 2 } else { 0 };
                h.check(c, |c| {
                    c.a = 0x69;
                    c.alu_flags(0xffu8.wrapping_add(index), index != 0);
                });
            }
            for opcode in [0x7d, 0x83] {
                // LZP / SZP
                let mut c = Case::new(opcode, 0x96, 15, profile);
                c.operand(Z, false, index as u32, 1);
                c.emit(0x23, 1);
                c.write(0x2300 | index as u16, 0x69, 1);
                c.clocks = 6;
                h.check(c, |c| {
                    if opcode == 0x7d {
                        c.a = 0x69;
                    } else {
                        c.write(0x2300 | index as u16, 0x96, 1);
                    }
                });
            }
        }
    }
}

fn clear(h: &mut Harness) {
    for (opcode, mode, width, clocks) in [
        (0x9c, I, 0, 3),
        (0x9d, Z, 1, 4),
        (0x9e, B, 1, 6),
        (0x9f, Z, 2, 4),
        (0xa0, B, 2, 7),
        (0xa1, Z, 4, 6),
        (0xa2, B, 4, 11),
    ] {
        for profile in 0..4 {
            let mut c = Case::new(opcode, 0x69, 15, profile);
            let addr = if width != 0 {
                c.operand(mode, true, 0xff12_ffff, width)
            } else {
                0
            };
            c.clocks = clocks;
            h.check(c, |c| {
                c.write(addr, 0, width);
                if width != 1 {
                    c.a = 0;
                }
            });
        }
    }
    for profile in 0..4 {
        let mut c = Case::new(0xa3, 0x69, 15, profile);
        let dst = c.operand(T, false, 0xa5, 1);
        let ptr = c.code[1] as u16;
        c.clocks = 16;
        h.check(c, |c| {
            for i in 0..5 {
                c.write(dst.wrapping_add(i), 0, 1);
            }
            let low = dst as u8;
            c.a = low.wrapping_add(5);
            c.write(ptr, c.a as u32, 1); // only the low pointer byte is advanced
            c.alu_flags(if low > 250 { 0 } else { c.a }, low > 250);
        });
    }
}

fn banked(h: &mut Harness) {
    for profile in 0..4 {
        for bank in [0, 5, 0x7f, 0x80, 0xff] {
            for opcode in [0x70, 0x71, 0x72, 0x73] {
                let mut c = Case::new(opcode, 0xff, 15, profile);
                let addr = 0x23ffu16;
                match opcode {
                    0x70 => {
                        c.emit(addr, 2);
                        c.emit(bank as u16, 1);
                        c.clocks = 8;
                    }
                    0x71 => {
                        c.emit(0x4500, 2);
                        c.write(0x4500, addr as u32 | (bank as u32) << 16, 3);
                        c.clocks = 11;
                    }
                    0x72 => {
                        c.emit(0x23 | (bank as u16) << 8, 2);
                        c.clocks = 7;
                    }
                    0x73 => {
                        c.operand(Z, false, 0xff, 1);
                        c.emit(0x23 | (bank as u16) << 8, 2);
                        c.clocks = 9;
                    }
                    _ => unreachable!(),
                }
                if bank < 128 {
                    c.flash.push((((bank as usize) << 12) | 0x3ff, 0x96));
                } else {
                    c.write(addr, 0x96, 1);
                }
                h.check(c, |c| c.a = 0x96);
            }
            for opcode in [0x74, 0x75] {
                let mut c = Case::new(opcode, 0x96, 15, profile);
                let addr = 0x23ffu16;
                if opcode == 0x74 {
                    c.emit(addr, 2);
                    c.emit(bank as u16, 1);
                    c.clocks = 14;
                } else {
                    c.emit(0x4500, 2);
                    c.write(0x4500, addr as u32 | (bank as u32) << 16, 3);
                    c.clocks = 16;
                }
                h.check(c, |c| {
                    c.write(0xff, c.start.wrapping_add(2) as u8 as u32, 1);
                    if bank >= 128 {
                        c.write(addr, 0x96, 1);
                    }
                });
            }
        }
    }
}
