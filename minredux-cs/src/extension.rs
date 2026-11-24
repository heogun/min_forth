//! Integrated colour + SN76489 extension, addresses `0xFEE0..0xFEEF`.
//!
//! Address bit 3 is not decoded, producing two aliases for each register:
//!
//! | address              | write                       | read          |
//! | -------------------- | --------------------------- | ------------- |
//! | `0xFEE0`, `0xFEE8`   | SN76489 data hold latch     | -             |
//! | `0xFEE1`, `0xFEE9`   | -                           | status        |
//! | `0xFEE2`, `0xFEEA`   | control register            | -             |
//! | other aliases        | reserved, no RAM selected   | `0xFF`        |
//!
//! Control bits: 0 colour enable, 1 SN write assert (CE/WE low), 2 attribute
//! write mode, 3 audio unmute.  Reset clears the control register; the PSG has
//! no reset pin and keeps its state.
//!
//! SN write protocol (CIRCUIT.md): hold the data latch, assert bit 1, wait
//! for READY to return high *while still asserted*, then deassert.  The chip
//! samples the held data when CE/WE go low; READY recovers after 32 input
//! clocks regardless of the strobe.  Deasserting before READY or changing the
//! data latch mid-strobe would corrupt a real transfer, so both are counted in
//! `protocol_errors` instead of being silently accepted.

use crate::psg::Psg;

pub const WINDOW_FIRST: u16 = 0xFEE0;
pub const WINDOW_LAST: u16 = 0xFEEF;

pub const CONTROL_COLOR: u8 = 1 << 0;
pub const CONTROL_SN_WRITE: u8 = 1 << 1;
pub const CONTROL_ATTR: u8 = 1 << 2;
pub const CONTROL_AUDIO: u8 = 1 << 3;

pub struct Extension {
    control: u8,
    sn_data: u8,
    strobe: bool,
    pub psg: Psg,
    /// Driver bugs a real SN76489 would not tolerate (see module docs).
    pub protocol_errors: u64,
}

impl Default for Extension {
    fn default() -> Self {
        Self::new()
    }
}

impl Extension {
    pub fn new() -> Self {
        Self {
            control: 0,
            sn_data: 0,
            strobe: false,
            psg: Psg::default(),
            protocol_errors: 0,
        }
    }

    #[inline(always)]
    pub fn hit(addr: u16) -> bool {
        (addr & 0xfff0) == WINDOW_FIRST
    }

    /// Reset clears only the control latch; the PSG keeps power-on state.
    pub fn reset(&mut self) {
        self.control = 0;
        self.sn_data = 0;
        self.strobe = false;
    }

    #[inline(always)]
    pub fn color_enable(&self) -> bool {
        self.control & CONTROL_COLOR != 0
    }

    #[inline(always)]
    pub fn attr_mode(&self) -> bool {
        self.control & CONTROL_ATTR != 0
    }

    #[inline(always)]
    pub fn audio_enable(&self) -> bool {
        self.control & CONTROL_AUDIO != 0
    }

    #[inline(always)]
    pub fn sn_strobe(&self) -> bool {
        self.strobe
    }

    #[inline(always)]
    pub fn sn_ready(&self) -> bool {
        self.psg.ready()
    }

    pub fn control(&self) -> u8 {
        self.control
    }

    pub fn sn_data(&self) -> u8 {
        self.sn_data
    }

    /// Status byte read from `0xFEE1`/`0xFEE9`; the upper nibble is grounded.
    pub fn status(&self) -> u8 {
        (self.sn_ready() as u8)
            | ((self.attr_mode() as u8) << 1)
            | ((self.color_enable() as u8) << 2)
            | ((self.audio_enable() as u8) << 3)
    }

    /// CPU read inside the extension window.  Only the status alias drives the
    /// bus; every other sub-address floats high.
    pub fn read(&self, addr: u16) -> u8 {
        match addr & 0x07 {
            1 => self.status(),
            _ => 0xff,
        }
    }

    /// CPU write inside the extension window.  No write reaches system RAM.
    pub fn write(&mut self, addr: u16, value: u8) {
        match addr & 0x07 {
            0 => {
                if self.strobe && value != self.sn_data {
                    self.protocol_errors += 1;
                }
                self.sn_data = value;
            }
            2 => self.write_control(value),
            _ => {}
        }
    }

    fn write_control(&mut self, value: u8) {
        let previous = self.control;
        self.control = value & 0x0f;
        let was_asserted = previous & CONTROL_SN_WRITE != 0;
        let asserted = self.control & CONTROL_SN_WRITE != 0;
        if !was_asserted && asserted {
            self.strobe = true;
            // CE/WE low: the chip samples the held data and drops READY.
            self.psg.write(self.sn_data);
        } else if was_asserted && !asserted {
            self.strobe = false;
            if !self.psg.ready() {
                self.protocol_errors += 1; // strobe released mid-transfer
            }
        }
    }

    /// Advance the independently clocked PSG by one CPU clock.
    pub fn step(&mut self) {
        self.psg.step();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_uses_top_twelve_bits() {
        for addr in 0..=u16::MAX {
            assert_eq!(
                Extension::hit(addr),
                (0xfee0..=0xfeef).contains(&addr),
                "{addr:04x}"
            );
        }
    }

    #[test]
    fn status_bits_and_reserved_reads() {
        let mut e = Extension::new();
        assert_eq!(e.read(0xfee1), 0x01); // READY after power-on
        e.write(0xfee2, CONTROL_ATTR | CONTROL_COLOR | CONTROL_AUDIO);
        assert_eq!(e.read(0xfee9), 0x0f);
        assert_eq!(e.read(0xfee0), 0xff);
        assert_eq!(e.read(0xfeef), 0xff);
    }

    #[test]
    fn sn_ready_recovers_while_strobe_is_still_asserted() {
        let mut e = Extension::new();
        e.write(0xfee0, 0x9f);
        e.write(0xfee2, CONTROL_SN_WRITE);
        assert_eq!(e.read(0xfee1) & 1, 0); // asserted: busy
        for _ in 0..200 {
            e.step();
        }
        // CIRCUIT.md: READY must go high before the driver deasserts.
        assert_eq!(e.read(0xfee1) & 1, 1);
        e.write(0xfee2, 0);
        assert_eq!(e.read(0xfee1) & 1, 1);
        assert_eq!(e.protocol_errors, 0);
    }

    #[test]
    fn early_release_and_mid_strobe_data_change_are_protocol_errors() {
        let mut e = Extension::new();
        e.write(0xfee0, 0x9f);
        e.write(0xfee2, CONTROL_SN_WRITE);
        e.write(0xfee0, 0xbf); // data changed while CE/WE low
        e.write(0xfee2, 0); // released before READY
        assert_eq!(e.protocol_errors, 2);
    }

    #[test]
    fn reset_clears_control_but_not_psg() {
        let mut e = Extension::new();
        e.write(0xfee2, CONTROL_COLOR | CONTROL_AUDIO);
        e.reset();
        assert_eq!(e.control(), 0);
        assert!(!e.audio_enable());
        assert!(!e.color_enable());
        assert!(!e.attr_mode());
    }
}
