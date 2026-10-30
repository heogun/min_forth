//! Local validation of the native MinOS smoke programs submitted upstream.
use minredux::{ControlRom, Images, Machine};
use std::env;

fn main() {
    let args: Vec<_> = env::args().skip(1).collect();
    assert_eq!(args.len(), 3, "usage: rom_smoke ROM_DIR xor|win PASS|FAIL");
    let images = Images::load(&args[0]).unwrap();
    let mut m = Machine::new(ControlRom::from_images(&images).unwrap(), images.flash);
    m.uart_after = 200_000;
    m.collect_output = false;
    let win = args[1] == "win";
    assert!(win || args[1] == "xor");
    let input = if win { b"wincheck\n" } else { b"xorcheck\n" };
    m.feed_uart(input.iter().copied());
    if win {
        while !(m.pc == 0xffff && m.sc == 0 && m.bank == 0xff) {
            assert!(m.cycles < 2_000_000, "did not reach ffff WIN");
            m.step();
        }
        assert_eq!(m.uart_status(), (0, 0xff, 0));
        m.run_cycles(18);
        assert_eq!((m.pc, m.mar, m.sc), (0xffff, 0xffff, 0));
        m.feed_uart([0x61]);
    }
    m.run_cycles(400_000);
    let screen = m.text_screen();
    assert!(screen.contains(&format!("{}:", args[2])), "{screen}");
    let other = if args[2] == "PASS" { "FAIL:" } else { "PASS:" };
    assert!(!screen.contains(other), "{screen}");
    println!("{} smoke: {}\n{screen}", args[1], args[2]);
}
