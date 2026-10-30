use super::*;

#[path = "isa_tests/mod.rs"]
mod isa;

fn images() -> Images {
    Images::load(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../minimal64/Revision 1.4 Redux/FLASH Images"
    ))
    .unwrap()
}

fn cpu(code: &[u8]) -> Machine {
    let images = images();
    let ctrl = ControlRom::from_images(&images).unwrap();
    let mut flash = vec![0xff; 0x80000];
    flash[..code.len()].copy_from_slice(code);
    Machine::new(ctrl, flash)
}

fn flash_machine() -> Machine {
    Machine::new(
        ControlRom {
            words: vec![AO | RI; CTRL_ENTRIES],
        },
        vec![0xff; 0x80000],
    )
}

fn flash_write(m: &mut Machine, addr: usize, value: u8) {
    m.bank = (addr >> 12) as u8;
    m.memory_write((addr & 0xfff) as u16, value);
}

fn flash_read(m: &mut Machine, addr: usize) -> u8 {
    m.bank = (addr >> 12) as u8;
    m.memory_read((addr & 0xfff) as u16)
}

fn command(m: &mut Machine, value: u8, alias: usize) {
    flash_write(m, 0x5555 | alias, 0xaa);
    flash_write(m, 0x2aaa | alias, 0x55);
    flash_write(m, 0x5555 | alias, value);
}

fn finish_flash(m: &mut Machine) {
    while m.flash_busy_cycles() != 0 {
        m.tick_flash();
    }
}

#[test]
fn uart_is_seven_bit_in_both_directions() {
    let mut m = cpu(&[2, 0]); // INT
    m.flags |= F_T;
    m.feed_uart([0xe1]);
    m.run_cycles(3);
    assert_eq!(m.ar, 0x61);

    let mut m = cpu(&[1, 0]); // OUT
    m.ar = 0xe1;
    m.flags |= F_T;
    m.collect_output = true;
    m.run_cycles(6);
    assert!(m.uart_out.is_empty());
    m.run_cycles(160);
    assert_eq!(m.uart_out, [0x61]);
}

fn tick_inputs(m: &mut Machine, clocks: u64) {
    for _ in 0..clocks {
        m.service_io();
        m.cycles += 1;
    }
}

#[test]
fn timed_uart_delays_first_frame_and_drops_unread_frames() {
    let mut m = flash_machine();
    m.input_mode = InputMode::Timed;
    m.flags |= F_T;
    m.uart_after = 10;
    m.feed_uart([0xe1, 0x62, 0x63]);
    tick_inputs(&mut m, 169);
    assert_eq!(m.uart_rx, 0xff);
    tick_inputs(&mut m, 1);
    assert_eq!(m.uart_rx, 0x61);
    assert_eq!(m.flags & F_T, 0);
    tick_inputs(&mut m, 320);
    assert_eq!(m.uart_dropped, 2);
    assert!(!m.input_pending());
    assert_eq!(m.uart_rx, 0x61);
}

#[test]
fn buffered_input_preserves_unread_host_data() {
    let mut m = flash_machine();
    m.flags |= F_T;
    m.feed_uart([0x61, 0x62, 0x63]);
    tick_inputs(&mut m, 1000);
    assert_eq!(m.uart_in.len(), 2);
    assert_eq!(m.uart_rx, 0x61);
    assert_eq!(m.uart_dropped, 0);
    m.flags |= F_T;
    tick_inputs(&mut m, 1);
    assert_eq!(m.uart_rx, 0x62);
}

#[test]
fn timed_uart_half_duplex_collision_and_output_completion() {
    let mut m = cpu(&[1, 0]);
    m.input_mode = InputMode::Timed;
    m.flags |= F_T;
    m.ar = 0x41;
    m.collect_output = true;
    m.feed_uart([0x62]);
    m.run_cycles(6); // transmitter starts on the sixth clock
    assert!(m.uart_out.is_empty());
    m.run_cycles(159);
    assert!(m.uart_out.is_empty());
    assert_eq!(m.uart_dropped, 1);
    m.run_cycles(1);
    assert_eq!(m.uart_out, [0x41]);
}

#[test]
fn timed_ps2_waits_for_frame_and_keeps_only_one_latch() {
    let mut m = flash_machine();
    m.input_mode = InputMode::Timed;
    m.flags |= F_K;
    m.feed_ps2([0x1c, 0xf0]);
    tick_inputs(&mut m, 15_999);
    assert_eq!(m.ps2_reg, 0xff);
    tick_inputs(&mut m, 1);
    assert_eq!(m.ps2_reg, 0x1c);
    tick_inputs(&mut m, 16_000);
    assert_eq!(m.ps2_reg, 0x1c);
    assert_eq!(m.ps2_dropped, 1);
}

#[test]
fn flash_unlock_ignores_high_address_lines() {
    for alias in [0, 0x8000, 0x10000, 0x78000] {
        let mut m = flash_machine();
        command(&mut m, 0xa0, alias);
        flash_write(&mut m, 0x12345, 0x12);
        finish_flash(&mut m);
        assert_eq!(flash_read(&mut m, 0x12345), 0x12);
        assert_eq!(flash_read(&mut m, 0x12346), 0xff);
    }
}

#[test]
fn flash_chip_and_sector_erase() {
    let mut m = flash_machine();
    m.flash[0x12345] = 0x12;
    m.flash[0x13345] = 0x34;
    command(&mut m, 0x80, 0);
    flash_write(&mut m, 0x5555, 0xaa);
    flash_write(&mut m, 0x2aaa, 0x55);
    flash_write(&mut m, 0x12fff, 0x30);
    finish_flash(&mut m);
    assert_eq!(flash_read(&mut m, 0x12345), 0xff);
    assert_eq!(flash_read(&mut m, 0x13345), 0x34);

    command(&mut m, 0x80, 0x8000);
    flash_write(&mut m, 0xd555, 0xaa);
    flash_write(&mut m, 0xaaaa, 0x55);
    flash_write(&mut m, 0xd555, 0x10);
    finish_flash(&mut m);
    assert!(m.flash.iter().all(|&b| b == 0xff));
}

#[test]
fn flash_software_id_and_both_exit_sequences() {
    let mut m = flash_machine();
    for long_exit in [false, true] {
        command(&mut m, 0x90, 0x8000);
        assert_eq!(flash_read(&mut m, 0), 0xbf);
        assert_eq!(flash_read(&mut m, 1), 0xb7);
        if long_exit {
            command(&mut m, 0xf0, 0);
        } else {
            flash_write(&mut m, 0x1234, 0xf0);
        }
        assert_eq!(flash_read(&mut m, 0), 0xff);
    }
    command(&mut m, 0xa0, 0);
    flash_write(&mut m, 0, 0xf0); // program data, not an ID-exit command
    finish_flash(&mut m);
    assert_eq!(flash_read(&mut m, 0), 0xf0);
}

#[test]
fn flash_busy_polling_and_exact_completion() {
    let mut m = flash_machine();
    command(&mut m, 0xa0, 0);
    flash_write(&mut m, 0x12345, 0x12);
    assert_eq!(m.flash_busy_cycles(), 112);
    let a = flash_read(&mut m, 0x12345);
    let b = flash_read(&mut m, 0x12345);
    assert_eq!(a & 0x80, 0x80); // complement of data DQ7
    assert_eq!((a ^ b) & 0x40, 0x40);
    assert_eq!(m.flash[0x12345], 0xff);
    command(&mut m, 0x90, 0); // ignored while busy
    flash_write(&mut m, 0, 0xf0); // also cannot abort an internal operation
    for _ in 0..111 {
        m.tick_flash();
    }
    assert_eq!(m.flash_busy_cycles(), 1);
    assert_eq!(m.flash[0x12345], 0xff);
    m.tick_flash();
    assert_eq!(flash_read(&mut m, 0x12345), 0x12);
    assert!(!m.flash_id);
    assert_eq!(flash_read(&mut m, 0), 0xff);
}

#[test]
fn flash_erase_busy_status_and_reset_independence() {
    let mut m = flash_machine();
    m.flash[0x12345] = 0;
    command(&mut m, 0x80, 0);
    flash_write(&mut m, 0x5555, 0xaa);
    flash_write(&mut m, 0x2aaa, 0x55);
    flash_write(&mut m, 0x12345, 0x30);
    assert_eq!(m.flash_busy_cycles(), 144_000);
    assert_eq!(flash_read(&mut m, 0x12345) & 0x80, 0);
    m.reset();
    assert_eq!(m.flash_busy_cycles(), 144_000);
    finish_flash(&mut m);
    assert_eq!(flash_read(&mut m, 0x12345), 0xff);
    command(&mut m, 0x80, 0);
    flash_write(&mut m, 0x5555, 0xaa);
    flash_write(&mut m, 0x2aaa, 0x55);
    flash_write(&mut m, 0x5555, 0x10);
    assert_eq!(m.flash_busy_cycles(), 560_000);
}

fn execute(m: &mut Machine, pc: u16, code: &[u8], a: u8, flags: u8) -> u64 {
    for (i, &byte) in code.iter().enumerate() {
        m.ram[pc.wrapping_add(i as u16) as usize] = byte;
    }
    m.pc = pc;
    m.mar = pc;
    m.bank = 0xff;
    m.sc = 0;
    m.ar = a;
    m.fr = F_R | flags;
    let start = m.cycles;
    loop {
        m.step();
        if m.sc == 0 {
            break;
        }
        assert!(m.cycles - start < 1024, "instruction did not terminate");
    }
    m.cycles - start
}

#[test]
fn shipped_control_rom_matches_all_csv_entries() {
    use std::collections::BTreeMap;
    let bits = [
        BO, EC, ES, EO, IC, II, FI, IO, MC, CIH, CE, BI, AI, AO, COH, COL, MIL, MIH, ME, CIL, MZ,
        RO, NI, RI,
    ];
    let names = [
        "BO", "EC", "ES", "EO", "IC", "II", "FI", "IO", "MC", "CIH", "CE", "BI", "AI", "AO", "COH",
        "COL", "MIL", "MIH", "ME", "CIL", "MZ", "RO", "NI", "RI",
    ];
    let signals: BTreeMap<_, _> = names.into_iter().zip(bits).collect();
    let defs = include_str!("../../minimal64/Revision 1.4 Redux/microcode_def.csv");
    let mut words = BTreeMap::new();
    for line in defs.lines().filter_map(|l| l.strip_prefix("#define ")) {
        let (name, body) = line.split_once(' ').unwrap();
        let row: Vec<u32> = body
            .split(',')
            .map(|w| {
                w.trim()
                    .split('|')
                    .map(|s| match s {
                        "0" | "FF" => 0,
                        _ => *signals.get(s).unwrap(),
                    })
                    .fold(0, |a, b| a | b)
            })
            .collect();
        assert_eq!(row.len(), 16, "{name}");
        words.insert(name, row);
    }
    let ctrl = ControlRom::from_images(&images()).unwrap();
    let mapping = include_str!("../../minimal64/Revision 1.4 Redux/microcode_rom.csv");
    let mut checked = 0;
    for (fr, line) in mapping.lines().enumerate() {
        let (_, row) = line.split_once("*/").unwrap();
        let row: Vec<_> = row
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .collect();
        assert_eq!(row.len(), 256);
        for (ir, name) in row.iter().enumerate() {
            for (sc, &expected) in words[name].iter().enumerate() {
                assert_eq!(
                    ctrl.words[(fr << 12) | (ir << 4) | sc],
                    expected,
                    "FR={fr:02x} IR={ir:02x} SC={sc} {name}"
                );
                checked += 1;
            }
        }
    }
    assert_eq!(checked, CTRL_ENTRIES);
}

#[test]
fn exhaustive_immediate_arithmetic_results_flags_and_cycles() {
    let mut m = cpu(&[0]);
    for (opcode, compare, subtract, with_carry) in [
        (0xb0, false, false, false), // ADI
        (0xcc, false, true, false),  // SUI
        (0xe8, true, true, false),   // CPI
        (0xf9, false, false, true),  // ACI
        (0xfc, false, true, true),   // SCI
    ] {
        for carry in 0..=u8::from(with_carry) {
            for a in 0..=255u16 {
                for b in 0..=255u16 {
                    let cin = if with_carry {
                        carry as u16
                    } else {
                        u16::from(subtract)
                    };
                    let sum = if subtract {
                        a + (255 - b) + cin
                    } else {
                        a + b + cin
                    };
                    let r = sum as u8;
                    assert_eq!(
                        execute(&mut m, 0x8000, &[opcode, b as u8], a as u8, carry * F_C),
                        3
                    );
                    assert_eq!(m.ar, if compare { a as u8 } else { r });
                    let expected = if sum > 255 { F_C } else { 0 }
                        | if r & 128 != 0 { F_N } else { 0 }
                        | if r & 15 == 0 { F_ZL } else { 0 }
                        | if r & 240 == 0 { F_ZH } else { 0 };
                    assert_eq!(
                        m.fr & 15,
                        expected,
                        "op={opcode:02x} a={a} b={b} carry={carry}"
                    );
                    assert_eq!(m.pc, 0x8002);
                    assert_eq!(m.mar, m.pc);
                }
            }
        }
    }
}

#[test]
fn conditional_branches_and_operand_fetch_page() {
    let mut m = cpu(&[0]);
    for f in 0..16 {
        let z = f & (F_ZL | F_ZH) == F_ZL | F_ZH;
        let c = f & F_C != 0;
        let n = f & F_N != 0;
        let taken = [!z, z, !c, c, !n, n, c && !z, !c || z];
        for (i, take) in taken.into_iter().enumerate() {
            // Opcode at xxFF: the target page comes from the operand fetch.
            assert_eq!(execute(&mut m, 0x80ff, &[0x55 + i as u8, 0x42], 0, f), 2);
            assert_eq!(m.pc, if take { 0x8142 } else { 0x8101 });
            assert_eq!(m.mar, m.pc);
            assert_eq!(
                execute(&mut m, 0x80ff, &[0x5e + i as u8, 0x42, 0x93], 0, f),
                if take { 4 } else { 3 }
            );
            assert_eq!(m.pc, if take { 0x9342 } else { 0x8102 });
            assert_eq!(m.mar, m.pc);
        }
    }
}

#[test]
fn loads_indirection_and_indexed_page_crossing() {
    let mut m = cpu(&[0]);
    m.ram[0x1234] = 0x9a;
    m.ram[0x20] = 0x34;
    m.ram[0x21] = 0x12;
    assert_eq!(execute(&mut m, 0x80ff, &[0x76, 0xab], 0, 0), 2);
    assert_eq!(m.ar, 0xab);
    assert_eq!(execute(&mut m, 0x8000, &[0x78, 0x34, 0x12], 0, 0), 5);
    assert_eq!(m.ar, 0x9a);
    assert_eq!(execute(&mut m, 0x8000, &[0x79, 0x20], 0, 0), 6);
    assert_eq!(m.ar, 0x9a);
    for (index, clocks) in [(0, 7), (1, 9)] {
        m.ram[0x12ff] = 0x34;
        m.ram[0x1300] = 0x56;
        m.ram[0x1301] = 0x78;
        assert_eq!(
            execute(&mut m, 0x8000, &[0x68, 0xff, 0x12], index, 0),
            clocks
        );
        assert_eq!(m.pc, if index == 0 { 0x5634 } else { 0x7856 });
        assert_eq!(m.mar, m.pc);
    }
}

#[test]
fn stack_wrap_and_subroutine_return_across_page() {
    let mut m = cpu(&[0]);
    for sp in [0xfe, 0, 1] {
        m.ram[0xffff] = sp;
        assert_eq!(execute(&mut m, 0x8000, &[0x6c], 0xa5, 0), 8); // PHS
        assert_eq!(m.ram[0xffff], sp.wrapping_sub(1));
        assert_eq!(m.ar, 0xa5);
        assert_eq!(execute(&mut m, 0x8001, &[0x6d], 0, 0), 6); // PLS
        assert_eq!(m.ram[0xffff], sp);
        // SP=0 wraps to 0xffff: the stack-pointer byte aliases data on real hardware.
        if sp != 0 {
            assert_eq!(m.ar, 0xa5);
        }
    }
    m.ram[0xffff] = 0xfe;
    assert_eq!(execute(&mut m, 0x80ff, &[0x69, 0, 0x90], 0x55, 0), 11);
    assert_eq!(m.pc, 0x9000);
    assert_eq!(m.ram[0xffff], 0xfc);
    assert_eq!(execute(&mut m, 0x9000, &[0x6b], 0, 0), 10);
    assert_eq!(m.pc, 0x8102);
    assert_eq!(m.mar, m.pc);
    assert_eq!(m.ram[0xffff], 0xfe);
}

#[test]
fn reset_only_clears_wired_counters_and_samples_reset_pin() {
    let mut m = cpu(&[0]);
    m.ar = 0x12;
    m.br = 0x34;
    m.ir = 0x56;
    m.fr = F_R | F_C;
    m.ram[0x1234] = 0xab;
    m.uart_rx = 0x61;
    m.uart_tx_busy = 100;
    m.cycles = 77;
    m.pc = 0x1234;
    m.mar = 0x5678;
    m.bank = 0xff;
    m.sc = 5;
    m.reset();
    assert_eq!((m.pc, m.mar, m.bank, m.sc), (0, 0, 0, 0));
    assert_eq!((m.ar, m.br, m.ir, m.fr), (0x12, 0x34, 0x56, F_R | F_C));
    assert_eq!(m.cycles, 77);
    assert_eq!(m.ram[0x1234], 0xab);
    assert_eq!(m.uart_status(), (0, 0x61, 100));
    m.set_reset(true);
    m.step();
    assert_eq!((m.pc, m.mar, m.bank, m.sc), (0, 0, 0, 0));
    assert_eq!(m.flags & F_R, 0);
    m.set_reset(false);
    assert_ne!(m.flags & F_R, 0);
}

#[test]
fn mar_captures_pre_edge_pc_not_updated_pc() {
    let mut m = Machine::new(
        ControlRom {
            words: vec![CE | MC | MIL | MIH; CTRL_ENTRIES],
        },
        vec![],
    );
    m.pc = 0x12ff;
    m.step();
    assert_eq!(m.pc, 0x1300);
    assert_eq!(m.mar, 0x12ff);
}

#[test]
fn video_is_distinct_from_cpu_ram_and_survives_cpu_reset() {
    let mut m = flash_machine();
    m.bank = 0xff;
    m.memory_write(0x430c, 0xa5);
    assert_eq!(m.peek_ram(0x430c), 0xa5);
    assert_eq!(m.video.vram()[0x30c], 0);
    tick_inputs(&mut m, 2);
    assert_eq!(m.video.vram()[0x30c], 0xa5);
    m.reset();
    assert_eq!(m.video.vram()[0x30c], 0xa5);
    // FLASH mapping disables CPU RAM, but does not disable the VREG write pulse.
    m.bank = 0;
    m.memory_write(0x430c, 0x5a);
    assert_eq!(m.peek_ram(0x430c), 0xa5);
    tick_inputs(&mut m, 1);
    assert_eq!(m.video.vram()[0x30c], 0x5a);
}

#[test]
fn reference_minos_boot_and_video_mirror_agree() {
    let images = images();
    let ctrl = ControlRom::from_images(&images).unwrap();
    let mut m = Machine::new(ctrl, images.flash);
    m.run_cycles(400_000);
    assert!(m.text_screen().contains("READY."));
    assert_eq!(m.bank, 0xff);
    assert_eq!(m.video.overwritten_writes, 0);
    assert_eq!(m.video.vram().as_slice(), &m.ram()[0x4000..0x8000]);
    assert_eq!(m.video.frames, 400_000 / video::FRAME_CPU_CYCLES);
}

#[test]
fn minos_save_and_load_with_flash_busy_polling() {
    let images = images();
    let ctrl = ControlRom::from_images(&images).unwrap();
    let mut m = Machine::new(ctrl, images.flash);
    m.run_cycles(400_000);
    m.ram[0x1000] = 0x6b; // RTS: MinOS loads AND executes a file named as a command
    m.feed_uart(b"save 1000 1000 audit\n".iter().copied());
    m.run_cycles(3_000_000);
    assert!(!m.input_pending());
    assert_eq!(m.flash_busy_cycles(), 0);
    m.ram[0x1000] = 0;
    m.feed_uart(b"audit\n".iter().copied());
    m.run_cycles(2_000_000);
    assert_eq!(m.ram[0x1000], 0x6b);
    assert_eq!(m.video.overwritten_writes, 0);
}
