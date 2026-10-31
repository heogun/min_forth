//! SN76489AN programmable sound generator, modelled after the documented
//! internal clocking (input clock / 16) and the MAME reference behaviour for
//! the original SN76489 variant (15-bit XNOR noise, taps D/E, inverted output).
//!
//! The board clocks the chip from an independent 3.579545 MHz oscillator, so
//! the host CPU advances it through a fractional phase accumulator.  The chip
//! has no system reset input: power-on state is retained across CPU resets.

pub const INPUT_CLOCK_HZ: u64 = 3_579_545;
pub const CPU_CLOCK_HZ: u64 = 8_000_000;
/// Internal tick every 16 input clocks on the SN76489.
pub const CLOCK_DIVIDER: u32 = 16;
/// READY is held low for 32 input clocks after a write (4 * divider / clock).
pub const READY_INPUT_CLOCKS: u32 = 32;

const FEEDBACK_MASK: u16 = 0x4000;

/// 2 dB per step, 15 steps plus silence.  Four channels are summed, so each
/// channel is scaled to one quarter of the signed 16-bit range.
const VOLUME_TABLE: [i32; 16] = [
    8191, 6506, 5168, 4105, 3261, 2590, 2057, 1634, 1298, 1031, 819, 650, 516, 410, 326, 0,
];

pub struct Psg {
    registers: [u16; 8],
    last_register: usize,
    period: [u32; 4],
    count: [i32; 4],
    output: [bool; 4],
    volume: [i32; 4],
    rng: u16,
    ready_timer: u32,
    input_acc: u64,
    divider: u32,
}

impl Default for Psg {
    fn default() -> Self {
        let mut psg = Self {
            registers: [0; 8],
            last_register: 0,
            period: [0x400, 0x400, 0x400, 0],
            count: [0; 4],
            output: [false; 4],
            volume: [0; 4],
            rng: FEEDBACK_MASK,
            ready_timer: 0,
            input_acc: 0,
            divider: 0,
        };
        psg.output[3] = psg.rng & 1 != 0;
        for i in 0..4 {
            psg.volume[i] = VOLUME_TABLE[psg.registers[i * 2 + 1] as usize & 0x0f];
        }
        psg
    }
}

impl Psg {
    /// Advance the chip by one CPU clock.  The oscillator runs asynchronously
    /// at 3.579545 MHz; the accumulator keeps it cycle-exact on average.
    pub fn step(&mut self) {
        self.input_acc += INPUT_CLOCK_HZ;
        while self.input_acc >= CPU_CLOCK_HZ {
            self.input_acc -= CPU_CLOCK_HZ;
            self.input_tick();
        }
    }

    fn input_tick(&mut self) {
        if self.ready_timer > 0 {
            self.ready_timer -= 1;
        }
        self.divider += 1;
        if self.divider >= CLOCK_DIVIDER {
            self.divider = 0;
            self.internal_tick();
        }
    }

    fn internal_tick(&mut self) {
        for i in 0..3 {
            self.count[i] -= 1;
            if self.count[i] <= 0 {
                self.output[i] = !self.output[i];
                self.count[i] = self.period[i] as i32;
            }
        }
        self.count[3] -= 1;
        if self.count[3] <= 0 {
            let tap1 = self.rng & 0x01 != 0;
            let tap2 = self.rng & 0x02 != 0;
            let white = self.registers[6] & 0x04 != 0;
            let feedback = if tap1 != (tap2 && white) {
                FEEDBACK_MASK
            } else {
                0
            };
            self.rng = (self.rng >> 1) | feedback;
            self.output[3] = self.rng & 1 != 0;
            self.count[3] = self.period[3] as i32;
        }
    }

    /// True when the chip has finished the 32-clock write recovery window.
    pub fn ready(&self) -> bool {
        self.ready_timer == 0
    }

    /// Latch a byte on the rising edge of /WE (after the board deasserts the
    /// shared CE/WE strobe).  Every write restarts the READY timer.
    pub fn write(&mut self, data: u8) {
        let mut r = self.last_register;
        if data & 0x80 != 0 {
            r = ((data & 0x70) >> 4) as usize;
            self.last_register = r;
            self.registers[r] = (self.registers[r] & 0x3f0) | (data as u16 & 0x00f);
        }
        let c = r >> 1;
        match r {
            0 | 2 | 4 => {
                if data & 0x80 == 0 {
                    self.registers[r] = (self.registers[r] & 0x00f) | ((data as u16 & 0x3f) << 4);
                }
                self.period[c] = if self.registers[r] != 0 {
                    self.registers[r] as u32
                } else {
                    0x400
                };
                if r == 4 && (self.registers[6] & 0x03) == 0x03 {
                    self.period[3] = self.period[2] << 1;
                }
            }
            1 | 3 | 5 | 7 => {
                self.volume[c] = VOLUME_TABLE[(data & 0x0f) as usize];
                if data & 0x80 == 0 {
                    self.registers[r] = (self.registers[r] & 0x3f0) | (data as u16 & 0x00f);
                }
            }
            6 => {
                if data & 0x80 == 0 {
                    self.registers[6] = (self.registers[6] & 0x3f0) | (data as u16 & 0x00f);
                }
                let n = self.registers[6];
                self.period[3] = if (n & 0x03) == 0x03 {
                    self.period[2] << 1
                } else {
                    1 << (5 + (n & 0x03))
                };
                self.rng = FEEDBACK_MASK;
            }
            _ => {}
        }
        self.ready_timer = READY_INPUT_CLOCKS;
    }

    /// Current summed output before the board's analogue mute/AC coupling.
    /// Silence is zero; each channel contributes at most 8191.
    pub fn level(&self) -> i32 {
        (0..4)
            .map(|i| if self.output[i] { self.volume[i] } else { 0 })
            .sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn advance_input_clocks(psg: &mut Psg, clocks: u32) {
        for _ in 0..clocks {
            psg.input_tick();
        }
    }

    #[test]
    fn ready_is_low_for_thirty_two_input_clocks_after_write() {
        let mut psg = Psg::default();
        assert!(psg.ready());
        psg.write(0x9f);
        assert!(!psg.ready());
        advance_input_clocks(&mut psg, 31);
        assert!(!psg.ready());
        advance_input_clocks(&mut psg, 1);
        assert!(psg.ready());
    }

    #[test]
    fn tone_period_zero_maps_to_0x400_and_toggles_at_internal_rate() {
        let mut psg = Psg::default();
        psg.write(0x80); // latch tone 0, low nibble zero
        assert_eq!(psg.period[0], 0x400);
        psg.write(0x00); // high bits zero
        assert_eq!(psg.period[0], 0x400);
        // Silence is not asserted; channel output starts low.
        let before = psg.output[0];
        advance_input_clocks(&mut psg, CLOCK_DIVIDER * 0x400);
        assert_eq!(psg.output[0], !before);
    }

    #[test]
    fn volume_table_and_channel_sum() {
        let mut psg = Psg::default();
        psg.write(0x9f); // channel 0 volume 15 (silence)
        assert_eq!(psg.volume[0], 0);
        psg.write(0x90); // channel 0 volume 0 (max)
        assert_eq!(psg.volume[0], 8191);
        assert_eq!(psg.level(), 0); // channel still low
    }

    #[test]
    fn noise_register_selects_documented_periods() {
        let mut psg = Psg::default();
        psg.write(0xe0); // noise control, rate 0
        assert_eq!(psg.period[3], 1 << 5);
        psg.write(0xe4); // white noise, rate 0
        assert_eq!(psg.period[3], 1 << 5);
        psg.write(0xe3); // clocked by tone 2
        assert_eq!(psg.period[3], 0x400 << 1);
    }
}
