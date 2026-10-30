//! Explicitly selected, separately saved fixed ROMs. The default/original ROM
//! tests and their known-erratum assertions remain unchanged.
use super::*;

#[test]
fn fixed_rom_passes_all_255_opcodes_without_semantic_exceptions() {
    let mut h = Harness::with_fixed_rom();
    arithmetic::check(&mut h);
    data::check(&mut h);
    control::check(&mut h);
    assert!(h.seen[..255].iter().all(|&count| count > 0));
    assert!(h.errata.iter().all(|&count| count == 0));
    assert_eq!(h.cases, 21_446);
    eprintln!(
        "fixed ROM: 255/255 public opcodes, {} cases, zero semantic exceptions",
        h.cases
    );
}

#[test]
fn fixed_rom_only_changes_reviewed_words_and_preserves_program_flash() {
    let original = images();
    let fixed = fixed_images();
    assert_eq!(fixed.flash, original.flash);
    let before = ControlRom::from_images(&original).unwrap();
    let after = ControlRom::from_images(&fixed).unwrap();
    let mut changed = 0;
    for (index, (&old, &new)) in before.words.iter().zip(after.words.iter()).enumerate() {
        if old == new {
            continue;
        }
        changed += 1;
        let flags = index >> 12;
        let opcode = (index >> 4) & 255;
        let step = index & 15;
        assert_ne!(flags & F_R as usize, 0);
        match (opcode, step) {
            (0x52, 5) | (0x54, 8) => {
                assert_eq!(old, MIL | MZ | MIH);
                assert_eq!(new, 0);
            }
            (0x52, 9) => assert_eq!(new, old | RI),
            (4, 1) => {
                assert_eq!(flags & (F_T | F_K) as usize, (F_T | F_K) as usize);
                assert_eq!(old, BI | FI);
                assert_eq!(new, BI);
            }
            _ => panic!("unreviewed ROM change: {index:05x}"),
        }
    }
    assert_eq!(changed, 208);
    assert_eq!(fixed.ctrl_msb, original.ctrl_msb);
}

#[test]
fn fixed_xor_writeback_is_exhaustive_and_preserves_scratch() {
    let images = fixed_images();
    let mut m = Machine::new(
        ControlRom::from_images(&images).unwrap(),
        vec![0xff; 0x80000],
    );
    for indirect in [false, true] {
        for a in 0..=255u8 {
            for b in 0..=255u8 {
                let addr = if b & 1 != 0 { 0x12ffu16 } else { 0x1234 };
                m.ram[addr as usize] = b;
                m.ram[addr as usize - 1] = 0xc3;
                m.ram[addr as usize + 1] = 0x3c;
                m.ram[0xff] = 0x5a;
                let code = if indirect {
                    let ptr = if a & 1 != 0 { 0xffffu16 } else { 0x45ff };
                    m.ram[ptr as usize] = addr as u8;
                    m.ram[ptr.wrapping_add(1) as usize] = (addr >> 8) as u8;
                    vec![0x54, ptr as u8, (ptr >> 8) as u8]
                } else {
                    vec![0x52, addr as u8, (addr >> 8) as u8]
                };
                assert_eq!(
                    execute(&mut m, 0x80ff, &code, a, 15),
                    if indirect { 13 } else { 10 }
                );
                assert_eq!(m.ar, a ^ b);
                assert_eq!(m.ram[addr as usize], a ^ b);
                assert_eq!(m.ram[0xff], 0x5a);
                assert_eq!(
                    (m.ram[addr as usize - 1], m.ram[addr as usize + 1]),
                    (0xc3, 0x3c)
                );
                assert_eq!(m.fr, F_R | 15);
            }
        }
    }
    // The scratch byte itself remains a valid destination.
    for indirect in [false, true] {
        m.ram[0xff] = 0xaa;
        let code = if indirect {
            m.ram[0x4500] = 0xff;
            m.ram[0x4501] = 0;
            vec![0x54, 0, 0x45]
        } else {
            vec![0x52, 0xff, 0]
        };
        execute(&mut m, 0x8000, &code, 0x55, 15);
        assert_eq!(m.ram[0xff], 0xff);
    }
}

#[test]
fn fixed_win_wakes_at_the_correct_pc_for_each_input_arrival_phase() {
    let images = fixed_images();
    let mut m = Machine::new(
        ControlRom::from_images(&images).unwrap(),
        vec![0xff; 0x80000],
    );
    let mut cases = 0;
    for high in [0u16, 1, 0x80, 0xff] {
        for low in [0u16, 0xfe, 0xff] {
            let start = (high << 8) | low;
            for a in [0u8, 1, 0xff] {
                for b in [0u8, 0xff] {
                    for keyboard in [false, true] {
                        for arrival in 0..32 {
                            m.ram[start as usize] = 4;
                            m.pc = start;
                            m.mar = start;
                            m.bank = 0xff;
                            m.ir = 0;
                            m.sc = 0;
                            m.ar = a;
                            m.br = b;
                            m.fr = F_R | F_T | F_K | 15;
                            m.flags = F_R | F_T | F_K;
                            m.cycles = 0;
                            m.uart_rx = 0xff;
                            m.ps2_reg = 0xff;
                            m.uart_in.clear();
                            m.ps2_in.clear();
                            m.uart_pace = 0;
                            m.ps2_pace = 0;
                            let mut exited = false;
                            for clock in 0..arrival + 20 {
                                if clock == arrival {
                                    if keyboard {
                                        m.feed_ps2([0x1c]);
                                    } else {
                                        m.feed_uart([0x61]);
                                    }
                                }
                                m.step();
                                if m.sc == 0 {
                                    if m.pc == start.wrapping_add(1) {
                                        assert!(clock >= arrival, "WIN returned before input");
                                        exited = true;
                                        break;
                                    }
                                    assert_eq!(
                                        m.pc, start,
                                        "bad WIN rewind: start={start:04x}, arrival={arrival}, clock={clock}"
                                    );
                                    assert_eq!(m.mar, start);
                                }
                            }
                            assert!(
                                exited,
                                "WIN failed to wake: start={start:04x}, arrival={arrival}"
                            );
                            assert_eq!(m.mar, start.wrapping_add(1));
                            if keyboard {
                                assert_eq!(m.ps2_reg, 0x1c);
                            } else {
                                assert_eq!(m.uart_rx, 0x61);
                            }
                            cases += 1;
                        }
                    }
                }
            }
        }
    }
    assert_eq!(cases, 4608);
}

#[test]
fn fixed_rom_boots_unmodified_minos() {
    let images = fixed_images();
    let mut m = Machine::new(ControlRom::from_images(&images).unwrap(), images.flash);
    m.run_cycles(400_000);
    assert!(m.text_screen().contains("READY."));
    assert_eq!(m.video.overwritten_writes, 0);
}

#[test]
fn generated_fixed_rom_bundle_is_reproducible_without_writing() {
    let status = std::process::Command::new("python3")
        .arg(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../roms/build_redux_isa_fixes.py"
        ))
        .arg("--check")
        .output()
        .expect("python3 is required to verify generated ROM artifacts");
    assert!(
        status.status.success(),
        "{}",
        String::from_utf8_lossy(&status.stderr)
    );
}
