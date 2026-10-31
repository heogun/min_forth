//! Host keyboard to MinOS UART byte mapping.
//!
//! MinOS `OS_ReadLine` expects LF (`0x0a`) for Enter and `0x08` for
//! Backspace.  Host terminal frontends often send CR (`0x0d`) and DEL
//! (`0x7f`) instead, which is why this windowed frontend translates keys
//! explicitly rather than forwarding terminal bytes.

use minifb::Key;

/// Translate one key press into an ASCII byte for the guest UART.
///
/// Modifier keys, arrow keys, and function keys return `None`.  Ctrl+letter
/// produces the conventional C0 control code (Ctrl+A = `0x01`).
pub fn key_to_byte(key: Key, shift: bool, ctrl: bool, caps: bool) -> Option<u8> {
    let letter = |lower: u8| {
        if ctrl {
            Some(lower - b'a' + 1)
        } else if shift ^ caps {
            Some(lower.to_ascii_uppercase())
        } else {
            Some(lower)
        }
    };

    let digit = |base: u8, shifted: u8| Some(if shift { shifted } else { base });

    match key {
        Key::Enter | Key::NumPadEnter => Some(0x0a),
        Key::Backspace => Some(0x08),
        // GUI keyboards label the main delete key "Backspace" and the other
        // one "Delete"; both are line-editing deletes for MinOS.
        Key::Delete => Some(0x08),
        Key::Tab => Some(0x09),
        Key::Escape => Some(0x1b),
        Key::Space => Some(b' '),

        Key::A => letter(b'a'),
        Key::B => letter(b'b'),
        Key::C => letter(b'c'),
        Key::D => letter(b'd'),
        Key::E => letter(b'e'),
        Key::F => letter(b'f'),
        Key::G => letter(b'g'),
        Key::H => letter(b'h'),
        Key::I => letter(b'i'),
        Key::J => letter(b'j'),
        Key::K => letter(b'k'),
        Key::L => letter(b'l'),
        Key::M => letter(b'm'),
        Key::N => letter(b'n'),
        Key::O => letter(b'o'),
        Key::P => letter(b'p'),
        Key::Q => letter(b'q'),
        Key::R => letter(b'r'),
        Key::S => letter(b's'),
        Key::T => letter(b't'),
        Key::U => letter(b'u'),
        Key::V => letter(b'v'),
        Key::W => letter(b'w'),
        Key::X => letter(b'x'),
        Key::Y => letter(b'y'),
        Key::Z => letter(b'z'),

        Key::Key0 => digit(b'0', b')'),
        Key::Key1 => digit(b'1', b'!'),
        Key::Key2 => digit(b'2', b'@'),
        Key::Key3 => digit(b'3', b'#'),
        Key::Key4 => digit(b'4', b'$'),
        Key::Key5 => digit(b'5', b'%'),
        Key::Key6 => digit(b'6', b'^'),
        Key::Key7 => digit(b'7', b'&'),
        Key::Key8 => digit(b'8', b'*'),
        Key::Key9 => digit(b'9', b'('),

        Key::Apostrophe => Some(if shift { b'"' } else { b'\'' }),
        Key::Backquote => Some(if shift { b'~' } else { b'`' }),
        Key::Backslash => Some(if shift { b'|' } else { b'\\' }),
        Key::Comma => Some(if shift { b'<' } else { b',' }),
        Key::Equal => Some(if shift { b'+' } else { b'=' }),
        Key::LeftBracket => Some(if shift { b'{' } else { b'[' }),
        Key::Minus => Some(if shift { b'_' } else { b'-' }),
        Key::Period => Some(if shift { b'>' } else { b'.' }),
        Key::RightBracket => Some(if shift { b'}' } else { b']' }),
        Key::Semicolon => Some(if shift { b':' } else { b';' }),
        Key::Slash => Some(if shift { b'?' } else { b'/' }),

        Key::NumPad0 => Some(b'0'),
        Key::NumPad1 => Some(b'1'),
        Key::NumPad2 => Some(b'2'),
        Key::NumPad3 => Some(b'3'),
        Key::NumPad4 => Some(b'4'),
        Key::NumPad5 => Some(b'5'),
        Key::NumPad6 => Some(b'6'),
        Key::NumPad7 => Some(b'7'),
        Key::NumPad8 => Some(b'8'),
        Key::NumPad9 => Some(b'9'),
        Key::NumPadDot => Some(b'.'),
        Key::NumPadSlash => Some(b'/'),
        Key::NumPadAsterisk => Some(b'*'),
        Key::NumPadMinus => Some(b'-'),
        Key::NumPadPlus => Some(b'+'),

        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enter_and_backspace_match_minos_line_editor() {
        assert_eq!(key_to_byte(Key::Enter, false, false, false), Some(0x0a));
        assert_eq!(
            key_to_byte(Key::NumPadEnter, false, false, false),
            Some(0x0a)
        );
        assert_eq!(key_to_byte(Key::Backspace, false, false, false), Some(0x08));
        assert_eq!(key_to_byte(Key::Delete, false, false, false), Some(0x08));
    }

    #[test]
    fn letters_respect_shift_and_caps() {
        assert_eq!(key_to_byte(Key::A, false, false, false), Some(b'a'));
        assert_eq!(key_to_byte(Key::A, true, false, false), Some(b'A'));
        assert_eq!(key_to_byte(Key::A, false, false, true), Some(b'A'));
        assert_eq!(key_to_byte(Key::A, true, false, true), Some(b'a'));
        assert_eq!(key_to_byte(Key::Z, false, false, true), Some(b'Z'));
    }

    #[test]
    fn shifted_punctuation_and_keypad() {
        assert_eq!(key_to_byte(Key::Key1, false, false, false), Some(b'1'));
        assert_eq!(key_to_byte(Key::Key1, true, false, false), Some(b'!'));
        assert_eq!(key_to_byte(Key::Key0, true, false, false), Some(b')'));
        assert_eq!(key_to_byte(Key::Semicolon, true, false, false), Some(b':'));
        assert_eq!(key_to_byte(Key::Slash, true, false, false), Some(b'?'));
        assert_eq!(key_to_byte(Key::NumPad7, false, false, false), Some(b'7'));
        assert_eq!(
            key_to_byte(Key::NumPadPlus, false, false, false),
            Some(b'+')
        );
    }

    #[test]
    fn ctrl_letters_become_control_codes() {
        assert_eq!(key_to_byte(Key::C, false, true, false), Some(0x03));
        assert_eq!(key_to_byte(Key::A, true, true, false), Some(0x01));
    }

    #[test]
    fn modifiers_and_navigation_are_not_text() {
        for key in [
            Key::LeftShift,
            Key::RightShift,
            Key::LeftCtrl,
            Key::CapsLock,
            Key::Left,
            Key::Right,
            Key::Up,
            Key::Down,
            Key::F5,
        ] {
            assert_eq!(key_to_byte(key, false, false, false), None);
        }
    }
}
