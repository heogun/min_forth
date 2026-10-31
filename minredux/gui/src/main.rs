//! Windowed monochrome frontend for the Minimal 64x4 Revision 1.4 Redux
//! emulator.  It renders the real 400x240 VRAM viewport and feeds typed keys
//! to the guest UART, avoiding host terminal encoding and CR/DEL issues.

mod frame;
mod input;

use std::path::{Path, PathBuf};

use minifb::{Key, KeyRepeat, Scale, Window, WindowOptions};
use minredux::video::FRAME_CPU_CYCLES;
use minredux::{ControlRom, Images, Machine};

use frame::{Palette, SCREEN_HEIGHT, SCREEN_WIDTH};

const TARGET_FPS: usize = 60;

fn default_rom_dir() -> PathBuf {
    const REL: &str = "minimal64/Revision 1.4 Redux/FLASH Images";
    // Accept running from minredux/gui (cargo run), minredux, or the
    // workspace root, since cargo keeps the caller's working directory.
    for base in ["../..", "..", "."] {
        let candidate = Path::new(base).join(REL);
        if candidate.is_dir() {
            return candidate;
        }
    }
    Path::new("../..").join(REL)
}

fn usage() {
    eprintln!(
        "minredux-gui - windowed monochrome Minimal 64x4 Revision 1.4 (Redux)

USAGE:
    minredux-gui [OPTIONS]

The window shows the 400x240 VRAM viewport.  Typed characters go directly to
the guest UART.  Enter is sent as LF (0x0a) and Backspace as 0x08, matching
MinOS.  F5 resets the CPU; close the window to quit.

OPTIONS:
    --rom-dir <DIR>     directory with flash.bin and ctrl_*.bin
                        (default: auto-detect the installed Redux images)
    --scale <N>         integer window scale, 1..=8 (default: 3)
    --speed <X>         emulated speed multiplier at 60 fps (default: 1.0)
    --fg <RRGGBB>       foreground colour (default: e8e8e8)
    --bg <RRGGBB>       background colour (default: 000000)
    --frames <N>        stop after N frames, useful with --screenshot
    --screenshot <FILE> write the final frame as a 24-bit BMP
    --headless          do not open a window; requires --frames
    --text              print the decoded 50x30 text screen at exit
    --uart-hex <HEX>    preload bytes for the UART receiver (e.g. 6d696e666f7274680a)
    --uart-after <N>    deliver UART input after N clocks (default: 200000)
    -h, --help          show this help
"
    );
}

struct Options {
    rom_dir: PathBuf,
    scale: usize,
    speed: f64,
    palette: Palette,
    frames: Option<u64>,
    screenshot: Option<PathBuf>,
    headless: bool,
    text: bool,
    uart_hex: Option<String>,
    uart_after: u64,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            rom_dir: default_rom_dir(),
            scale: 3,
            speed: 1.0,
            palette: Palette::default(),
            frames: None,
            screenshot: None,
            headless: false,
            text: false,
            uart_hex: None,
            uart_after: 200_000,
        }
    }
}

fn parse_color(value: &str) -> Result<u32, String> {
    let s = value.trim();
    let s = s.strip_prefix('#').unwrap_or(s);
    let s = s.strip_prefix("0x").unwrap_or(s);
    if s.len() != 6 {
        return Err(format!("colour needs six hex digits: {value}"));
    }
    u32::from_str_radix(s, 16).map_err(|_| format!("bad colour: {value}"))
}

fn parse_hex(s: &str) -> Result<Vec<u8>, String> {
    let s: String = s.chars().filter(|c| !c.is_ascii_whitespace()).collect();
    if s.len() & 1 != 0 {
        return Err("hex string has odd length".into());
    }
    let mut bytes = Vec::with_capacity(s.len() / 2);
    let digits = s.as_bytes();
    let mut i = 0;
    while i < digits.len() {
        let hi = (digits[i] as char).to_digit(16).ok_or("bad hex digit")?;
        let lo = (digits[i + 1] as char)
            .to_digit(16)
            .ok_or("bad hex digit")?;
        bytes.push((hi * 16 + lo) as u8);
        i += 2;
    }
    Ok(bytes)
}

fn parse_args() -> Result<Options, String> {
    let mut opts = Options::default();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--rom-dir" => {
                opts.rom_dir = PathBuf::from(args.next().ok_or("--rom-dir needs a value")?)
            }
            "--scale" => {
                opts.scale = args
                    .next()
                    .ok_or("--scale needs a value")?
                    .parse()
                    .map_err(|_| "bad --scale value")?;
                if !(1..=8).contains(&opts.scale) {
                    return Err("--scale must be between 1 and 8".into());
                }
            }
            "--speed" => {
                opts.speed = args
                    .next()
                    .ok_or("--speed needs a value")?
                    .parse()
                    .map_err(|_| "bad --speed value")?;
                if !opts.speed.is_finite() || !(0.05..=32.0).contains(&opts.speed) {
                    return Err("--speed must be between 0.05 and 32".into());
                }
            }
            "--fg" => opts.palette.fg = parse_color(&args.next().ok_or("--fg needs a value")?)?,
            "--bg" => opts.palette.bg = parse_color(&args.next().ok_or("--bg needs a value")?)?,
            "--frames" => {
                let n: u64 = args
                    .next()
                    .ok_or("--frames needs a value")?
                    .parse()
                    .map_err(|_| "bad --frames value")?;
                if n == 0 {
                    return Err("--frames must be positive".into());
                }
                opts.frames = Some(n);
            }
            "--screenshot" => {
                opts.screenshot = Some(PathBuf::from(
                    args.next().ok_or("--screenshot needs a path")?,
                ))
            }
            "--headless" => opts.headless = true,
            "--text" => opts.text = true,
            "--uart-hex" => opts.uart_hex = Some(args.next().ok_or("--uart-hex needs a value")?),
            "--uart-after" => {
                opts.uart_after = args
                    .next()
                    .ok_or("--uart-after needs a value")?
                    .parse()
                    .map_err(|_| "bad --uart-after value")?
            }
            "-h" | "--help" => {
                usage();
                std::process::exit(0);
            }
            other => return Err(format!("unknown option: {other}")),
        }
    }
    Ok(opts)
}

fn load_machine(rom_dir: &Path) -> Result<Machine, String> {
    let images = Images::load(rom_dir).map_err(|e| {
        format!(
            "failed to load ROM images from {}: {e}\n\
             hint: pass --rom-dir pointing at the installed FLASH Images or minforth/build",
            rom_dir.display()
        )
    })?;
    let ctrl = ControlRom::from_images(&images).map_err(|e| format!("invalid control ROM: {e}"))?;
    Ok(Machine::new(ctrl, images.flash))
}

fn prepare_machine(opts: &Options) -> Result<Machine, String> {
    let mut machine = load_machine(&opts.rom_dir)?;
    machine.collect_output = false;
    machine.uart_after = opts.uart_after;
    if let Some(hex) = &opts.uart_hex {
        machine.feed_uart(parse_hex(hex).map_err(|e| format!("bad --uart-hex: {e}"))?);
    }
    Ok(machine)
}

fn cycles_per_frame(opts: &Options) -> Result<u64, String> {
    let cycles = (FRAME_CPU_CYCLES as f64 * opts.speed).round() as u64;
    if cycles == 0 {
        return Err("--speed is too small to advance a CPU clock per frame".into());
    }
    Ok(cycles)
}

fn finish(machine: &Machine, opts: &Options) -> Result<(), String> {
    if opts.text {
        print!("{}", machine.text_screen());
    }
    if let Some(path) = &opts.screenshot {
        let mut pixels = vec![0u32; SCREEN_WIDTH * SCREEN_HEIGHT];
        frame::render(machine.video.vram(), opts.palette, &mut pixels);
        let bmp = frame::bmp_bytes(&pixels, SCREEN_WIDTH, SCREEN_HEIGHT);
        std::fs::write(path, bmp)
            .map_err(|e| format!("failed to write screenshot {}: {e}", path.display()))?;
        eprintln!(
            "wrote {} ({}x{})",
            path.display(),
            SCREEN_WIDTH,
            SCREEN_HEIGHT
        );
    }
    Ok(())
}

fn run_headless(mut machine: Machine, opts: &Options) -> Result<(), String> {
    let frames = opts
        .frames
        .ok_or("--headless requires --frames N with N > 0")?;
    let cycles = cycles_per_frame(opts)?;
    for _ in 0..frames {
        machine.run_cycles(cycles);
    }
    finish(&machine, opts)
}

fn run_gui(mut machine: Machine, opts: &Options) -> Result<(), String> {
    let width = SCREEN_WIDTH * opts.scale;
    let height = SCREEN_HEIGHT * opts.scale;
    let mut window = Window::new(
        "minredux-gui - Minimal 64x4 (Redux)",
        width,
        height,
        WindowOptions {
            resize: false,
            scale: Scale::X1,
            ..WindowOptions::default()
        },
    )
    .map_err(|e| format!("failed to open window: {e}"))?;
    window.set_target_fps(TARGET_FPS);

    let cycles = cycles_per_frame(opts)?;
    let mut native = vec![0u32; SCREEN_WIDTH * SCREEN_HEIGHT];
    let mut scaled = vec![0u32; width * height];
    let mut caps = false;
    let mut frames = 0u64;

    while window.is_open() {
        let shift = window.is_key_down(Key::LeftShift) || window.is_key_down(Key::RightShift);
        let ctrl = window.is_key_down(Key::LeftCtrl) || window.is_key_down(Key::RightCtrl);
        for key in window.get_keys_pressed(KeyRepeat::Yes) {
            match key {
                Key::F5 => machine.reset(),
                Key::CapsLock => caps = !caps,
                _ => {
                    if let Some(byte) = input::key_to_byte(key, shift, ctrl, caps) {
                        machine.feed_uart([byte]);
                    }
                }
            }
        }

        machine.run_cycles(cycles);
        frame::render(machine.video.vram(), opts.palette, &mut native);
        frame::scale_nearest(
            &native,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            opts.scale,
            &mut scaled,
        );
        window
            .update_with_buffer(&scaled, width, height)
            .map_err(|e| format!("failed to update window: {e}"))?;

        frames += 1;
        if opts.frames.is_some_and(|limit| frames >= limit) {
            break;
        }
    }

    finish(&machine, opts)
}

fn main() {
    let opts = match parse_args() {
        Ok(opts) => opts,
        Err(e) => {
            eprintln!("error: {e}");
            usage();
            std::process::exit(2);
        }
    };

    let result = if opts.headless {
        prepare_machine(&opts).and_then(|machine| run_headless(machine, &opts))
    } else {
        prepare_machine(&opts).and_then(|machine| run_gui(machine, &opts))
    };
    if let Err(e) = result {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}
