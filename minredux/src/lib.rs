//! Microcode-driven emulator for the Minimal 64x4 Revision 1.4 "Redux".
//! CPU clocks, digital VGA and FLASH busy timing are modelled; serial input
//! offers buffered and frame-timed modes. See README.md for fidelity limits.
//!
//! The CPU is a microcoded machine: three 512 KiB control ROMs produce a
//! 24-bit control word for every combination of the 7-bit flag register,
//! the 8-bit instruction register and the 4-bit step counter.  This crate
//! executes that microcode one clock at a time, using the physical
//! control-signal bit assignment of the Redux board.
//!
//! Redux control-word bit assignment (decoded from the shipped ROM images
//! and `microcode_def.csv`, verified against the well-known fetch word
//! `RO|II|CE|ME`):
//!
//! ```text
//!  0 BO    1 EC    2 ES    3 EO    4 IC    5 II    6 FI    7 IO
//!  8 MC    9 CIH  10 CE   11 BI   12 AI   13 AO   14 COH  15 COL
//! 16 MIL  17 MIH  18 ME   19 CIL  20 MZ   21 RO   22 NI   23 RI
//! ```
//!
//! The stored ROM words are active-low for some signals.  XORing the raw
//! 24-bit word with `0xEBFAF9` yields the active-high logical word.
//!
//! The original Revision 1.1 had a single ALU zero flag.  Redux derives two
//! nibble-zero flags (ZL, ZH) from a 74HC4002; equality is "ZL && ZH".
//! The 7-bit flag register is laid out as `R K T N C ZH ZL`.

use std::cell::Cell;
use std::collections::VecDeque;
use std::fs;
use std::io;
use std::path::Path;

pub mod pacing;
pub mod video;

pub const CTRL_INVERT_MASK: u32 = 0x00EB_FAF9;
pub const CTRL_ENTRIES: usize = 0x80000;

// Logical control signals.
pub const BO: u32 = 1 << 0;
pub const EC: u32 = 1 << 1;
pub const ES: u32 = 1 << 2;
pub const EO: u32 = 1 << 3;
pub const IC: u32 = 1 << 4;
pub const II: u32 = 1 << 5;
pub const FI: u32 = 1 << 6;
pub const IO: u32 = 1 << 7;
pub const MC: u32 = 1 << 8;
pub const CIH: u32 = 1 << 9;
pub const CE: u32 = 1 << 10;
pub const BI: u32 = 1 << 11;
pub const AI: u32 = 1 << 12;
pub const AO: u32 = 1 << 13;
pub const COH: u32 = 1 << 14;
pub const COL: u32 = 1 << 15;
pub const MIL: u32 = 1 << 16;
pub const MIH: u32 = 1 << 17;
pub const ME: u32 = 1 << 18;
pub const CIL: u32 = 1 << 19;
pub const MZ: u32 = 1 << 20;
pub const RO: u32 = 1 << 21;
pub const NI: u32 = 1 << 22;
pub const RI: u32 = 1 << 23;

// Flag-register bits, as printed in `microcode_rom.csv`: `rktnczz`.
pub const F_ZL: u8 = 1 << 0;
pub const F_ZH: u8 = 1 << 1;
pub const F_C: u8 = 1 << 2;
pub const F_N: u8 = 1 << 3;
pub const F_T: u8 = 1 << 4;
pub const F_K: u8 = 1 << 5;
pub const F_R: u8 = 1 << 6;

/// UART transmitter is busy for this many CPU clocks after an `OUT`.
pub const UART_TX_CYCLES: u16 = 160;
/// 500 kbit/s: 1 start + 7 data + 2 stop bits, 16 CPU clocks per bit.
pub const UART_FRAME_CYCLES: u32 = 160;
pub const UART_RX_PACE: u32 = UART_FRAME_CYCLES;
/// Default pacing of a PS/2 scancode (2 ms at 8 MHz).
pub const PS2_RX_PACE: u32 = 16000;

/// Buffered input is a lossless host-side test helper, not a physical wire.
/// Timed input sends complete frames independently of CPU reads; collisions
/// and full receive latches discard frames. Bit-level malformed frames and
/// mid-frame resynchronization are outside this frame-level digital model.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum InputMode {
    #[default]
    Buffered,
    Timed,
}

struct InputFrame {
    byte: u8,
    remaining: u32,
    blocked: bool,
}

/// SST39SF040 typical internal operation times at 8 MHz, not measured bounds.
/// Configure these for a particular part; internal FLASH timing is asynchronous.
#[derive(Clone, Copy, Debug)]
pub struct FlashTiming {
    pub program: u64,
    pub sector_erase: u64,
    pub chip_erase: u64,
}

impl Default for FlashTiming {
    fn default() -> Self {
        Self {
            program: 112,
            sector_erase: 144_000,
            chip_erase: 560_000,
        }
    }
}

enum FlashAction {
    Program(usize, u8),
    SectorErase(usize),
    ChipErase,
}

struct FlashOperation {
    remaining: u64,
    action: FlashAction,
}

/// All ROM/RAM images required by the machine.
pub struct Images {
    pub flash: Vec<u8>,
    pub ctrl_lsb: Vec<u8>,
    pub ctrl_msb: Vec<u8>,
    pub ctrl_hsb: Vec<u8>,
}

impl Images {
    /// Load the four images from a directory containing
    /// `flash.bin`, `ctrl_lsb.bin`, `ctrl_msb.bin`, `ctrl_hsb.bin`.
    pub fn load<P: AsRef<Path>>(dir: P) -> io::Result<Self> {
        let dir = dir.as_ref();
        Ok(Self {
            flash: fs::read(dir.join("flash.bin"))?,
            ctrl_lsb: fs::read(dir.join("ctrl_lsb.bin"))?,
            ctrl_msb: fs::read(dir.join("ctrl_msb.bin"))?,
            ctrl_hsb: fs::read(dir.join("ctrl_hsb.bin"))?,
        })
    }

    pub fn flash_image_path<P: AsRef<Path>>(dir: P) -> std::path::PathBuf {
        dir.as_ref().join("flash.bin")
    }
}

/// Predecoded control ROM: one active-high 24-bit word per
/// `(FR << 12) | (IR << 4) | SC`.
pub struct ControlRom {
    pub words: Vec<u32>,
}

impl ControlRom {
    pub fn from_images(images: &Images) -> io::Result<Self> {
        let n = images.ctrl_lsb.len();
        if images.ctrl_msb.len() != n || images.ctrl_hsb.len() != n {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "control ROM images have different sizes",
            ));
        }
        if n < CTRL_ENTRIES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("control ROM too small: {n} bytes, need {CTRL_ENTRIES}"),
            ));
        }
        let mut words = Vec::with_capacity(CTRL_ENTRIES);
        for i in 0..CTRL_ENTRIES {
            let raw = images.ctrl_lsb[i] as u32
                | ((images.ctrl_msb[i] as u32) << 8)
                | ((images.ctrl_hsb[i] as u32) << 16);
            words.push(raw ^ CTRL_INVERT_MASK);
        }
        Ok(Self { words })
    }
}

/// The complete Redux machine: CPU, RAM, FLASH, UART and PS/2.
pub struct Machine {
    ram: Box<[u8; 0x10000]>,
    flash: Vec<u8>,
    ctrl: ControlRom,
    pub video: video::Video,

    // CPU registers.
    pub pc: u16,
    pub mar: u16,
    pub bank: u8,
    pub ar: u8,
    pub br: u8,
    pub ir: u8,
    pub sc: u8,
    /// Flag register (7 bits) used to index the control ROM.
    pub fr: u8,
    /// Internal ALU/IO flag latches, sampled into `fr` by `FI`.
    pub flags: u8,

    // FLASH programming state machine.
    flash_state: u8,
    flash_id: bool,
    flash_operation: Option<FlashOperation>,
    flash_toggle: Cell<bool>,
    pub flash_timing: FlashTiming,

    // UART.
    uart_rx: u8,
    uart_tx_busy: u16,
    uart_tx_data: u8,
    /// Bytes waiting to be delivered to the UART receiver.
    pub uart_in: VecDeque<u8>,
    uart_pace: u32,
    /// Do not deliver UART input before this cycle count.
    pub uart_after: u64,
    /// Set before running/feeding input; changing mode during a frame is unsupported.
    pub input_mode: InputMode,
    uart_frame: Option<InputFrame>,
    ps2_frame: Option<InputFrame>,
    /// Frame duration is device-dependent; default is a nominal 2 ms.
    pub ps2_frame_cycles: u32,
    pub uart_dropped: u64,
    pub ps2_dropped: u64,
    /// Bytes the CPU has transmitted.
    pub uart_out: Vec<u8>,
    pub collect_output: bool,

    // PS/2.
    ps2_reg: u8,
    pub ps2_in: VecDeque<u8>,
    ps2_pace: u32,

    pub cycles: u64,
    pub halted: bool,
    pub trace_io: bool,
    pub io_events: Vec<(u64, char, u8)>,
    reset_asserted: bool,
}

impl Machine {
    pub fn new(ctrl: ControlRom, flash: Vec<u8>) -> Self {
        let mut flash = flash;
        if flash.len() < 0x80000 {
            flash.resize(0x80000, 0xff);
        }
        let mut m = Self {
            ram: Box::new([0u8; 0x10000]),
            flash,
            ctrl,
            video: video::Video::default(),
            pc: 0,
            mar: 0,
            bank: 0,
            ar: 0,
            br: 0,
            ir: 0,
            sc: 0,
            fr: F_R,
            flags: F_R,
            flash_state: 0,
            flash_id: false,
            flash_operation: None,
            flash_toggle: Cell::new(false),
            flash_timing: FlashTiming::default(),
            uart_rx: 0xff,
            uart_tx_busy: 0,
            uart_tx_data: 0x7f,
            uart_in: VecDeque::new(),
            uart_pace: 0,
            uart_after: 0,
            input_mode: InputMode::Buffered,
            uart_frame: None,
            ps2_frame: None,
            ps2_frame_cycles: PS2_RX_PACE,
            uart_dropped: 0,
            ps2_dropped: 0,
            uart_out: Vec::new(),
            collect_output: false,
            ps2_reg: 0xff,
            ps2_in: VecDeque::new(),
            ps2_pace: 0,
            cycles: 0,
            halted: false,
            trace_io: false,
            io_events: Vec::new(),
            reset_asserted: false,
        };
        m.reset();
        m
    }

    /// Pulse the CPU reset input without advancing time. Only the counters
    /// wired to RESET are cleared; RAM, A/B/IR/FR and peripherals are retained.
    /// Use `set_reset` and `step` to model a reset held across clock edges.
    pub fn reset(&mut self) {
        self.set_reset(true);
        self.set_reset(false);
    }

    pub fn set_reset(&mut self, asserted: bool) {
        self.reset_asserted = asserted;
        if asserted {
            self.flags &= !F_R;
            self.clear_reset_counters();
        } else {
            self.flags |= F_R;
        }
    }

    fn clear_reset_counters(&mut self) {
        self.pc = 0;
        self.mar = 0;
        self.bank = 0;
        self.sc = 0;
        // CPU reset does not reset the independently powered FLASH chip.
        self.halted = false;
    }

    #[inline(always)]
    pub fn memory_read(&self, addr: u16) -> u8 {
        if (addr & 0x8000) != 0 || (self.bank & 0x80) != 0 {
            self.ram[addr as usize]
        } else {
            let idx = ((self.bank as usize) << 12) | ((addr as usize) & 0x0fff);
            if let Some(op) = &self.flash_operation {
                let dq7 = match op.action {
                    FlashAction::Program(_, data) => (!data) & 0x80,
                    _ => 0,
                };
                let toggle = !self.flash_toggle.get();
                self.flash_toggle.set(toggle);
                (self.flash[idx] & 0x3f) | dq7 | if toggle { 0x40 } else { 0 }
            } else if self.flash_id {
                match idx {
                    0 => 0xbf,
                    1 => 0xb7,
                    _ => 0xff,
                }
            } else {
                self.flash[idx]
            }
        }
    }

    #[inline(always)]
    fn memory_write(&mut self, addr: u16, value: u8) {
        // VREG observes the write pulse independently of the system RAM bank.
        self.video.capture_write(addr, value);
        if (addr & 0x8000) != 0 || (self.bank & 0x80) != 0 {
            self.ram[addr as usize] = value;
            return;
        }
        let adr = ((self.bank as usize) << 12) | ((addr as usize) & 0x0fff);
        if self.flash_operation.is_some() {
            return; // all command writes are ignored during internal programming/erase
        }
        // Command addresses decode A14..A0; A18..A15 are don't-care.
        let cmd_addr = adr & 0x7fff;
        if value == 0xf0 && self.flash_state != 3 {
            self.flash_id = false;
            self.flash_state = 0;
            return;
        }
        match self.flash_state {
            0 => {
                self.flash_state = if cmd_addr == 0x5555 && value == 0xaa {
                    1
                } else {
                    0
                };
            }
            1 => {
                self.flash_state = if cmd_addr == 0x2aaa && value == 0x55 {
                    2
                } else {
                    0
                };
            }
            2 => {
                if cmd_addr == 0x5555 && value == 0xa0 && !self.flash_id {
                    self.flash_state = 3;
                } else if cmd_addr == 0x5555 && value == 0x80 && !self.flash_id {
                    self.flash_state = 4;
                } else if cmd_addr == 0x5555 && value == 0x90 {
                    self.flash_id = true;
                    self.flash_state = 0;
                } else {
                    self.flash_state = 0;
                }
            }
            3 => {
                self.begin_flash(FlashAction::Program(adr, value), self.flash_timing.program);
                self.flash_state = 0;
            }
            4 => {
                self.flash_state = if cmd_addr == 0x5555 && value == 0xaa {
                    5
                } else {
                    0
                };
            }
            5 => {
                self.flash_state = if cmd_addr == 0x2aaa && value == 0x55 {
                    6
                } else {
                    0
                };
            }
            6 => {
                if value == 0x30 {
                    let base = (self.bank as usize) << 12;
                    self.begin_flash(
                        FlashAction::SectorErase(base),
                        self.flash_timing.sector_erase,
                    );
                } else if cmd_addr == 0x5555 && value == 0x10 {
                    self.begin_flash(FlashAction::ChipErase, self.flash_timing.chip_erase);
                }
                self.flash_state = 0;
            }
            _ => self.flash_state = 0,
        }
    }

    fn begin_flash(&mut self, action: FlashAction, clocks: u64) {
        self.flash_toggle.set(false);
        self.flash_operation = Some(FlashOperation {
            action,
            remaining: clocks.max(1),
        });
    }

    pub fn flash_busy_cycles(&self) -> u64 {
        self.flash_operation.as_ref().map_or(0, |op| op.remaining)
    }

    fn tick_flash(&mut self) {
        if let Some(op) = &mut self.flash_operation {
            op.remaining -= 1;
            if op.remaining != 0 {
                return;
            }
        } else {
            return;
        }
        match self.flash_operation.take().unwrap().action {
            FlashAction::Program(addr, value) => self.flash[addr] &= value,
            FlashAction::SectorErase(base) => self.flash[base..base + 0x1000].fill(0xff),
            FlashAction::ChipErase => self.flash.fill(0xff),
        }
    }

    /// Queue a byte for the UART receiver (as if it arrived from the host).
    pub fn feed_uart(&mut self, bytes: impl IntoIterator<Item = u8>) {
        self.uart_in.extend(bytes);
    }

    /// Queue PS/2 scancodes (as if typed on the keyboard).
    pub fn feed_ps2(&mut self, bytes: impl IntoIterator<Item = u8>) {
        self.ps2_in.extend(bytes);
    }

    #[inline(always)]
    fn service_io(&mut self) {
        self.tick_flash();
        self.video.tick();
        // A transmitted byte becomes externally visible only at frame completion.
        if self.uart_tx_busy > 0 {
            self.uart_tx_busy -= 1;
            if self.uart_tx_busy == 0 {
                self.flags &= !F_T;
                if self.collect_output {
                    self.uart_out.push(self.uart_tx_data);
                }
            }
        }
        if self.input_mode == InputMode::Timed {
            self.service_timed_input();
            return;
        }
        // Deliver one UART byte when the receiver is idle.
        if self.uart_pace > 0 {
            self.uart_pace -= 1;
        }
        if self.uart_pace == 0
            && !self.uart_in.is_empty()
            && self.cycles >= self.uart_after
            && (self.flags & F_T) != 0
            && self.uart_tx_busy == 0
        {
            let b = self.uart_in.pop_front().unwrap();
            if self.trace_io {
                self.io_events.push((self.cycles, 'D', b & 0x7f));
            }
            self.uart_rx = b & 0x7f;
            self.flags &= !F_T;
            self.uart_pace = UART_RX_PACE;
        }

        // Deliver one PS/2 scancode when the keyboard register is empty.
        if self.ps2_pace > 0 {
            self.ps2_pace -= 1;
        }
        if self.ps2_pace == 0 && !self.ps2_in.is_empty() && (self.flags & F_K) != 0 {
            self.ps2_reg = self.ps2_in.pop_front().unwrap();
            self.flags &= !F_K;
            self.ps2_pace = self.ps2_frame_cycles.max(1);
        }
    }

    fn service_timed_input(&mut self) {
        if self.uart_frame.is_none() && self.cycles >= self.uart_after && !self.uart_in.is_empty() {
            self.uart_frame = Some(InputFrame {
                byte: self.uart_in.pop_front().unwrap() & 0x7f,
                remaining: UART_FRAME_CYCLES,
                blocked: self.uart_tx_busy != 0 || self.flags & F_T == 0,
            });
        }
        if let Some(frame) = &mut self.uart_frame {
            frame.remaining -= 1;
            if frame.remaining == 0 {
                let frame = self.uart_frame.take().unwrap();
                if frame.blocked || self.uart_tx_busy != 0 || self.flags & F_T == 0 {
                    self.uart_dropped += 1;
                } else {
                    self.uart_rx = frame.byte;
                    self.flags &= !F_T;
                    if self.trace_io {
                        self.io_events.push((self.cycles + 1, 'D', frame.byte));
                    }
                }
            }
        }
        if self.ps2_frame.is_none() && !self.ps2_in.is_empty() {
            self.ps2_frame = Some(InputFrame {
                byte: self.ps2_in.pop_front().unwrap(),
                remaining: self.ps2_frame_cycles.max(1),
                blocked: self.flags & F_K == 0,
            });
        }
        if let Some(frame) = &mut self.ps2_frame {
            frame.remaining -= 1;
            if frame.remaining == 0 {
                let frame = self.ps2_frame.take().unwrap();
                if frame.blocked || self.flags & F_K == 0 {
                    self.ps2_dropped += 1;
                } else {
                    self.ps2_reg = frame.byte;
                    self.flags &= !F_K;
                }
            }
        }
    }

    /// Execute exactly one 8 MHz CPU clock.
    #[inline(always)]
    pub fn step(&mut self) {
        self.service_io();

        let old_pc = self.pc;

        let index = ((self.fr as usize) << 12) | ((self.ir as usize) << 4) | self.sc as usize;
        let w = self.ctrl.words[index];

        // ---- ALU -----------------------------------------------------
        let a = self.ar as u16;
        let b = self.br as u16;
        let mut c = b;
        if (w & ES) != 0 {
            c = (!b) & 0xff;
        }
        let mut result = a + c;
        if (w & EC) != 0 {
            result += 1;
        }
        let r = result as u8;

        if result > 0xff {
            self.flags |= F_C;
        } else {
            self.flags &= !F_C;
        }
        if (r & 0x0f) == 0 {
            self.flags |= F_ZL;
        } else {
            self.flags &= !F_ZL;
        }
        if (r & 0xf0) == 0 {
            self.flags |= F_ZH;
        } else {
            self.flags &= !F_ZH;
        }
        if (r & 0x80) != 0 {
            self.flags |= F_N;
        } else {
            self.flags &= !F_N;
        }

        // ---- system bus ---------------------------------------------
        // With the bus 0xff register removed on Redux, an undriven bus
        // reads as 0xff (the microcode relies on this, e.g. INT with no
        // data and the branch "not taken" path).
        let mut bus: u8 = 0xff;
        if (w & AO) != 0 {
            bus = self.ar;
        }
        if (w & BO) != 0 {
            bus = self.br;
        }
        if (w & EO) != 0 {
            bus = r;
        } else if (w & ES) != 0 {
            bus = self.ar & self.br;
        } else if (w & EC) != 0 {
            bus = self.ar | self.br;
        }
        if (w & RO) != 0 {
            bus = self.memory_read(self.mar);
        }
        if (w & IO) != 0 {
            if (w & AI) != 0 && (self.flags & F_T) == 0 {
                bus = self.uart_rx;
                if self.trace_io {
                    self.io_events.push((self.cycles, 'R', bus));
                }
                self.uart_rx = 0xff;
                self.flags |= F_T;
            }
            if (w & BI) != 0 && (self.flags & F_K) == 0 {
                bus = self.ps2_reg;
                self.ps2_reg = 0xff;
                self.flags |= F_K;
            }
        }
        if (w & COL) != 0 {
            bus = self.pc as u8;
        }
        if (w & COH) != 0 {
            bus = (self.pc >> 8) as u8;
        }

        // ---- register inputs ----------------------------------------
        if (w & RI) != 0 {
            self.memory_write(self.mar, bus);
        }
        if (w & AI) != 0 {
            self.ar = bus;
        }
        if (w & BI) != 0 {
            self.br = bus;
        }
        if (w & NI) != 0 {
            self.bank = bus;
        }
        if (w & FI) != 0 {
            self.fr = self.flags & 0x7f;
        }
        if (w & II) != 0 {
            self.ir = bus;
        }
        if (w & CE) != 0 {
            self.pc = self.pc.wrapping_add(1);
        }
        if (w & CIL) != 0 {
            self.pc = (self.pc & 0xff00) | bus as u16;
        }
        if (w & CIH) != 0 {
            self.pc = (self.pc & 0x00ff) | ((bus as u16) << 8);
        }
        if (w & ME) != 0 {
            self.mar = self.mar.wrapping_add(1);
        }
        if (w & MIL) != 0 {
            if (w & MC) != 0 {
                self.mar = (self.mar & 0xff00) | (old_pc & 0x00ff);
            } else {
                self.mar = (self.mar & 0xff00) | bus as u16;
            }
        }
        if (w & MIH) != 0 {
            if (w & MZ) != 0 {
                self.mar &= 0x00ff;
            } else if (w & MC) != 0 {
                self.mar = (self.mar & 0x00ff) | (old_pc & 0xff00);
            } else {
                self.mar = (self.mar & 0x00ff) | ((bus as u16) << 8);
            }
        }

        // ---- UART transmit (TI) -------------------------------------
        if (w & IO) != 0 && (w & AO) != 0 {
            self.uart_tx_data = bus & 0x7f;
            if let Some(frame) = &mut self.uart_frame {
                frame.blocked = true;
            }
            self.uart_tx_busy = UART_TX_CYCLES;
            self.flags |= F_T;
        }

        // ---- step counter -------------------------------------------
        if (w & IC) != 0 {
            self.sc = 0;
        } else {
            self.sc = (self.sc + 1) & 0x0f;
        }

        if self.reset_asserted {
            self.clear_reset_counters();
        }

        self.cycles += 1;
    }

    /// Run `n` clocks (or until a `halt` request, which this core never sets).
    #[inline]
    pub fn run_cycles(&mut self, n: u64) {
        for _ in 0..n {
            self.step();
        }
    }

    /// Run until the UART output contains a given byte, or a cycle budget expires.
    pub fn run_until_output(&mut self, needle: u8, max_cycles: u64) -> bool {
        let start = self.cycles;
        while self.cycles - start < max_cycles {
            self.step();
            if self.uart_out.last() == Some(&needle) {
                return true;
            }
        }
        false
    }

    pub fn uart_output_lossy(&self) -> String {
        String::from_utf8_lossy(&self.uart_out).into_owned()
    }

    pub fn control_word(&self) -> u32 {
        let i = ((self.fr as usize) << 12) | ((self.ir as usize) << 4) | self.sc as usize;
        self.ctrl.words[i]
    }

    /// Raw RAM byte (bypasses the FLASH/RAM mapping). Useful for VRAM dumps.
    #[inline]
    pub fn peek_ram(&self, addr: u16) -> u8 {
        self.ram[addr as usize]
    }

    /// Raw RAM slice, used by frontends to read the framebuffer.
    #[inline]
    pub fn ram(&self) -> &[u8; 0x10000] {
        &self.ram
    }

    /// Number of bytes still queued for the UART receiver, and the byte
    /// currently latched in the receiver register.
    pub fn uart_status(&self) -> (usize, u8, u16) {
        (self.uart_in.len(), self.uart_rx, self.uart_tx_busy)
    }

    pub fn input_pending(&self) -> bool {
        !self.uart_in.is_empty()
            || !self.ps2_in.is_empty()
            || self.uart_frame.is_some()
            || self.ps2_frame.is_some()
    }

    /// Decode the 50x30 text screen from VRAM.  Each cell is one byte wide
    /// and eight pixel rows tall (stride 64), and glyphs are matched against
    /// the character-generator ROM in FLASH bank 1.
    pub fn text_screen(&self) -> String {
        const COLS: usize = 50;
        const ROWS: usize = 30;
        const VIEWPORT: u16 = 0x430c;
        let mut out = String::with_capacity((COLS + 1) * ROWS);
        for r in 0..ROWS {
            let mut line = String::with_capacity(COLS);
            for c in 0..COLS {
                let addr = VIEWPORT.wrapping_add((r as u16) * 512 + c as u16);
                let mut glyph = [0u8; 8];
                for (k, pixel_row) in glyph.iter_mut().enumerate() {
                    *pixel_row =
                        self.video.vram()[(addr.wrapping_add((k as u16) * 64) as usize) & 0x3fff];
                }
                // Reverse-map the glyph to a character code.  Scan past 126
                // so the MinOS block cursor (160) can be recognised; it is
                // rendered as a space because it is not real screen content.
                let mut hit = None;
                'search: for code in 32u16..=160 {
                    if (0..8).all(|k| self.flash[0x1000 + k * 256 + code as usize] == glyph[k]) {
                        hit = Some(code);
                        break 'search;
                    }
                }
                let mut ch = match hit {
                    Some(code) if code < 127 => char::from(code as u8),
                    Some(_) => ' ',
                    None => ' ',
                };
                if hit.is_none() && glyph.iter().any(|&b| b != 0) {
                    ch = '?';
                }
                line.push(ch);
            }
            out.push_str(line.trim_end());
            out.push('\n');
        }
        out
    }
}

#[cfg(test)]
mod tests;

/// Render the visible 400x240 region of VRAM as ASCII art.
/// `cols` is the output width; each source pixel is one character.
pub fn render_ascii(machine: &Machine, cols: usize, rows: usize) -> String {
    render_ascii_crop(machine, cols, rows, (96, 12, 400, 240))
}

/// Render an arbitrary VRAM crop as ASCII art.  VRAM is 512x256, 64 bytes
/// per row, bit 0 is the leftmost pixel.
pub fn render_ascii_crop(
    machine: &Machine,
    cols: usize,
    rows: usize,
    crop: (usize, usize, usize, usize),
) -> String {
    let (cx, cy, cw, ch) = crop;
    let cw = cw.max(1);
    let ch = ch.max(1);
    let mut out = String::with_capacity((cols + 1) * rows);
    for ry in 0..rows {
        let sy = cy + (ry * ch / rows);
        for rx in 0..cols {
            let sx = cx + (rx * cw / cols);
            let addr = 0x4000 + (sy & 0xff) * 64 + ((sx >> 3) & 0x3f);
            let bit = (machine.video.vram()[addr & 0x3fff] >> (sx & 7)) & 1;
            out.push(if bit != 0 { '#' } else { ' ' });
        }
        out.push('\n');
    }
    out
}
