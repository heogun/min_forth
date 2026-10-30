use std::io::{self, IsTerminal, Read, Write};
use std::path::PathBuf;
use std::sync::mpsc::{self, TryRecvError};
use std::thread;
use std::time::{Duration, Instant};

use minredux::pacing::RealtimePacer;
use minredux::{ControlRom, Images, InputMode, Machine};

const DEFAULT_ROM_DIR: &str = "../roms/redux-1.4-isa-fixes-v1";

fn usage() {
    eprintln!(
        "minredux - microcode-driven Minimal 64x4 Revision 1.4 (Redux) emulator

USAGE:
    minredux run  [OPTIONS]
    minredux bench [OPTIONS]
    minredux term [OPTIONS]

The `term` command is an interactive frontend: it renders the 50x30 text
screen into the host terminal and forwards keystrokes to the UART.
Press Ctrl-] to quit.

OPTIONS:
    --rom-dir <DIR>   directory with flash.bin and ctrl_*.bin
                      (default: {DEFAULT_ROM_DIR})
    --cycles <N>      number of clocks to execute
                      (run default: 20000000, bench default: 200000000)
    --uart-hex <HEX>  feed bytes to the UART receiver (e.g. 4d494e0a)
    --uart-file <F>   feed a binary/text file to the UART receiver
    --uart-log        log UART deliveries and reads
    --uart-after <N>  start delivering UART input at cycle N
                       (use ~200000 to wait for the MinOS banner)
    --input-mode <M>  buffered (default, lossless helper) or timed (frame timing/loss)
    --ps2-frame-cycles <N> PS/2 frame duration in timed mode (default 16000)
    --ps2-hex <HEX>   feed bytes to the PS/2 keyboard register
    --ascii           render the visible VRAM region as ASCII
    --cols <N>        ASCII columns (default 100)
    --rows <N>        ASCII rows (default 30)
    --trace <N>       print the first N executed clocks
    --skip <N>        run N clocks before tracing
    --no-output       discard UART output (faster benchmarks)
    --stats           print cycle count and speed
    --dump            print final CPU registers
    --dump-mem A:L    hex dump RAM at address A (hex) for L bytes
    --dump-ram FILE   write the full 64 KiB RAM image to FILE
    --text            print the decoded 50x30 text screen
    --until-text STR  stop once STR appears on the text screen
    --poll N          text-screen poll interval for --until-text (default 65536)
    --crop X,Y,W,H    VRAM crop used by --ascii (default 96,12,400,240)
    --profile         report the hottest program counters
    --realtime        throttle execution to 8 MHz (run/bench/term; default unthrottled)
    -h, --help        show this help
"
    );
}

fn parse_hex(s: &str) -> Result<Vec<u8>, String> {
    let s: String = s.chars().filter(|c| !c.is_ascii_whitespace()).collect();
    if s.len() & 1 != 0 {
        return Err("hex string has odd length".into());
    }
    let mut v = Vec::with_capacity(s.len() / 2);
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        let hi = (b[i] as char).to_digit(16).ok_or("bad hex digit")?;
        let lo = (b[i + 1] as char).to_digit(16).ok_or("bad hex digit")?;
        v.push((hi * 16 + lo) as u8);
        i += 2;
    }
    Ok(v)
}

struct Options {
    rom_dir: PathBuf,
    cycles: u64,
    uart_hex: Option<String>,
    uart_file: Option<PathBuf>,
    ps2_hex: Option<String>,
    ascii: bool,
    cols: usize,
    rows: usize,
    trace: usize,
    skip: u64,
    no_output: bool,
    stats: bool,
    bench: bool,
    dump: bool,
    profile: bool,
    dump_mem: Vec<(u16, usize)>,
    dump_ram: Option<PathBuf>,
    crop: Option<(usize, usize, usize, usize)>,
    text: bool,
    until_text: Option<String>,
    poll: u64,
    uart_log: bool,
    uart_after: u64,
    term: bool,
    input_mode: InputMode,
    ps2_frame_cycles: u32,
    realtime: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            rom_dir: PathBuf::from(DEFAULT_ROM_DIR),
            cycles: 20_000_000,
            uart_hex: None,
            uart_file: None,
            ps2_hex: None,
            ascii: false,
            cols: 100,
            rows: 30,
            trace: 0,
            skip: 0,
            no_output: false,
            stats: false,
            bench: false,
            dump: false,
            profile: false,
            dump_mem: Vec::new(),
            dump_ram: None,
            crop: None,
            text: false,
            until_text: None,
            poll: 65536,
            uart_log: false,
            uart_after: 0,
            term: false,
            input_mode: InputMode::Buffered,
            ps2_frame_cycles: minredux::PS2_RX_PACE,
            realtime: false,
        }
    }
}

fn parse_args() -> Result<Options, String> {
    let mut o = Options::default();
    let mut args = std::env::args().skip(1);
    let cmd = args.next().ok_or("missing command (run or bench)")?;
    match cmd.as_str() {
        "run" => {}
        "term" => {
            o.term = true;
            o.cycles = u64::MAX;
        }
        "bench" => {
            o.bench = true;
            o.cycles = 200_000_000;
            o.no_output = true;
        }
        "-h" | "--help" => {
            usage();
            std::process::exit(0);
        }
        other => return Err(format!("unknown command: {other}")),
    }
    while let Some(a) = args.next() {
        match a.as_str() {
            "--rom-dir" => o.rom_dir = PathBuf::from(args.next().ok_or("--rom-dir needs a value")?),
            "--cycles" => {
                o.cycles = args
                    .next()
                    .ok_or("--cycles needs a value")?
                    .parse()
                    .map_err(|_| "bad --cycles value")?
            }
            "--uart-hex" => o.uart_hex = Some(args.next().ok_or("--uart-hex needs a value")?),
            "--uart-file" => {
                o.uart_file = Some(PathBuf::from(
                    args.next().ok_or("--uart-file needs a value")?,
                ))
            }
            "--ps2-hex" => o.ps2_hex = Some(args.next().ok_or("--ps2-hex needs a value")?),
            "--input-mode" => {
                o.input_mode = match args.next().as_deref() {
                    Some("buffered") => InputMode::Buffered,
                    Some("timed") => InputMode::Timed,
                    _ => return Err("--input-mode needs buffered or timed".into()),
                };
            }
            "--ps2-frame-cycles" => {
                o.ps2_frame_cycles = args
                    .next()
                    .ok_or("--ps2-frame-cycles needs a value")?
                    .parse()
                    .map_err(|_| "bad --ps2-frame-cycles value")?;
                if o.ps2_frame_cycles == 0 {
                    return Err("PS/2 frame duration must be positive".into());
                }
            }
            "--ascii" => o.ascii = true,
            "--cols" => {
                o.cols = args
                    .next()
                    .ok_or("--cols needs a value")?
                    .parse()
                    .map_err(|_| "bad --cols value")?
            }
            "--rows" => {
                o.rows = args
                    .next()
                    .ok_or("--rows needs a value")?
                    .parse()
                    .map_err(|_| "bad --rows value")?
            }
            "--trace" => {
                o.trace = args
                    .next()
                    .ok_or("--trace needs a value")?
                    .parse()
                    .map_err(|_| "bad --trace value")?
            }
            "--skip" => {
                o.skip = args
                    .next()
                    .ok_or("--skip needs a value")?
                    .parse()
                    .map_err(|_| "bad --skip value")?
            }
            "--no-output" => o.no_output = true,
            "--stats" => o.stats = true,
            "--realtime" => o.realtime = true,
            "--dump" => o.dump = true,
            "--profile" => o.profile = true,
            "--crop" => {
                let v = args.next().ok_or("--crop needs x,y,w,h")?;
                let p: Vec<&str> = v.split(',').collect();
                if p.len() != 4 {
                    return Err("--crop needs x,y,w,h".into());
                }
                let mut n = [0usize; 4];
                for (i, s) in p.iter().enumerate() {
                    n[i] = s.parse().map_err(|_| "bad --crop value")?;
                }
                o.crop = Some((n[0], n[1], n[2].max(1), n[3].max(1)));
            }
            "--dump-mem" => {
                let v = args.next().ok_or("--dump-mem needs addr:len")?;
                let (a, l) = v.split_once(':').ok_or("--dump-mem needs addr:len")?;
                let addr = u16::from_str_radix(a.trim_start_matches("0x"), 16)
                    .map_err(|_| "bad --dump-mem address")?;
                let len: usize = l
                    .trim_start_matches("0x")
                    .parse()
                    .or_else(|_| usize::from_str_radix(l, 16))
                    .map_err(|_| "bad --dump-mem length")?;
                o.dump_mem.push((addr, len));
            }
            "--dump-ram" => {
                o.dump_ram = Some(PathBuf::from(args.next().ok_or("--dump-ram needs a path")?))
            }
            "--text" => o.text = true,
            "--uart-log" => o.uart_log = true,
            "--uart-after" => {
                o.uart_after = args
                    .next()
                    .ok_or("--uart-after needs a value")?
                    .parse()
                    .map_err(|_| "bad --uart-after value")?
            }
            "--until-text" => o.until_text = Some(args.next().ok_or("--until-text needs a value")?),
            "--poll" => {
                o.poll = args
                    .next()
                    .ok_or("--poll needs a value")?
                    .parse()
                    .map_err(|_| "bad --poll value")?
            }
            "-h" | "--help" => {
                usage();
                std::process::exit(0);
            }
            other => return Err(format!("unknown option: {other}")),
        }
    }
    Ok(o)
}

fn signal_names(w: u32) -> String {
    const NAMES: [(&str, u32); 24] = [
        ("BO", minredux::BO),
        ("EC", minredux::EC),
        ("ES", minredux::ES),
        ("EO", minredux::EO),
        ("IC", minredux::IC),
        ("II", minredux::II),
        ("FI", minredux::FI),
        ("IO", minredux::IO),
        ("MC", minredux::MC),
        ("CIH", minredux::CIH),
        ("CE", minredux::CE),
        ("BI", minredux::BI),
        ("AI", minredux::AI),
        ("AO", minredux::AO),
        ("COH", minredux::COH),
        ("COL", minredux::COL),
        ("MIL", minredux::MIL),
        ("MIH", minredux::MIH),
        ("ME", minredux::ME),
        ("CIL", minredux::CIL),
        ("MZ", minredux::MZ),
        ("RO", minredux::RO),
        ("NI", minredux::NI),
        ("RI", minredux::RI),
    ];
    let mut s = String::new();
    for (name, bit) in NAMES {
        if (w & bit) != 0 {
            if !s.is_empty() {
                s.push('|');
            }
            s.push_str(name);
        }
    }
    if s.is_empty() {
        s.push('0');
    }
    s
}

struct RawTerm {
    saved: Option<String>,
}

impl RawTerm {
    fn enter() -> Self {
        if !io::stdin().is_terminal() {
            return Self { saved: None };
        }
        // `output()` gives the child a null stdin, so stty would not see the
        // terminal; it must inherit our stdin explicitly.
        let saved = std::process::Command::new("stty")
            .arg("-g")
            .stdin(std::process::Stdio::inherit())
            .output()
            .ok()
            .filter(|o| o.status.success())
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string());
        if saved.is_some() {
            let _ = std::process::Command::new("stty")
                .args(["raw", "-echo"])
                .stdin(std::process::Stdio::inherit())
                .status();
        }
        Self { saved }
    }
}

impl Drop for RawTerm {
    fn drop(&mut self) {
        if let Some(s) = &self.saved {
            let _ = std::process::Command::new("stty").arg(s).status();
        }
        print!("\x1b[?25h\r\n");
        let _ = io::stdout().flush();
    }
}

fn paint_screen(m: &Machine, prev: &mut [String], cursor: &mut (u8, u8)) {
    let screen = m.text_screen();
    let mut body = String::new();
    for (row, line) in screen.lines().enumerate() {
        if row >= prev.len() {
            break;
        }
        if prev[row] != line {
            body.push_str(&format!("\x1b[{};1H{}\x1b[K", row + 1, line));
            prev[row].clear();
            prev[row].push_str(line);
        }
    }
    let x = m.peek_ram(0xc0).min(49);
    let y = m.peek_ram(0xc1).min(29);
    if body.is_empty() && *cursor == (x, y) {
        return;
    }
    let mut out = String::with_capacity(body.len() + 32);
    out.push_str("\x1b[?25l");
    out.push_str(&body);
    out.push_str(&format!("\x1b[{};{}H\x1b[?25h", y + 1, x + 1));
    *cursor = (x, y);
    print!("{out}");
    let _ = io::stdout().flush();
}

fn run_terminal(mut m: Machine, realtime: bool) {
    let _raw = RawTerm::enter();
    let (tx, rx) = mpsc::channel::<u8>();
    thread::spawn(move || {
        let stdin = io::stdin();
        let mut handle = stdin.lock();
        let mut buf = [0u8; 1];
        loop {
            match handle.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if tx.send(buf[0]).is_err() {
                        break;
                    }
                }
            }
        }
    });

    m.collect_output = false;
    // Wait for the MinOS banner before accepting input; early bytes would be
    // consumed by the boot sequence instead of the line editor.
    m.uart_after = m.uart_after.max(200_000);
    let mut prev = vec![String::new(); 30];
    let mut cursor = (0xff, 0xff);
    let mut cooldown: Option<Instant> = None;
    let mut last_paint = Instant::now() - Duration::from_secs(1);
    let pacer = realtime.then(|| RealtimePacer::new(m.cycles));
    // Clear the host screen once; afterwards only changed rows are redrawn.
    print!("\x1b[2J\x1b[H\x1b[?25l");
    let _ = io::stdout().flush();

    loop {
        let mut eof = false;
        loop {
            match rx.try_recv() {
                Ok(0x1d) => return, // Ctrl-]
                Ok(b) => m.feed_uart([b]),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    eof = true;
                    break;
                }
            }
        }
        if eof && !m.input_pending() {
            // Give the machine a moment to finish the piped input, then quit.
            cooldown.get_or_insert_with(Instant::now);
            if cooldown.unwrap().elapsed() >= Duration::from_secs(1) {
                return;
            }
        }
        m.run_cycles(2_000);
        if let Some(pacer) = &pacer {
            pacer.wait(m.cycles);
        }
        if last_paint.elapsed() >= Duration::from_millis(40) {
            paint_screen(&m, &mut prev, &mut cursor);
            last_paint = Instant::now();
        }
    }
}

fn advance(
    m: &mut Machine,
    clocks: u64,
    profile: bool,
    counts: &mut [u64],
    pacer: Option<&RealtimePacer>,
) {
    let mut remaining = clocks;
    while remaining != 0 {
        // At most 1 ms of virtual time between host-throttle checkpoints.
        let chunk = if pacer.is_some() {
            remaining.min(8_000)
        } else {
            remaining
        };
        if profile {
            for _ in 0..chunk {
                counts[m.pc as usize] += 1;
                m.step();
            }
        } else {
            m.run_cycles(chunk);
        }
        if let Some(pacer) = pacer {
            pacer.wait(m.cycles);
        }
        remaining -= chunk;
    }
}

fn main() {
    let opts = match parse_args() {
        Ok(o) => o,
        Err(e) => {
            eprintln!("error: {e}");
            usage();
            std::process::exit(2);
        }
    };

    let images = match Images::load(&opts.rom_dir) {
        Ok(i) => i,
        Err(e) => {
            eprintln!("failed to load images from {}: {e}", opts.rom_dir.display());
            std::process::exit(1);
        }
    };

    let ctrl = match ControlRom::from_images(&images) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("invalid control ROM: {e}");
            std::process::exit(1);
        }
    };

    let mut m = Machine::new(ctrl, images.flash);
    m.collect_output = !opts.no_output;
    m.uart_after = opts.uart_after;
    m.input_mode = opts.input_mode;
    m.ps2_frame_cycles = opts.ps2_frame_cycles;

    if let Some(file) = &opts.uart_file {
        match std::fs::read(file) {
            Ok(bytes) => m.feed_uart(bytes),
            Err(e) => {
                eprintln!("failed to read {}: {e}", file.display());
                std::process::exit(1);
            }
        }
    }
    if let Some(hex) = &opts.uart_hex {
        match parse_hex(hex) {
            Ok(bytes) => m.feed_uart(bytes),
            Err(e) => {
                eprintln!("bad --uart-hex: {e}");
                std::process::exit(1);
            }
        }
    }
    if let Some(hex) = &opts.ps2_hex {
        match parse_hex(hex) {
            Ok(bytes) => m.feed_ps2(bytes),
            Err(e) => {
                eprintln!("bad --ps2-hex: {e}");
                std::process::exit(1);
            }
        }
    }

    if opts.term {
        run_terminal(m, opts.realtime);
        return;
    }

    let trace = opts.trace.min(opts.cycles as usize);
    if opts.skip > 0 {
        m.run_cycles(opts.skip);
    }
    let start = Instant::now();
    let start_cycles = m.cycles;
    let pacer = opts.realtime.then(|| RealtimePacer::new(m.cycles));
    m.trace_io = opts.uart_log;
    let mut pc_counts = vec![0u64; 0x10000];
    for i in 0..trace {
        let w = m.control_word();
        println!(
            "{:>8} pc={:04x} mar={:04x} a={:02x} b={:02x} bank={:02x} ir={:02x} sc={:2} fr={:02x} f={:02x} w={:06x} {}",
            i,
            m.pc,
            m.mar,
            m.ar,
            m.br,
            m.bank,
            m.ir,
            m.sc,
            m.fr,
            m.flags,
            w,
            signal_names(w)
        );
        if opts.profile {
            pc_counts[m.pc as usize] += 1;
        }
        m.step();
        if let Some(pacer) = &pacer {
            pacer.wait(m.cycles);
        }
    }
    let remaining = opts.cycles.saturating_sub(trace as u64);
    if let Some(needle) = &opts.until_text {
        // Poll the text screen every `poll` clocks.  The screen decode is
        // comparatively expensive, so keep chunks reasonably large.
        let poll = opts.poll.max(1);
        let mut done = 0u64;
        loop {
            let chunk = poll.min(remaining - done);
            advance(&mut m, chunk, opts.profile, &mut pc_counts, pacer.as_ref());
            done += chunk;
            let found = m.text_screen().contains(needle.as_str());
            if found || done >= remaining {
                break;
            }
        }
    } else {
        advance(
            &mut m,
            remaining,
            opts.profile,
            &mut pc_counts,
            pacer.as_ref(),
        );
    }
    let elapsed = start.elapsed();

    if !m.uart_out.is_empty() {
        // UART output is raw bytes; write them through unchanged so ANSI
        // sequences and binary payloads survive.
        let stdout = io::stdout();
        let mut lock = stdout.lock();
        let _ = lock.write_all(&m.uart_out);
        let _ = lock.flush();
        if !m.uart_out.ends_with(b"\n") {
            eprintln!();
        }
    }

    if opts.ascii {
        let s = match opts.crop {
            Some(c) => minredux::render_ascii_crop(&m, opts.cols, opts.rows, c),
            None => minredux::render_ascii(&m, opts.cols, opts.rows),
        };
        eprintln!("{s}");
    }

    if opts.text {
        println!("{}", m.text_screen());
    }

    for &(addr, len) in &opts.dump_mem {
        eprintln!("memory {addr:04x}:{len}:");
        let mut a = addr;
        for i in (0..len).step_by(16) {
            let n = (len - i).min(16);
            let mut line = format!("  {:04x}:", a);
            for j in 0..n {
                line.push_str(&format!(" {:02x}", m.peek_ram(a.wrapping_add(j as u16))));
            }
            eprintln!("{line}");
            a = a.wrapping_add(n as u16);
        }
    }

    if let Some(path) = &opts.dump_ram {
        match std::fs::write(path, m.ram()) {
            Ok(()) => eprintln!("wrote RAM dump to {}", path.display()),
            Err(e) => eprintln!("failed to write {}: {e}", path.display()),
        }
    }

    if opts.uart_log {
        for (c, k, b) in &m.io_events {
            eprintln!("io {c:>12} {k} {b:02x}");
        }
    }

    if opts.dump {
        let w = m.control_word();
        let (pending, rx, busy) = m.uart_status();
        eprintln!(
            "FINAL pc={:04x} mar={:04x} bank={:02x} a={:02x} b={:02x} ir={:02x} sc={} fr={:02x} flags={:02x} w={:06x} {} uart_pending={} uart_rx={:02x} tx_busy={}",
            m.pc,
            m.mar,
            m.bank,
            m.ar,
            m.br,
            m.ir,
            m.sc,
            m.fr,
            m.flags,
            w,
            signal_names(w),
            pending,
            rx,
            busy
        );
    }

    if opts.profile {
        let mut v: Vec<(u64, usize)> = pc_counts
            .iter()
            .enumerate()
            .filter(|(_, c)| **c > 0)
            .map(|(a, &c)| (c, a))
            .collect();
        v.sort_unstable_by(|a, b| b.cmp(a));
        eprintln!("top PCs:");
        for (count, pc) in v.into_iter().take(20) {
            eprintln!("  {count:>12}  pc={pc:04x}");
        }
    }

    if opts.stats || opts.bench {
        eprintln!(
            "input_mode={:?} uart_dropped={} ps2_dropped={}",
            m.input_mode, m.uart_dropped, m.ps2_dropped
        );
        eprintln!(
            "video_frames={} vreg_overwrites={} flash_busy_cycles={}",
            m.video.frames,
            m.video.overwritten_writes,
            m.flash_busy_cycles()
        );
        let secs = elapsed.as_secs_f64();
        let mhz = (m.cycles - start_cycles) as f64 / secs / 1e6;
        eprintln!(
            "cycles={} elapsed={:.3}s speed={:.1} MHz ({:.2}x realtime) out={}B",
            m.cycles,
            secs,
            mhz,
            mhz / 8.0,
            m.uart_out.len()
        );
    }
}
