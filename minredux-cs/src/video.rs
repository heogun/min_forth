//! Digital VGA model from Redux schematic sheets 4 and 6.
//!
//! One byte fetch per four CPU clocks, two 16 MHz pixel edges per CPU clock.
//! Counter Q6 is unconnected: H=Q0..5, V1=Q7, V2..256=Q8..15.
//! Consequently each VRAM row is scanned twice. V4 && V256 asynchronously
//! clears the counter after 520 scanlines (260 logical rows), not VGA's
//! textbook 525 lines. No analog propagation delays are modelled.
//!
//! The integrated colour extension shares the VREG address and data bus.  U82
//! captures the destination plane when the VREG latches a write, U81 latches
//! the attribute byte at the same fetch as the bitmap byte, and U83 latches the
//! active-window and colour-enable state.  The palette output is therefore
//! derived from a coherent per-fetch snapshot, not from live late values.

pub const SCAN_LINES: usize = 520;
pub const FRAME_CPU_CYCLES: u64 = 64 * SCAN_LINES as u64 * 4;
pub const ATTRIBUTE_BYTES: usize = 0x800;
/// Visible 400x240 window used by the reference monitor.
pub const VIEW_X: usize = 96;
pub const VIEW_Y: usize = 12;
pub const VIEW_WIDTH: usize = 400;
pub const VIEW_HEIGHT: usize = 240;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Rgb {
    pub r: u8,
    pub g: u8,
    pub b: u8,
}

impl Rgb {
    pub const BLACK: Self = Self { r: 0, g: 0, b: 0 };
    pub const WHITE: Self = Self {
        r: 255,
        g: 255,
        b: 255,
    };
}

#[derive(Clone, Copy, Debug)]
pub struct VideoSignals {
    pub x: u16,
    pub y: u16,
    /// Electrical signal levels: false means active sync.
    pub hsync: bool,
    pub vsync: bool,
    /// Two consecutive pixels clocked out during the previous CPU step.
    pub pixels: [bool; 2],
    /// Palette output for those two pixels (black while blanked).
    pub rgb: [Rgb; 2],
    /// True outside the 400x240 active window; the DAC buffers are high-Z.
    pub blank: bool,
}

struct PendingWrite {
    index: usize,
    value: u8,
    attribute: bool,
}

pub struct Video {
    vram: Box<[u8; 0x4000]>,
    attributes: Box<[u8; ATTRIBUTE_BYTES]>,
    pending: Option<PendingWrite>,
    phase: u8,
    counter: u16,
    shift: u8,
    signals: VideoSignals,
    /// Bytes actually sampled by the scanner, including blanking regions.
    scanout: Box<[u8; 64 * SCAN_LINES]>,
    /// Live colour-enable control bit; U83 latches it per fetch.
    color_enable: bool,
    latched_color: bool,
    latched_active: bool,
    latched_attr: u8,
    pub frames: u64,
    pub overwritten_writes: u64,
}

impl Default for Video {
    fn default() -> Self {
        Self {
            vram: Box::new([0; 0x4000]),
            attributes: Box::new([0; ATTRIBUTE_BYTES]),
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
                rgb: [Rgb::BLACK; 2],
                blank: true,
            },
            scanout: Box::new([0; 64 * SCAN_LINES]),
            color_enable: false,
            latched_color: false,
            latched_active: false,
            latched_attr: 0,
            frames: 0,
            overwritten_writes: 0,
        }
    }
}

/// Attribute SRAM address after the U78 adder and U79 XOR.
///
/// The scanner presents `VA = ((y & 255) << 6) | column`.  The adder treats
/// VA9..VA12 as its low four bits with VA8 as carry-in, matching the physical
/// wiring, so the ordinary formula `(((y + 4) & 255) >> 3)` only holds when
/// the top address bit is folded back through CA10.
pub fn attribute_index(y: usize, column: usize) -> usize {
    let va = (((y & 0xff) as u16) << 6) | (column as u16 & 63);
    let a = (va >> 9) & 0x0f;
    let carry_in = (va >> 8) & 1;
    let total = a + carry_in;
    let ca10 = ((total >> 4) & 1) ^ ((va >> 13) & 1);
    let row = ((total & 0x0f) | (ca10 << 4)) as usize;
    row * 64 + (va as usize & 63)
}

fn attribute_index_for_vreg(offset: u16) -> usize {
    let offset = offset & 0x3fff;
    attribute_index((offset >> 6) as usize, (offset & 63) as usize)
}

/// U84/U85/U86/U87 active-window decoder.
pub fn active_window(y: usize, column: usize) -> bool {
    let col = (column & 63) as u8;
    let h12 = col & 0b0000_1100 == 0b0000_1100;
    let hlow = col & 0b0010_0000 == 0 && col & 0b0001_0000 == 0 && !h12;
    let hhigh_bad = col & 0b0011_1110 == 0b0011_1110;
    let row = attribute_index(y, column) / 64;
    let vbad = row & 0b1_1110 == 0;
    let v256 = y >= 256;
    !vbad && !hlow && !hhigh_bad && !v256
}

/// Palette DAC for one attribute byte.  The low nibble is the foreground
/// (pixel = 1); the high nibble is the background.  Each nibble is `I:R:G:B`
/// and each channel is `(2 * colour + I) / 3` of full scale.
pub fn pixel_rgb(attribute: u8, pixel: bool, color_enable: bool) -> Rgb {
    if !color_enable {
        return if pixel { Rgb::WHITE } else { Rgb::BLACK };
    }
    let colors = if pixel {
        attribute & 0x0f
    } else {
        attribute >> 4
    };
    let blue = colors & 1;
    let green = (colors >> 1) & 1;
    let red = (colors >> 2) & 1;
    let intensity = (colors >> 3) & 1;
    let channel = |c: u8| ((2 * c as u16 + intensity as u16) * 255 / 3) as u8;
    Rgb {
        r: channel(red),
        g: channel(green),
        b: channel(blue),
    }
}

impl Video {
    /// Capture a CPU write pulse together with the plane latched by U82.
    pub(crate) fn capture_write(&mut self, addr: u16, value: u8, attribute: bool) {
        if (0x4000..0x8000).contains(&addr) {
            let pending = PendingWrite {
                index: addr as usize & 0x3fff,
                value,
                attribute,
            };
            if self.pending.replace(pending).is_some() {
                self.overwritten_writes += 1;
            }
        }
    }

    pub(crate) fn set_color_enable(&mut self, enabled: bool) {
        self.color_enable = enabled;
    }

    pub(crate) fn tick(&mut self) {
        let col = self.counter as usize & 63;
        let row = self.counter as usize >> 7;
        let scanline = self.counter as usize >> 6;
        if self.phase == 0 {
            // ~VREG_OE high: scanner owns the address lines; postpone VREG.
            self.shift = self.vram[((row & 255) << 6) | col];
            self.scanout[self.counter as usize] = self.shift;
            // U81/U83 latch the attribute byte and the window/colour state at
            // the same fetch that loads the bitmap shift register.
            self.latched_attr = self.attributes[attribute_index(row, col)];
            self.latched_color = self.color_enable;
            self.latched_active = active_window(row, col);
        } else if let Some(pending) = self.pending.take() {
            if pending.attribute {
                let index = attribute_index_for_vreg(pending.index as u16);
                self.attributes[index] = pending.value;
            } else {
                self.vram[pending.index] = pending.value;
            }
        }
        let pixels = [self.shift & 1 != 0, self.shift & 2 != 0];
        let blank = !self.latched_active;
        let colors = if blank {
            [Rgb::BLACK; 2]
        } else {
            [
                pixel_rgb(self.latched_attr, pixels[0], self.latched_color),
                pixel_rgb(self.latched_attr, pixels[1], self.latched_color),
            ]
        };
        self.signals = VideoSignals {
            x: (col * 8 + self.phase as usize * 2) as u16,
            y: scanline as u16,
            hsync: col & 0x38 != 0,
            // U8's SR latch holds sync low until V1 goes high after reset.
            vsync: row != 0,
            pixels,
            rgb: colors,
            blank,
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

    pub fn attributes(&self) -> &[u8; ATTRIBUTE_BYTES] {
        &self.attributes
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

    /// Attribute byte used by one 8x8 viewport cell.
    pub fn cell_attribute(&self, cell_row: usize, cell_column: usize) -> u8 {
        let index = (cell_row + 2) * 64 + cell_column + 12;
        self.attributes[index % ATTRIBUTE_BYTES]
    }

    /// Foreground/background colours of one viewport cell.
    pub fn cell_colors(&self, cell_row: usize, cell_column: usize) -> (Rgb, Rgb) {
        let attr = self.cell_attribute(cell_row, cell_column);
        (
            pixel_rgb(attr, true, self.color_enable),
            pixel_rgb(attr, false, self.color_enable),
        )
    }

    /// Render the visible 400x240 region as packed RGB (3 bytes per pixel).
    pub fn frame_rgb(&self) -> Vec<u8> {
        let mut out = vec![0u8; VIEW_WIDTH * VIEW_HEIGHT * 3];
        for y in 0..VIEW_HEIGHT {
            let sy = VIEW_Y + y;
            for x in 0..VIEW_WIDTH {
                let sx = VIEW_X + x;
                let col = (sx >> 3) & 63;
                let bit = sx & 7;
                let cell = ((sy & 255) << 6) | col;
                let pixel = (self.vram[cell & 0x3fff] >> bit) & 1 != 0;
                let attr = self.attributes[attribute_index(sy, col)];
                let color = pixel_rgb(attr, pixel, self.color_enable);
                let i = (y * VIEW_WIDTH + x) * 3;
                out[i] = color.r;
                out[i + 1] = color.g;
                out[i + 2] = color.b;
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vreg_is_delayed_and_postponed_during_scanner_slot() {
        let mut v = Video::default();
        v.capture_write(0x430c, 0xa5, false);
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
        v.capture_write(0x4000, 1, false);
        v.capture_write(0x4001, 2, false);
        v.tick();
        v.tick();
        assert_eq!(v.overwritten_writes, 1);
        assert_eq!(&v.vram()[..2], &[0, 2]);
    }

    #[test]
    fn attribute_adder_matches_viewport_formula_across_raster() {
        for y in 0..260 {
            for column in 0..64 {
                assert_eq!(
                    attribute_index(y, column),
                    (((y + 4) & 255) >> 3) * 64 + column
                );
            }
        }
    }

    #[test]
    fn active_window_matches_hardware_gate_truth() {
        for y in 0..260 {
            for column in 0..64 {
                let expected = (12..62).contains(&column) && (12..252).contains(&y);
                assert_eq!(active_window(y, column), expected, "y={y} col={column}");
            }
        }
    }

    #[test]
    fn attribute_write_plane_is_captured_per_write() {
        let mut v = Video::default();
        v.capture_write(0x430c, 0x1e, true);
        v.tick();
        v.tick();
        assert_eq!(v.attributes()[attribute_index(12, 12)], 0x1e);
        assert_eq!(v.vram()[0x30c], 0);
        v.capture_write(0x430c, 0x2d, false);
        v.tick();
        v.tick();
        assert_eq!(v.vram()[0x30c], 0x2d);
        assert_eq!(v.attributes()[attribute_index(12, 12)], 0x1e);
    }

    #[test]
    fn palette_nibbles_are_i_r_g_b_with_three_level_channels() {
        // Foreground = 0b1111 -> full white, background = 0b0000 -> black.
        assert_eq!(
            pixel_rgb(0x0f, true, true),
            Rgb {
                r: 255,
                g: 255,
                b: 255
            }
        );
        assert_eq!(pixel_rgb(0x0f, false, true), Rgb::BLACK);
        // Foreground 0b0100 = red only.
        assert_eq!(pixel_rgb(0x04, true, true), Rgb { r: 170, g: 0, b: 0 });
        // Foreground 0b1100 = red + intensity.
        assert_eq!(
            pixel_rgb(0x0c, true, true),
            Rgb {
                r: 255,
                g: 85,
                b: 85
            }
        );
        // Colour disabled: monochrome bypass.
        assert_eq!(pixel_rgb(0x0f, true, false), Rgb::WHITE);
        assert_eq!(pixel_rgb(0x0f, false, false), Rgb::BLACK);
    }
}
