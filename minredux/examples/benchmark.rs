//! Cycle-edge benchmark observer. No CPU or instruction semantics are patched.
use minredux::{ControlRom, Images, Machine};
use std::{env, fs, process};
#[path = "benchmark/profile.rs"]
mod profile;

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().skip(1).collect();
    if !(4..=5).contains(&args.len()) {
        return Err("usage: benchmark ROM_DIR UART_FILE RAM_OUT MAX_CYCLES [PROFILE_FILE]".into());
    }
    let images = Images::load(&args[0])?;
    let mut m = Machine::new(ControlRom::from_images(&images)?, images.flash);
    m.collect_output = false;
    m.uart_after = 200_000;
    m.feed_uart(fs::read(&args[1])?);
    let limit: u64 = args[3].parse()?;
    let mut start = None;
    let mut profile = args.get(4).map(profile::Profile::load).transpose()?;
    while m.cycles < limit {
        if let Some(profile) = &mut profile {
            profile.boundary(&m);
        }
        // Observe the fetch boundary, not a PC value passing through an operand.
        if m.sc == 0 && m.bank == 0xff {
            if m.pc == 0xdf00 {
                if m.peek_ram(0xdf00) != 0x6b || m.peek_ram(0xdf10) != 0x6b {
                    return Err("timing hook memory was overwritten".into());
                }
                if start
                    .replace((m.cycles, m.peek_ram(0), m.peek_ram(0xffff)))
                    .is_some()
                {
                    return Err("duplicate start hook".into());
                }
                if let Some(profile) = &mut profile {
                    profile.executing = true;
                }
            }
            if m.pc == 0xdf10 {
                let (begin, start_sp, start_rsp) = start.ok_or("end hook before start")?;
                fs::write(&args[2], m.ram().as_slice())?;
                let extra = profile
                    .as_ref()
                    .map(|p| format!(",{}", p.json()))
                    .unwrap_or_default();
                println!(
                    "{{\"start_cycle\":{begin},\"end_cycle\":{},\"raw_cycles\":{},\"start_data_sp\":{start_sp},\"data_sp\":{},\"start_return_sp\":{start_rsp},\"return_sp\":{}{extra}}}",
                    m.cycles,
                    m.cycles - begin,
                    m.peek_ram(0),
                    m.peek_ram(0xffff)
                );
                return Ok(());
            }
        }
        if let Some(profile) = &mut profile {
            profile.tick(&m);
        }
        m.step();
    }
    fs::write(&args[2], m.ram().as_slice())?;
    Err(format!(
        "timeout after {limit} cycles; start={start:?}, pc={:04x}\n{}",
        m.pc,
        m.text_screen()
    )
    .into())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("benchmark: {error}");
        process::exit(1);
    }
}
