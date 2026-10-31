use super::*;

pub(super) fn check(h: &mut Harness) {
    branches(h);
    jumps(h);
    stack(h);
    io(h);
}

fn branches(h: &mut Harness) {
    for f in 0..16 {
        let z = f & 3 == 3;
        let carry = f & F_C != 0;
        let negative = f & F_N != 0;
        let conditions = [
            !z,
            z,
            !carry,
            carry,
            !negative,
            negative,
            carry && !z,
            !carry || z,
            true,
        ];
        for (i, take) in conditions.into_iter().enumerate() {
            for profile in 0..4 {
                let mut c = Case::new(0x55 + i as u8, 0x69, f, profile);
                if profile == 2 {
                    c.start = 0xffff;
                }
                c.emit(0x42, 1);
                c.clocks = 2;
                h.check(c, |c| {
                    if take {
                        c.pc = Some(c.start.wrapping_add(1) & 0xff00 | 0x42);
                    }
                });
                let mut c = Case::new(0x5e + i as u8, 0x69, f, profile);
                if profile == 2 {
                    c.start = 0xffff;
                }
                c.emit(0x9342, 2);
                c.clocks = if take { 4 } else { 3 };
                h.check(c, |c| {
                    if take {
                        c.pc = Some(0x9342);
                    }
                });
            }
        }
    }
}

fn jumps(h: &mut Harness) {
    for profile in 0..4 {
        let mut c = Case::new(0x67, 0x69, 15, profile);
        let ptr = [0x4500, 0x45ff, 0xffff, 0x00ff][profile];
        c.emit(ptr, 2);
        c.write(ptr, 0x9342, 2);
        c.clocks = 7;
        h.check(c, |c| c.pc = Some(0x9342));
        for base in [0x4500u16, 0x45ff, 0xffff] {
            for a in [0, 1, 0x7f, 0xff] {
                let mut c = Case::new(0x68, a, 15, profile);
                c.emit(base, 2);
                c.write(base.wrapping_add(a as u16), 0x9342, 2);
                let carry = (base as u8 as u16) + a as u16 > 255;
                c.clocks = 7 + if carry { 2 } else { 0 };
                h.check(c, |c| {
                    c.pc = Some(0x9342);
                    c.alu_flags((base as u8).wrapping_add(a), carry);
                });
            }
        }
    }
}

fn stack(h: &mut Harness) {
    for profile in 0..4 {
        for sp in [0u8, 1, 2, 0x7f, 0xfc, 0xfd, 0xfe, 0xff] {
            let mut c = Case::new(0x6c, 0x69, 15, profile); // PHS
            c.write(0xffff, sp as u32, 1);
            c.clocks = 8;
            h.check(c, |c| {
                c.write(0xff00 | sp as u16, 0x69, 1);
                c.write(0xffff, sp.wrapping_sub(1) as u32, 1);
                c.a = c.read(0xff00 | sp as u16, 1) as u8;
            });
            let mut c = Case::new(0x6d, 0x69, 15, profile); // PLS
            c.write(0xff00 | sp.wrapping_add(1) as u16, 0x96, 1);
            c.write(0xffff, sp as u32, 1);
            c.clocks = 6;
            h.check(c, |c| {
                c.write(0xffff, sp.wrapping_add(1) as u32, 1);
                c.a = c.read(0xff00 | sp.wrapping_add(1) as u16, 1) as u8;
            });
            for offset in [0u8, 1, 2, 0x7f, 0xfe, 0xff] {
                for opcode in [0x6e, 0x6f] {
                    let mut c = Case::new(opcode, 0x69, 15, profile);
                    c.emit(offset as u16, 1);
                    c.write(0xffff, sp as u32, 1);
                    c.clocks = if opcode == 0x6e { 6 } else { 11 };
                    h.check(c, |c| {
                        let dst = 0xff00 | sp.wrapping_add(offset) as u16;
                        if opcode == 0x6e {
                            c.a = c.read(dst, 1) as u8;
                        } else {
                            c.write(0xff00 | sp as u16, 0x69, 1);
                            c.a = c.read(0xff00 | sp as u16, 1) as u8;
                            c.write(dst, c.a as u32, 1);
                        }
                    });
                }
            }
            for opcode in [0x69, 0x6a] {
                let mut c = Case::new(opcode, 0x69, 15, profile);
                c.emit(0x9342, 2);
                c.write(0xffff, sp as u32, 1);
                c.clocks = if opcode == 0x69 { 11 } else { 14 };
                h.check(c, |c| {
                    let ret = c.start.wrapping_add(1);
                    if opcode == 0x6a {
                        c.write(0xff, 0x69, 1);
                    }
                    c.write(0xff00 | sp as u16, ret as u8 as u32, 1);
                    c.write(0xff00 | sp.wrapping_sub(1) as u16, (ret >> 8) as u32, 1);
                    c.write(0xffff, sp.wrapping_sub(2) as u32, 1);
                    c.pc = Some(0x9342);
                    c.a = if opcode == 0x69 {
                        sp.wrapping_sub(1)
                    } else {
                        0x69
                    };
                });
            }
            let mut c = Case::new(0x6b, 0x69, 15, profile);
            let hi = (0xff00 | sp as u16).wrapping_add(1);
            let lo = hi.wrapping_add(1);
            c.write(hi, 0x93, 1);
            c.write(lo, 0x42, 1);
            c.write(0xffff, sp as u32, 1);
            c.clocks = 10;
            h.check(c, |c| {
                let ret = (c.read(hi, 1) << 8) | c.read(lo, 1);
                // RTS increments MAR as 16 bits; overflowing stack frames
                // really do access 0000/0001 and may update 00ff, not ffff.
                c.write(lo & 0xff00 | 0xff, sp.wrapping_add(2) as u32, 1);
                c.pc = Some((ret as u16).wrapping_add(2));
            });
        }
    }
}

fn io(h: &mut Harness) {
    for profile in 0..4 {
        let mut c = Case::new(0x00, 0x69, 15, profile);
        c.clocks = 16;
        h.check(c, |c| c.a = 0xff);
        for a in [0u8, 0x7f, 0x80, 0xff] {
            for rx in [None, Some(0), Some(0x61), Some(0x7f)] {
                for key in [None, Some(0), Some(0x1c), Some(0xff)] {
                    for opcode in [1, 2, 3, 4] {
                        let mut c = Case::new(opcode, a, 15, profile);
                        c.rx = rx;
                        c.key = key;
                        c.initial_fr = F_R
                            | 15
                            | if rx.is_none() { F_T } else { 0 }
                            | if key.is_none() { F_K } else { 0 };
                        c.clocks = match opcode {
                            1 => 174,
                            2 => 3,
                            3 => {
                                if key.is_some() {
                                    4
                                } else {
                                    3
                                }
                            }
                            4 => {
                                if rx.is_some() || key.is_some() {
                                    2
                                } else if c.start.wrapping_add(1) as u8 == 0 {
                                    6
                                } else {
                                    5
                                }
                            }
                            _ => unreachable!(),
                        };
                        h.check(c, |c| {
                            if opcode == 1 {
                                c.output.push(a & 0x7f);
                                // Final FI is the wait loop's sample at TX
                                // completion, before its subsequent UART flush.
                                c.fr = F_R
                                    | if key.is_none() { F_K } else { 0 }
                                    | byte_flags(a.wrapping_mul(2), a >= 128);
                            } else if opcode == 4 && rx.is_none() && key.is_none() {
                                let next = c.start.wrapping_add(1);
                                c.pc = Some(c.start);
                                c.a = if next as u8 == 0 {
                                    (next >> 8) as u8
                                } else {
                                    next as u8
                                };
                                c.alu_flags(c.start as u8, next as u8 != 0);
                            } else {
                                let sum = a as u16 + c.initial_b as u16;
                                c.alu_flags(sum as u8, sum > 255);
                                if opcode == 2 {
                                    c.a = rx.unwrap_or(0xff);
                                }
                                if opcode == 3 {
                                    c.a = key.unwrap_or(0xff);
                                }
                            }
                        });
                    }
                }
            }
        }
    }
}

#[test]
fn internal_ff_wait_state_polls_and_exits_without_fetching_an_opcode() {
    let mut m = cpu(&[]);
    m.pc = 0x9342;
    m.mar = 0x9342;
    m.bank = 0xff;
    m.ir = 0xff;
    m.sc = 0;
    m.ar = 0x61;
    m.br = 0x61;
    m.fr = F_R | F_T | F_K;
    m.flags = F_R | F_T | F_K;
    m.uart_tx_busy = 17;
    m.uart_tx_data = 0x61;
    m.collect_output = true;
    m.run_cycles(16);
    assert_eq!((m.pc, m.mar, m.ir, m.sc), (0x9342, 0x9342, 0xff, 0));
    assert!(m.uart_out.is_empty());
    m.run_cycles(1);
    assert_eq!(m.uart_out, [0x61]);
    assert_eq!(m.fr & F_T, 0);
    m.run_cycles(8);
    assert_eq!((m.pc, m.mar, m.ir, m.sc), (0x9342, 0x9342, 0, 0));
    assert_eq!(m.ar, 0x61);
}

#[test]
fn win_waits_then_wakes_at_the_expected_pc() {
    for start in [0x8000u16, 0x80ff, 0xffff] {
        for keyboard in [false, true] {
            let mut m = cpu(&[]);
            m.bank = 0xff;
            m.pc = start;
            m.mar = start;
            m.ram[start as usize] = 4;
            m.flags = F_R | F_T | F_K;
            m.fr = m.flags;
            // Three full WIN iterations elapse without input; every one must
            // rewind to the same instruction instead of advancing its PC.
            for _ in 0..3 {
                loop {
                    m.step();
                    if m.sc == 0 {
                        break;
                    }
                }
                assert_eq!((m.pc, m.mar), (start, start));
            }
            if keyboard {
                m.feed_ps2([0x1c]);
            } else {
                m.feed_uart([0x61]);
            }
            let mut woke = false;
            for _ in 0..16 {
                m.step();
                if m.sc == 0 {
                    if m.pc == start.wrapping_add(1) {
                        woke = true;
                        break;
                    }
                    assert_eq!((m.pc, m.mar), (start, start));
                }
            }
            assert!(woke, "WIN failed to wake: start={start:04x}");
            assert_eq!(m.mar, start.wrapping_add(1));
            if keyboard {
                assert_eq!(m.ps2_reg, 0x1c);
            } else {
                assert_eq!(m.uart_rx, 0x61);
            }
        }
    }
}

#[test]
fn operand_fetch_wraps_the_full_sixteen_bit_address_space() {
    let mut h = Harness::new();
    for (opcode, mode, clocks) in [
        (0x76, I, 2),
        (0x77, Z, 3),
        (0x78, B, 5),
        (0x79, T, 6),
        (0x7a, R, 8),
    ] {
        for start in [0xfffdu16, 0xfffe, 0xffff] {
            let mut c = Case::new(opcode, 0x69, 15, 0);
            c.start = start;
            c.operand(mode, false, 0x96, 1);
            c.clocks = clocks;
            h.check(c, |c| c.a = 0x96);
        }
    }
}

#[test]
fn write_bank_instructions_really_program_flash_and_restore_pc_and_bank() {
    for indirect in [false, true] {
        let mut m = cpu(&[]);
        let opcode = if indirect { 0x75 } else { 0x74 };
        for (addr, value) in [
            (0x5555usize, 0xaa),
            (0x2aaa, 0x55),
            (0x5555, 0xa0),
            (0x12345, 0x96),
        ] {
            let bank = (addr >> 12) as u8;
            let offset = (addr & 0xfff) as u16;
            let code = if indirect {
                m.ram[0x4500] = offset as u8;
                m.ram[0x4501] = (offset >> 8) as u8;
                m.ram[0x4502] = bank;
                vec![opcode, 0, 0x45]
            } else {
                vec![opcode, offset as u8, (offset >> 8) as u8, bank]
            };
            let clocks = execute(&mut m, 0x80ff, &code, value, 0);
            assert_eq!(clocks, if indirect { 16 } else { 14 });
            assert_eq!(m.pc, 0x80ff + code.len() as u16);
            assert_eq!(m.mar, m.pc);
            assert_eq!(m.bank, 0xff);
            assert_eq!(m.ar, value);
            assert_eq!(m.ram[0xff], 1); // saved low PC=8101
        }
        // Internal programming overlaps the final five WDB / four WDR clocks.
        assert_eq!(m.flash_busy_cycles(), if indirect { 108 } else { 107 });
        finish_flash(&mut m);
        assert_eq!(m.flash[0x12345], 0x96);
        assert_eq!(execute(&mut m, 0x80ff, &[0x70, 0x45, 3, 0x12], 0, 0), 8);
        assert_eq!(m.ar, 0x96);
    }
}

#[test]
fn indirect_pointer_bytes_wrap_from_ffff_to_0000() {
    let mut h = Harness::new();
    for opcode in [0x7a, 0x82, 0x71, 0x75] {
        // LDR, SDR, RDR, WDR
        let mut c = Case::new(opcode, 0x96, 15, 0);
        c.emit(0xffff, 2);
        c.write(0xffff, 0x801234, if opcode < 0x76 { 3 } else { 2 });
        c.write(
            0x1234,
            if matches!(opcode, 0x7a | 0x71) {
                0x96
            } else {
                0x69
            },
            1,
        );
        c.clocks = match opcode {
            0x71 => 11,
            0x75 => 16,
            _ => 8,
        };
        h.check(c, |c| {
            if matches!(opcode, 0x82 | 0x75) {
                c.write(0x1234, 0x96, 1);
            }
            if opcode == 0x75 {
                c.write(0xff, 2, 1);
            }
        });
    }
    for source_wrap in [false, true] {
        let mut c = Case::new(0x99, 0x69, 15, 0); // MRR
        let src = if source_wrap { 0xffff } else { 0x4500 };
        let dst = if source_wrap { 0x5600 } else { 0xffff };
        c.emit(src, 2);
        c.emit(dst, 2);
        c.write(src, 0x1234, 2);
        c.write(dst, 0x2345, 2);
        c.write(0x1234, 0x96, 1);
        c.write(0x2345, 0x69, 1);
        c.clocks = 15;
        h.check(c, |c| {
            c.write(0x2345, 0x96, 1);
            c.a = 0x96;
        });
    }
}
