//! Digital VGA model from Redux schematic sheets 4 and 6.
//!
//! One byte fetch per four CPU clocks, two 16 MHz pixel edges per CPU clock.
//! Counter Q6 is unconnected: H=Q0..5, V1=Q7, V2..256=Q8..15.
//! Consequently each VRAM row is scanned twice. V4 && V256 asynchronously
//! clears the counter after 520 scanlines (260 logical rows), not VGA's
//! textbook 525 lines. No analog propagation delays are modelled.

pub const SCAN_LINES: usize = 520;
pub const FRAME_CPU_CYCLES: u64 = 64 * SCAN_LINES as u64 * 4;

#[derive(Clone, Copy, Debug)]
pub struct VideoSignals {
    pub x: u16,
    pub y: u16,
    /// Electrical signal levels: false means active sync.
    pub hsync: bool,
    pub vsync: bool,
    /// Two consecutive pixels clocked out during the previous CPU step.
    pub pixels: [bool; 2],
}

pub struct Video {
    vram: Box<[u8; 0x4000]>,
    pending: Option<(usize, u8)>,
    phase: u8,
    counter: u16,
    shift: u8,
    signals: VideoSignals,
    /// Bytes actually sampled by the scanner, including blanking regions.
    scanout: Box<[u8; 64 * SCAN_LINES]>,
    pub frames: u64,
    pub overwritten_writes: u64,
}

impl Default for Video {
    fn default() -> Self {
        Self {
            vram: Box::new([0; 0x4000]),
            pending: None,
            phase: 0,
            counter: 0,
            shift: 0,
            signals: VideoSignals {
                x: 0,
                y: 0,
                hsync: false,
                vsync: false,
                pixels: [false; 2],
            },
            scanout: Box::new([0; 64 * SCAN_LINES]),
            frames: 0,
            overwritten_writes: 0,
        }
    }
}

impl Video {
    pub(crate) fn capture_write(&mut self, addr: u16, value: u8) {
        if (0x4000..0x8000).contains(&addr)
            && self
                .pending
                .replace((addr as usize & 0x3fff, value))
                .is_some()
        {
            self.overwritten_writes += 1;
        }
    }

    pub(crate) fn tick(&mut self) {
        let col = self.counter as usize & 63;
        let row = self.counter as usize >> 7;
        let scanline = self.counter as usize >> 6;
        if self.phase == 0 {
            // ~VREG_OE high: scanner owns the address lines; postpone VREG.
            self.shift = self.vram[((row & 255) << 6) | col];
            self.scanout[self.counter as usize] = self.shift;
        } else if let Some((addr, byte)) = self.pending.take() {
            self.vram[addr] = byte;
        }
        self.signals = VideoSignals {
            x: (col * 8 + self.phase as usize * 2) as u16,
            y: scanline as u16,
            hsync: col & 0x38 != 0,
            // U8's SR latch holds sync low until V1 goes high after reset.
            vsync: row != 0,
            pixels: [self.shift & 1 != 0, self.shift & 2 != 0],
        };
        self.shift >>= 2;
        self.phase = (self.phase + 1) & 3;
        if self.phase == 0 {
            self.counter += 1;
            if self.counter & 0x8200 == 0x8200 {
                // V4 && V256 -> ~MRC
                self.counter = 0;
                self.frames += 1;
            }
        }
    }

    /// Video RAM is physically distinct from the CPU's system-RAM mirror.
    pub fn vram(&self) -> &[u8; 0x4000] {
        &self.vram
    }

    pub fn scanout(&self) -> &[u8; 64 * SCAN_LINES] {
        &self.scanout
    }

    pub fn signals(&self) -> VideoSignals {
        self.signals
    }

    pub fn write_pending(&self) -> bool {
        self.pending.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vreg_is_delayed_and_postponed_during_scanner_slot() {
        let mut v = Video::default();
        v.capture_write(0x430c, 0xa5);
        assert_eq!(v.vram()[0x30c], 0);
        v.tick(); // scanner owns cycle 0
        assert!(v.write_pending());
        v.tick();
        assert!(!v.write_pending());
        assert_eq!(v.vram()[0x30c], 0xa5);
    }

    #[test]
    fn pixel_order_shift_register_and_two_scanlines_per_row() {
        let mut v = Video::default();
        v.vram[0] = 0b1000_0001;
        v.tick();
        assert_eq!(v.signals().pixels, [true, false]);
        v.tick();
        v.tick();
        v.tick();
        assert_eq!(v.signals().pixels, [false, true]);
        for _ in 4..256 {
            v.tick();
        }
        v.tick();
        assert_eq!(v.signals().y, 1);
        assert_eq!(v.signals().pixels, [true, false]);
        assert_eq!(v.scanout()[0], 0x81);
        assert_eq!(v.scanout()[64], 0x81);
    }

    #[test]
    fn frame_period_sync_and_no_cpu_reset_dependency() {
        let mut v = Video::default();
        for _ in 0..FRAME_CPU_CYCLES - 1 {
            v.tick();
        }
        assert_eq!(v.frames, 0);
        assert_eq!(v.signals().y, 519);
        v.tick();
        assert_eq!(v.frames, 1);
        v.tick();
        assert_eq!((v.signals().x, v.signals().y), (0, 0));
        assert!(!v.signals().hsync);
        assert!(!v.signals().vsync);
        for _ in 0..512 {
            v.tick();
        }
        assert!(v.signals().vsync);
    }

    #[test]
    fn vreg_is_one_entry_not_an_unbounded_queue() {
        let mut v = Video::default();
        v.capture_write(0x4000, 1);
        v.capture_write(0x4001, 2);
        v.tick();
        v.tick();
        assert_eq!(v.overwritten_writes, 1);
        assert_eq!(&v.vram()[..2], &[0, 2]);
    }
}
