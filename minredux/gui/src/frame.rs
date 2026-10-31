//! Monochrome framebuffer extraction, nearest-neighbour scaling, and BMP export.
//!
//! The Redux VGA scans a 512x256 one-bit VRAM.  MinOS puts its visible
//! 400x240 viewport at (96, 12), so that crop is what the GUI presents.

/// Visible viewport width in VRAM pixels.
pub const SCREEN_WIDTH: usize = 400;
/// Visible viewport height in VRAM pixels.
pub const SCREEN_HEIGHT: usize = 240;
/// Left edge of the MinOS viewport inside the 512-pixel scanline.
pub const VIEW_X: usize = 96;
/// Top edge of the MinOS viewport inside the 256-row VRAM.
pub const VIEW_Y: usize = 12;
/// VRAM bytes per scanline (512 pixels / 8).
pub const VRAM_STRIDE: usize = 64;

const _: () = assert!(VIEW_X + SCREEN_WIDTH <= VRAM_STRIDE * 8);
const _: () = assert!(VIEW_Y + SCREEN_HEIGHT <= 256);

/// Colours are minifb's `0x00RRGGBB` values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Palette {
    pub fg: u32,
    pub bg: u32,
}

impl Default for Palette {
    fn default() -> Self {
        Self {
            fg: 0x00e8e8e8,
            bg: 0x00000000,
        }
    }
}

/// Copy the 400x240 viewport from VRAM into `out` as 32-bit pixels.
///
/// `out` must hold exactly `SCREEN_WIDTH * SCREEN_HEIGHT` entries.  Bit 0 of
/// each VRAM byte is the leftmost pixel.
pub fn render(vram: &[u8; 0x4000], palette: Palette, out: &mut [u32]) {
    assert_eq!(out.len(), SCREEN_WIDTH * SCREEN_HEIGHT);
    for y in 0..SCREEN_HEIGHT {
        let src = &vram[(VIEW_Y + y) * VRAM_STRIDE..][..VRAM_STRIDE];
        let dst = &mut out[y * SCREEN_WIDTH..][..SCREEN_WIDTH];
        for (x, pixel) in dst.iter_mut().enumerate() {
            let sx = VIEW_X + x;
            let bit = (src[sx >> 3] >> (sx & 7)) & 1;
            *pixel = if bit != 0 { palette.fg } else { palette.bg };
        }
    }
}

/// Scale `src` by an integer factor with nearest-neighbour sampling.
pub fn scale_nearest(src: &[u32], src_w: usize, src_h: usize, factor: usize, dst: &mut [u32]) {
    assert!(factor >= 1);
    let dst_w = src_w * factor;
    assert_eq!(src.len(), src_w * src_h);
    assert_eq!(dst.len(), dst_w * src_h * factor);
    for sy in 0..src_h {
        let src_row = &src[sy * src_w..][..src_w];
        for dy in 0..factor {
            let dst_row = &mut dst[(sy * factor + dy) * dst_w..][..dst_w];
            for (sx, &pixel) in src_row.iter().enumerate() {
                dst_row[sx * factor..][..factor].fill(pixel);
            }
        }
    }
}

/// Encode 32-bit `0x00RRGGBB` pixels as a 24-bit bottom-up BMP file.
pub fn bmp_bytes(pixels: &[u32], width: usize, height: usize) -> Vec<u8> {
    assert!(width > 0 && height > 0);
    assert_eq!(pixels.len(), width * height);
    let row_bytes = (width * 3).div_ceil(4) * 4;
    let image_bytes = row_bytes * height;
    let file_bytes = 54 + image_bytes;
    let mut out = Vec::with_capacity(file_bytes);

    out.extend_from_slice(b"BM");
    out.extend_from_slice(&(file_bytes as u32).to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes()); // reserved
    out.extend_from_slice(&54u32.to_le_bytes()); // pixel data offset

    out.extend_from_slice(&40u32.to_le_bytes()); // BITMAPINFOHEADER size
    out.extend_from_slice(&(width as i32).to_le_bytes());
    out.extend_from_slice(&(height as i32).to_le_bytes()); // positive: bottom-up
    out.extend_from_slice(&1u16.to_le_bytes()); // planes
    out.extend_from_slice(&24u16.to_le_bytes()); // bits per pixel
    out.extend_from_slice(&0u32.to_le_bytes()); // BI_RGB
    out.extend_from_slice(&(image_bytes as u32).to_le_bytes());
    out.extend_from_slice(&2835i32.to_le_bytes()); // 72 DPI
    out.extend_from_slice(&2835i32.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes()); // colours used
    out.extend_from_slice(&0u32.to_le_bytes()); // important colours

    for y in (0..height).rev() {
        for &pixel in &pixels[y * width..][..width] {
            out.push(pixel as u8);
            out.push((pixel >> 8) as u8);
            out.push((pixel >> 16) as u8);
        }
        out.resize(out.len() + (row_bytes - width * 3), 0);
    }
    debug_assert_eq!(out.len(), file_bytes);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const FG: u32 = 0x00ff8800;
    const BG: u32 = 0x00102030;

    fn set_pixel(vram: &mut [u8; 0x4000], x: usize, y: usize) {
        vram[y * VRAM_STRIDE + (x >> 3)] |= 1 << (x & 7);
    }

    #[test]
    fn renders_the_viewport_crop_and_bit_order() {
        let mut vram = [0u8; 0x4000];
        set_pixel(&mut vram, VIEW_X, VIEW_Y);
        set_pixel(&mut vram, VIEW_X + 7, VIEW_Y);
        set_pixel(&mut vram, VIEW_X, VIEW_Y + 1);
        // Outside the viewport must not bleed into the frame.
        set_pixel(&mut vram, VIEW_X - 1, VIEW_Y);
        set_pixel(&mut vram, VIEW_X, VIEW_Y - 1);

        let mut out = vec![0u32; SCREEN_WIDTH * SCREEN_HEIGHT];
        render(&vram, Palette { fg: FG, bg: BG }, &mut out);
        assert_eq!(out[0], FG);
        assert_eq!(out[1], BG);
        assert_eq!(out[7], FG);
        assert_eq!(out[SCREEN_WIDTH - 1], BG);
        assert_eq!(out[SCREEN_WIDTH], FG);
        assert!(out.iter().all(|&p| p == FG || p == BG));
        assert_eq!(out.iter().filter(|&&p| p == FG).count(), 3);
    }

    #[test]
    fn scaling_repeats_each_source_pixel() {
        let src = [1, 2, 3, 4];
        let mut dst = vec![0u32; 16];
        scale_nearest(&src, 2, 2, 2, &mut dst);
        assert_eq!(dst, [1, 1, 2, 2, 1, 1, 2, 2, 3, 3, 4, 4, 3, 3, 4, 4]);
    }

    #[test]
    fn bmp_has_headers_and_bottom_up_bgr_rows() {
        // 2x2 image: red, green / blue, white.
        let pixels = [0x00ff0000, 0x0000ff00, 0x000000ff, 0x00ffffff];
        let bmp = bmp_bytes(&pixels, 2, 2);
        assert_eq!(&bmp[0..2], b"BM");
        assert_eq!(u32::from_le_bytes(bmp[2..6].try_into().unwrap()), 70);
        assert_eq!(u32::from_le_bytes(bmp[10..14].try_into().unwrap()), 54);
        assert_eq!(u32::from_le_bytes(bmp[14..18].try_into().unwrap()), 40);
        assert_eq!(i32::from_le_bytes(bmp[18..22].try_into().unwrap()), 2);
        assert_eq!(i32::from_le_bytes(bmp[22..26].try_into().unwrap()), 2);
        assert_eq!(u16::from_le_bytes(bmp[26..28].try_into().unwrap()), 1);
        assert_eq!(u16::from_le_bytes(bmp[28..30].try_into().unwrap()), 24);
        // Bottom row first: blue then white, then two padding bytes.
        assert_eq!(
            &bmp[54..70],
            &[
                0xff, 0x00, 0x00, 0xff, 0xff, 0xff, 0, 0, 0x00, 0x00, 0xff, 0x00, 0xff, 0x00, 0, 0
            ]
        );
    }
}
