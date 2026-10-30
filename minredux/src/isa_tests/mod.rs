//! Instruction-level reference tests, deliberately NOT a second microcode
//! interpreter. Results use byte/word arithmetic and addressing semantics;
//! timing comes from independently reviewed instruction-path tables.
//! The existing CSV/ROM test is complementary, not the semantic oracle.

mod arithmetic;
mod control;
mod data;
mod fixed_rom;
mod upstream_pr;

use super::*;

const NAMES: &str = "
NOP OUT INT INK WIN LL0 LL1 LL2 LL3 LL4 LL5 LL6 LL7 RL0 RL1 RL2
RL3 RL4 RL5 RL6 RL7 RR1 LR0 LR1 LR2 LR3 LR4 LR5 LR6 LR7 LLZ LLB
LLV LLW LLQ LLL LRZ LRB RLZ RLB RLV RLW RLQ RLL RRZ RRB NOT NOZ
NOB NOV NOW NOQ NEG NEZ NEB NEV NEW NEQ ANI ANZ ANB ANT ANR ZAN
BAN TAN RAN ORI ORZ ORB ORT ORR ZOR BOR TOR ROR XRI XRZ XRB XRT
XRR ZXR BXR TXR RXR FNE FEQ FCC FCS FPL FMI FGT FLE FPA BNE BEQ
BCC BCS BPL BMI BGT BLE JPA JPR JAR JPS JAS RTS PHS PLS LDS SDS
RDB RDR RAP RZP WDB WDR LDI LDZ LDB LDT LDR LAP LAB LZP LZB SDZ
SDB SDT SDR SZP MIZ MIB MIT MIR MIV MIW MZZ MZB MZT MZR MBZ MBB
MBT MBR MTZ MTB MTT MTR MRZ MRB MRT MRR MVV MWV CLD CLZ CLB CLV
CLW CLQ CLL CL5 INC INZ INB INV INW INQ DEC DEZ DEB DEV DEW DEQ
ADI ADZ ADB ADT ADR ZAD BAD TAD RAD ADV ADW ADQ AIZ AIB AIT AIR
AIV AIW AIQ AZZ AZT AZV AZQ ABB ABW ATZ ATT AVV SUI SUZ SUB SUT
SUR ZSU BSU TSU RSU SUV SUW SUQ SIZ SIB SIT SIR SIV SIW SIQ SZZ
SZT SZV SZQ SBB SBW STZ STT SVV CPI CPZ CPB CPT CPR CIZ CIB CIT
CIR CIV CIW CZZ CZT CBB CTZ CTT CVV ACI ACZ ZAC SCI SCZ ZSC ???";

#[derive(Clone, Copy, Debug)]
enum Mode {
    I,
    Z,
    B,
    T,
    R,
}
use Mode::*;

impl Mode {
    fn arg_bytes(self) -> usize {
        if matches!(self, B | R) { 2 } else { 1 }
    }
    fn read_clocks(self) -> u64 {
        match self {
            I => 1,
            Z => 2,
            B => 4,
            T => 5,
            R => 7,
        }
    }
}

struct Case {
    opcode: u8,
    start: u16,
    code: Vec<u8>,
    ram: Box<[u8; 0x10000]>,
    a: u8,
    initial_a: u8,
    initial_b: u8,
    fr: u8,
    initial_fr: u8,
    clocks: u64,
    pc: Option<u16>,
    check_a: bool,
    profile: usize,
    flash: Vec<(usize, u8)>,
    rx: Option<u8>,
    key: Option<u8>,
    output: Vec<u8>,
    /// Reviewed shipped-ROM defect: destination remains at this old value.
    /// Kept separate from the semantic expected RAM, never silently blessed.
    xor_erratum: Option<(u16, u8)>,
    fixed_rom: bool,
}

impl Case {
    fn new(opcode: u8, a: u8, flags: u8, profile: usize) -> Self {
        static RAM_PATTERN: std::sync::OnceLock<Box<[u8; 0x10000]>> = std::sync::OnceLock::new();
        let ram = RAM_PATTERN
            .get_or_init(|| {
                let mut ram = Box::new([0; 0x10000]);
                for (addr, byte) in ram.iter_mut().enumerate() {
                    let v = (addr as u32).wrapping_mul(0x9e3779b9);
                    *byte = (v ^ (v >> 11) ^ (v >> 19)) as u8;
                }
                ram
            })
            .clone();
        Self {
            opcode,
            start: [0x8000, 0x80ff, 0x81fe, 0x7fff][profile % 4],
            code: vec![opcode],
            ram,
            a,
            initial_a: a,
            initial_b: 0x39,
            fr: F_R | F_K | F_T | flags,
            initial_fr: F_R | F_K | F_T | flags,
            clocks: 0,
            pc: None,
            check_a: true,
            profile,
            flash: Vec::new(),
            rx: None,
            key: None,
            output: Vec::new(),
            xor_erratum: None,
            fixed_rom: false,
        }
    }

    fn emit(&mut self, value: u16, bytes: usize) {
        self.code.push(value as u8);
        if bytes == 2 {
            self.code.push((value >> 8) as u8);
        }
    }

    fn read(&self, addr: u16, width: usize) -> u32 {
        (0..width).fold(0, |v, i| {
            v | (self.ram[addr.wrapping_add(i as u16) as usize] as u32) << (8 * i)
        })
    }

    fn write(&mut self, addr: u16, value: u32, width: usize) {
        for i in 0..width {
            self.ram[addr.wrapping_add(i as u16) as usize] = (value >> (8 * i)) as u8;
        }
    }

    /// Install a value at a direct or indirect operand and encode the operand.
    /// Profiles cover xxFF, ffff->0000 and ZP-pointer-high-byte at 0100.
    fn operand(&mut self, mode: Mode, dest: bool, value: u32, width: usize) -> u16 {
        if matches!(mode, I) {
            self.emit(value as u16, width);
            return 0;
        }
        let p = self.profile % 4;
        let zp = if dest {
            [0x80, 0xfe, 0xfc, 0x80][p]
        } else {
            [0x40, 0xff, 0x40, 0x40][p]
        };
        let abs = if dest {
            [0x3400, 0x34ff, 0xffff, 0x3400][p]
        } else {
            [0x1200, 0x12ff, 0x1200, 0xffff][p]
        };
        let ptr = if dest {
            [0x30, 0xff, 0x30, 0x30][p]
        } else {
            [0x20, 0x20, 0xff, 0x20][p]
        };
        let rptr = if dest {
            [0x5600, 0x56ff, 0x5600, 0x56fe][p]
        } else {
            [0x4500, 0x45ff, 0x4500, 0x45fe][p]
        };
        let addr = match mode {
            Z => {
                self.emit(zp, mode.arg_bytes());
                zp
            }
            B => {
                self.emit(abs, mode.arg_bytes());
                abs
            }
            T => {
                self.emit(ptr, mode.arg_bytes());
                self.write(ptr, abs as u32, 2);
                abs
            }
            R => {
                self.emit(rptr, mode.arg_bytes());
                self.write(rptr, abs as u32, 2);
                abs
            }
            I => unreachable!(),
        };
        self.write(addr, value, width);
        addr
    }

    fn alu_flags(&mut self, result: u8, carry: bool) {
        self.fr = F_R
            | if self.rx.is_none() { F_T } else { 0 }
            | if self.key.is_none() { F_K } else { 0 }
            | byte_flags(result, carry);
    }
}

fn byte_flags(r: u8, carry: bool) -> u8 {
    (u8::from(carry) * F_C)
        | (u8::from(r >= 128) * F_N)
        | (u8::from(r & 15 == 0) * F_ZL)
        | (u8::from(r & 240 == 0) * F_ZH)
}

struct Harness {
    m: Machine,
    seen: [usize; 256],
    names: Vec<&'static str>,
    cases: usize,
    errata: [usize; 256],
    lengths: Vec<usize>,
    expected_flash: Vec<u8>,
    fixed_rom: bool,
}

impl Harness {
    fn new() -> Self {
        let source =
            include_str!("../../../minimal64/Revision 1.4 Redux/Support/Assembler/asm.cpp");
        let args = source
            .split("const std::vector<int> ARGS")
            .nth(1)
            .unwrap()
            .split('{')
            .nth(1)
            .unwrap()
            .split('}')
            .next()
            .unwrap();
        let lengths = args
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| {
                let n = u8::from_str_radix(s.strip_prefix("0x").unwrap(), 16).unwrap();
                1 + [n & 15, n >> 4]
                    .into_iter()
                    .map(|arg| match arg {
                        0 => 0,
                        3 => 2,
                        1 | 2 | 4 => 1,
                        _ => panic!("unknown argument type"),
                    })
                    .sum::<usize>()
            })
            .collect::<Vec<_>>();
        assert_eq!(lengths.len(), 256);
        Self {
            m: cpu(&[]),
            seen: [0; 256],
            names: NAMES.split_whitespace().collect(),
            cases: 0,
            errata: [0; 256],
            lengths,
            expected_flash: vec![0xff; 0x80000],
            fixed_rom: false,
        }
    }

    fn with_fixed_rom() -> Self {
        let mut h = Self::new();
        h.m.ctrl = ControlRom::from_images(&fixed_images()).unwrap();
        h.fixed_rom = true;
        h
    }

    fn check(&mut self, mut c: Case, expected: impl FnOnce(&mut Case)) {
        c.fixed_rom = self.fixed_rom;
        assert_eq!(
            c.code.len(),
            self.lengths[c.opcode as usize],
            "assembler operand length for {}",
            self.names[c.opcode as usize]
        );
        // Lay out instruction bytes last, exactly as fetching self-modifying RAM
        // would see them. Test fixtures avoid operands overlapping this code.
        for (i, &b) in c.code.iter().enumerate() {
            c.ram[c.start.wrapping_add(i as u16) as usize] = b;
        }
        self.m.ram.copy_from_slice(c.ram.as_slice());
        self.m.pc = c.start;
        self.m.mar = c.start;
        self.m.bank = 0xff;
        self.m.ar = c.initial_a;
        self.m.br = c.initial_b;
        self.m.ir = 0;
        self.m.sc = 0;
        self.m.fr = c.initial_fr;
        self.m.flags =
            F_R | if c.rx.is_none() { F_T } else { 0 } | if c.key.is_none() { F_K } else { 0 };
        self.m.uart_rx = c.rx.unwrap_or(0xff);
        self.m.ps2_reg = c.key.unwrap_or(0xff);
        self.m.uart_in.clear();
        self.m.ps2_in.clear();
        self.m.uart_out.clear();
        self.m.collect_output = true;
        self.m.uart_tx_busy = 0;
        self.m.uart_pace = 0;
        self.m.ps2_pace = 0;
        self.m.cycles = 0;
        self.m.flash_state = 0;
        self.m.flash_id = false;
        self.m.flash_operation = None;
        self.m.video = video::Video::default();
        self.m.flash.fill(0xff);
        self.expected_flash.fill(0xff);
        for &(addr, byte) in &c.flash {
            self.m.flash[addr] = byte;
            self.expected_flash[addr] = byte;
        }
        expected(&mut c);
        let limit = c.clocks.max(1) + 16;
        loop {
            self.m.step();
            // OUT's internal 0xff wait loop is not an instruction boundary.
            if self.m.sc == 0 && (c.opcode != 1 || self.m.ir != 0xff) {
                break;
            }
            assert!(
                self.m.cycles < limit,
                "{} failed to finish",
                self.names[c.opcode as usize]
            );
        }
        let label = format!(
            "{:02x} {} profile={} A={:02x} FR={:02x} code={:02x?}",
            c.opcode, self.names[c.opcode as usize], c.profile, c.initial_a, c.initial_fr, c.code
        );
        assert_eq!(self.m.cycles, c.clocks, "clocks: {label}");
        let pc = c.pc.unwrap_or(c.start.wrapping_add(c.code.len() as u16));
        assert_eq!(self.m.pc, pc, "PC: {label}");
        assert_eq!(self.m.mar, pc, "MAR: {label}");
        assert_eq!(self.m.bank, 0xff, "BANK: {label}");
        assert_eq!(
            self.m.ir,
            if c.opcode == 1 { 0 } else { c.opcode },
            "IR: {label}"
        );
        if c.check_a {
            assert_eq!(self.m.ar, c.a, "A: {label}");
        }
        assert_eq!(self.m.fr, c.fr, "FR: {label}");
        if let Some((addr, old)) = c.xor_erratum.filter(|_| !self.fixed_rom) {
            assert!(matches!(c.opcode, 0x52 | 0x54));
            assert_eq!(
                self.m.ram[addr as usize], old,
                "reviewed XOR ROM defect changed: {label}"
            );
            if c.ram[addr as usize] != old {
                self.errata[c.opcode as usize] += 1;
            }
            // Check the EXACT shipped behavior, including all other RAM bytes.
            c.ram[addr as usize] = old;
        }
        if self.m.ram.as_slice() != c.ram.as_slice() {
            let mismatches: Vec<_> = self
                .m
                .ram
                .iter()
                .zip(c.ram.iter())
                .enumerate()
                .filter(|(_, (a, b))| a != b)
                .take(12)
                .map(|(i, (a, b))| format!("{i:04x}: actual={a:02x} expected={b:02x}"))
                .collect();
            panic!("RAM: {label}: {}", mismatches.join(", "));
        }
        assert_eq!(self.m.uart_out, c.output, "UART output: {label}");
        assert!(
            self.m.flash == self.expected_flash,
            "unexpected FLASH mutation: {label}"
        );
        assert_eq!(self.m.uart_tx_busy, 0, "unexpected TX still busy: {label}");
        let rx = if matches!(c.opcode, 1 | 2) {
            None
        } else {
            c.rx
        };
        let key = if c.opcode == 3 { None } else { c.key };
        assert_eq!(
            self.m.uart_rx,
            rx.unwrap_or(0xff),
            "UART receive latch: {label}"
        );
        assert_eq!(
            self.m.ps2_reg,
            key.unwrap_or(0xff),
            "PS2 receive latch: {label}"
        );
        assert_eq!(
            self.m.flags & (F_T | F_K),
            if rx.is_none() { F_T } else { 0 } | if key.is_none() { F_K } else { 0 },
            "I/O ready flags: {label}"
        );
        self.seen[c.opcode as usize] += 1;
        self.cases += 1;
    }
}

fn fixed_images() -> Images {
    Images::load(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../roms/redux-1.4-isa-fixes-v1"
    ))
    .unwrap()
}

#[test]
fn all_public_opcodes_have_independent_semantic_and_clock_checks() {
    let mut h = Harness::new();
    arithmetic::check(&mut h);
    data::check(&mut h);
    control::check(&mut h);
    let missing: Vec<_> = (0..255)
        .filter(|&i| h.seen[i] == 0)
        .map(|i| h.names[i])
        .collect();
    assert!(missing.is_empty(), "unverified public opcodes: {missing:?}");
    eprintln!(
        "ISA semantic coverage: 255/255 public opcodes, {} cases",
        h.cases
    );
    eprintln!(
        "shipped XOR writeback errata: BXR={} RXR={} divergent cases",
        h.errata[0x52], h.errata[0x54]
    );
    assert!(
        h.errata[0x52] > 0 && h.errata[0x54] > 0,
        "known ROM errata were not exercised"
    );
    if std::env::var_os("MINREDUX_ISA_REPORT").is_some() {
        eprintln!("opcode\tmnemonic\tcases\tsemantic_divergences");
        for i in 0..255 {
            eprintln!("{i:02x}\t{}\t{}\t{}", h.names[i], h.seen[i], h.errata[i]);
        }
        eprintln!("ff\t(internal wait)\tseparate control::internal_ff_wait_state test\tN/A");
    }
}

#[test]
fn independent_opcode_catalog_matches_official_assembler() {
    let source = include_str!("../../../minimal64/Revision 1.4 Redux/Support/Assembler/asm.cpp");
    let table = source
        .split("MNEMONICS")
        .nth(1)
        .unwrap()
        .split('{')
        .nth(1)
        .unwrap()
        .split('}')
        .next()
        .unwrap();
    let names: Vec<_> = table
        .split('"')
        .enumerate()
        .filter(|(i, _)| i % 2 == 1)
        .map(|(_, s)| s)
        .collect();
    assert_eq!(NAMES.split_whitespace().collect::<Vec<_>>(), names);
    assert_eq!(names.len(), 256);
}

fn faulty_control(opcode: u8, step: usize, removed_signal: u32) -> Harness {
    let mut h = Harness::new();
    for flags in 0..128 {
        h.m.ctrl.words[(flags << 12) | ((opcode as usize) << 4) | step] &= !removed_signal;
    }
    h
}

// Mutation checks prove that the semantic oracle is not simply re-reading the
// same control words and blessing whatever the emulator does with them.
#[test]
#[should_panic(expected = "A:")]
fn oracle_rejects_broken_accumulator_result() {
    let mut h = faulty_control(0x76, 1, AI);
    let mut c = Case::new(0x76, 0x69, 15, 0);
    c.emit(0x96, 1);
    c.clocks = 2;
    h.check(c, |c| c.a = 0x96);
}

#[test]
#[should_panic(expected = "FR:")]
fn oracle_rejects_broken_flag_updates() {
    let mut h = faulty_control(0xb0, 2, FI);
    let mut c = Case::new(0xb0, 0xff, 15, 0);
    c.emit(1, 1);
    c.clocks = 3;
    h.check(c, |c| {
        c.a = 0;
        c.alu_flags(0, true);
    });
}

#[test]
#[should_panic(expected = "RAM:")]
fn oracle_rejects_missing_memory_write() {
    let mut h = faulty_control(0x7f, 2, RI);
    let mut c = Case::new(0x7f, 0x96, 15, 0);
    let dst = c.operand(Z, true, 0x69, 1);
    c.clocks = 3;
    h.check(c, |c| c.write(dst, 0x96, 1));
}

#[test]
#[should_panic(expected = "clocks:")]
fn oracle_rejects_wrong_instruction_length_in_clocks() {
    let mut h = faulty_control(0x76, 1, IC);
    let mut c = Case::new(0x76, 0x69, 15, 0);
    c.emit(0x96, 1);
    c.clocks = 2;
    h.check(c, |c| c.a = 0x96);
}
