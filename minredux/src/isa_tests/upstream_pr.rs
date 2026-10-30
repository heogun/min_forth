//! Opt-in validation of each independently submitted upstream PR's ROMs.
//! This reads only the explicit PR fixture directory; the default corrected
//! bundle and its assertions are untouched.
use super::*;

#[test]
#[ignore = "set MINREDUX_PR_ROM_DIR and MINREDUX_PR_FIX=xor|win"]
fn reviewed_upstream_rom_passes_matrix_and_targeted_regression() {
    let dir = std::env::var("MINREDUX_PR_ROM_DIR").unwrap();
    let fix = std::env::var("MINREDUX_PR_FIX").unwrap();
    assert!(matches!(fix.as_str(), "xor" | "win"));
    let selected = Images::load(dir).unwrap();
    let mut h = Harness::new();
    h.m.ctrl = ControlRom::from_images(&selected).unwrap();
    // Only the XOR branch removes the two independently checked XOR errata.
    h.fixed_rom = fix == "xor";
    arithmetic::check(&mut h);
    data::check(&mut h);
    control::check(&mut h);
    assert!(h.seen[..255].iter().all(|&n| n > 0));
    assert_eq!(h.cases, 21_446);
    if fix == "xor" {
        assert!(h.errata.iter().all(|&n| n == 0));
    } else {
        assert_eq!((h.errata[0x52], h.errata[0x54]), (7, 7));
    }
    eprintln!("{fix}: 255/255 public opcodes, 21446 independent cases");

    let mut m = Machine::new(
        ControlRom::from_images(&selected).unwrap(),
        vec![0xff; 0x80000],
    );
    if fix == "xor" {
        for indirect in [false, true] {
            for a in 0..=255u8 {
                for b in 0..=255u8 {
                    let dst = if b & 1 != 0 { 0x12ffu16 } else { 0x1234 };
                    m.ram[dst as usize] = b;
                    m.ram[0xff] = 0x5a;
                    let ptr = if a & 1 != 0 { 0xffffu16 } else { 0x45ff };
                    m.ram[ptr as usize] = dst as u8;
                    m.ram[ptr.wrapping_add(1) as usize] = (dst >> 8) as u8;
                    let arg = if indirect { ptr } else { dst };
                    let code = [
                        if indirect { 0x54 } else { 0x52 },
                        arg as u8,
                        (arg >> 8) as u8,
                    ];
                    assert_eq!(
                        execute(&mut m, 0x80ff, &code, a, 15),
                        if indirect { 13 } else { 10 }
                    );
                    assert_eq!(m.ram[dst as usize], a ^ b);
                    assert_eq!(m.ar, a ^ b);
                    assert_eq!(m.ram[0xff], 0x5a);
                    assert_eq!(m.fr, F_R | 15);
                }
            }
        }
        eprintln!("xor: 131072 operand pairs passed with production Rust core");
    } else {
        let mut count = 0;
        for high in [0u16, 1, 0x80, 0xff] {
            for low in [0u16, 0xfe, 0xff] {
                let start = high << 8 | low;
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
                                m.fr = F_R | F_K | F_T | 15;
                                m.flags = F_R | F_K | F_T;
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
                                            assert!(clock >= arrival);
                                            assert_eq!(m.mar, m.pc);
                                            exited = true;
                                            break;
                                        }
                                        assert_eq!((m.pc, m.mar), (start, start));
                                    }
                                }
                                assert!(exited);
                                if keyboard {
                                    assert_eq!(m.ps2_reg, 0x1c);
                                } else {
                                    assert_eq!(m.uart_rx, 0x61);
                                }
                                count += 1;
                            }
                        }
                    }
                }
            }
        }
        assert_eq!(count, 4608);
        eprintln!("win: 4608 readiness-phase cases passed with production Rust core");
    }
    let mut boot = Machine::new(ControlRom::from_images(&selected).unwrap(), selected.flash);
    boot.run_cycles(400_000);
    assert!(boot.text_screen().contains("READY."));
    eprintln!("{fix}: unmodified MinOS boot passed");
}
