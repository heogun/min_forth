//! Host-side observers only: never write guest memory or alter CPU execution.
use minredux_cs::{Machine, RI};
use std::{collections::BTreeMap, fs, io, path::Path};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Role {
    Input,
    NativeLoad,
    SourceLoad,
    MinTokens,
    Next,
    Parse,
    Find,
    Emit,
    CompileWord,
    SetupWord,
}

impl Role {
    fn name(self) -> &'static str {
        match self {
            Self::Input => "readline",
            Self::NativeLoad => "native_load",
            Self::SourceLoad => "source_load",
            Self::MinTokens => "min_tokenizer",
            Self::Next => "forth_next",
            Self::Parse => "forth_parse",
            Self::Find => "forth_find",
            Self::Emit => "forth_emit",
            Self::CompileWord => "compile_word",
            Self::SetupWord => "setup_word",
        }
    }
}

#[derive(Debug)]
struct Frame {
    role: Role,
    entry: u16,
    entry_sp: u8,
    return_pc: u16,
    return_sp: u8,
}

pub struct Profile {
    config: BTreeMap<String, u16>,
    forth: bool,
    active: bool,
    frames: Vec<Frame>,
    pub executing: bool,
    phases: BTreeMap<&'static str, u64>,
    components: BTreeMap<&'static str, u64>,
    calls: BTreeMap<&'static str, u64>,
    memory: BTreeMap<&'static str, u64>,
    events: BTreeMap<&'static str, u64>,
}

fn word(m: &Machine, address: u16) -> u16 {
    u16::from_le_bytes([m.peek_ram(address), m.peek_ram(address.wrapping_add(1))])
}

fn return_target(m: &Machine) -> (u16, u8) {
    let sp = m.peek_ram(0xffff);
    let high = m.peek_ram(0xff00 | sp.wrapping_add(1) as u16);
    let low = m.peek_ram(0xff00 | sp.wrapping_add(2) as u16);
    (
        u16::from_le_bytes([low, high]).wrapping_add(2),
        sp.wrapping_add(2),
    )
}

impl Profile {
    pub fn load(path: impl AsRef<Path>) -> io::Result<Self> {
        let mut config = BTreeMap::new();
        let mut forth = None;
        for line in fs::read_to_string(path)?.lines() {
            let (key, value) = line
                .split_once(' ')
                .ok_or_else(|| io::Error::other("invalid profile line"))?;
            if key == "language" {
                forth = match value {
                    "forth" => Some(true),
                    "min" => Some(false),
                    _ => return Err(io::Error::other("unknown profile language")),
                };
            } else {
                let n = u16::from_str_radix(value, 16).map_err(io::Error::other)?;
                if config.insert(key.to_owned(), n).is_some() {
                    return Err(io::Error::other("duplicate profile key"));
                }
            }
        }
        let forth = forth.ok_or_else(|| io::Error::other("missing profile language"))?;
        let common = [
            "prompt",
            "app_entry",
            "app_ready",
            "readline",
            "native_load",
            "code_bytes",
        ];
        let specific: &[&str] = if forth {
            &[
                "word",
                "next",
                "parse",
                "find",
                "emit",
                "state",
                "token",
                "token_len",
                "here",
                "data_sp",
                "loop_top",
            ]
        } else {
            &["loader", "tokenizer", "source_end_ptr", "token_end_ptr"]
        };
        if common
            .iter()
            .chain(specific.iter())
            .any(|key| !config.contains_key(*key))
        {
            return Err(io::Error::other("missing required profile symbol"));
        }
        let mut memory = BTreeMap::new();
        memory.insert("runtime_code_bytes", config["code_bytes"] as u64);
        Ok(Self {
            config,
            forth,
            active: false,
            frames: Vec::new(),
            executing: false,
            phases: [
                "boot",
                "application_boot",
                "input",
                "load",
                "tokenize",
                "compile",
                "setup_execute",
                "dispatch",
                "execute",
            ]
            .into_iter()
            .map(|key| (key, 0))
            .collect(),
            components: BTreeMap::new(),
            calls: BTreeMap::new(),
            memory,
            events: BTreeMap::new(),
        })
    }

    fn at(&self, name: &str, pc: u16) -> bool {
        self.config.get(name) == Some(&pc)
    }

    fn peak(&mut self, key: &'static str, n: u64) {
        let old = self.memory.entry(key).or_default();
        *old = (*old).max(n);
    }

    pub fn boundary(&mut self, m: &Machine) {
        if m.sc != 0 {
            return;
        }
        let sp = m.peek_ram(0xffff);
        if self.at("prompt", m.pc) {
            self.events
                .entry("minos_boot_end_cycle")
                .or_insert(m.cycles);
        }
        if !self.active && self.at("app_entry", m.pc) {
            self.active = true;
            self.events.insert("application_entry_cycle", m.cycles);
        }
        if self.active && self.at("app_ready", m.pc) {
            if !self.events.contains_key("application_ready_cycle") && self.forth {
                self.memory.insert(
                    "boot_dictionary_bytes",
                    word(m, self.config["here"]) as u64 - 0x8000,
                );
            }
            self.events
                .entry("application_ready_cycle")
                .or_insert(m.cycles);
        }
        while self
            .frames
            .last()
            .is_some_and(|f| f.return_pc == m.pc && f.return_sp == sp)
        {
            let frame = self.frames.pop().unwrap();
            if frame.role == Role::SourceLoad {
                self.memory.insert(
                    "source_bytes",
                    word(m, self.config["source_end_ptr"]) as u64 - 0x8000,
                );
            }
            if frame.role == Role::MinTokens {
                let start = word(m, self.config["source_end_ptr"]);
                let end = word(m, self.config["token_end_ptr"]);
                assert!(end >= start, "invalid Min token span");
                self.memory.insert("token_bytes", (end - start + 1) as u64);
                self.events.insert("tokenizer_return_cycle", m.cycles);
            }
        }
        let role = if self.at("readline", m.pc) {
            Some(Role::Input)
        } else if self.at("native_load", m.pc) {
            Some(Role::NativeLoad)
        } else if self.active && self.forth {
            if self.at("word", m.pc) {
                let len = m.peek_ram(self.config["token_len"]) as usize;
                let base = self.config["token"];
                let token: Vec<_> = (0..len).map(|i| m.peek_ram(base + i as u16)).collect();
                let compile = m.peek_ram(self.config["state"]) != 0
                    || [b":".as_slice(), b"VARIABLE", b"CONSTANT", b"IMMEDIATE"]
                        .contains(&token.as_slice());
                Some(if compile {
                    Role::CompileWord
                } else {
                    Role::SetupWord
                })
            } else if self.at("next", m.pc) {
                Some(Role::Next)
            } else if self.at("parse", m.pc) {
                Some(Role::Parse)
            } else if self.at("find", m.pc) {
                Some(Role::Find)
            } else if self.at("emit", m.pc) {
                Some(Role::Emit)
            } else {
                None
            }
        } else if self.active && self.at("loader", m.pc) {
            Some(Role::SourceLoad)
        } else if self.active && self.at("tokenizer", m.pc) {
            Some(Role::MinTokens)
        } else {
            None
        };
        if let Some(role) = role {
            let (return_pc, return_sp) = return_target(m);
            // An internal loop may jump back to a function's entry label.
            if !self
                .frames
                .iter()
                .any(|f| f.entry == m.pc && f.entry_sp == sp && f.return_pc == return_pc)
            {
                self.frames.push(Frame {
                    role,
                    entry: m.pc,
                    entry_sp: sp,
                    return_pc,
                    return_sp,
                });
                *self.calls.entry(role.name()).or_default() += 1;
            }
        }
        if self.active && self.forth && self.events.contains_key("application_ready_cycle") {
            let dsp = m.peek_ram(self.config["data_sp"]);
            assert_eq!(dsp & 1, 0, "unaligned Forth stack");
            self.peak("data_stack_peak_cells", dsp.wrapping_add(2) as u64 / 2);
            let top = word(m, self.config["loop_top"]);
            assert!(top >= 0x2800, "invalid loop stack pointer");
            self.peak("loop_stack_peak_bytes", (top - 0x2800) as u64);
        }
    }

    pub fn tick(&mut self, m: &Machine) {
        let has = |role| self.frames.iter().any(|f| f.role == role);
        let phase = if self.executing {
            "execute"
        } else if !self.events.contains_key("minos_boot_end_cycle") {
            "boot"
        } else if has(Role::Input) {
            "input"
        } else if has(Role::NativeLoad) || has(Role::SourceLoad) {
            "load"
        } else if has(Role::MinTokens) {
            "tokenize"
        } else if has(Role::CompileWord) {
            "compile"
        } else if has(Role::Next) {
            "tokenize"
        } else if has(Role::SetupWord) {
            "setup_execute"
        } else if self.active && !self.events.contains_key("application_ready_cycle") {
            "application_boot"
        } else {
            "dispatch"
        };
        *self.phases.get_mut(phase).unwrap() += 1;
        for frame in &self.frames {
            *self.components.entry(frame.role.name()).or_default() += 1;
        }
        if self.active {
            self.peak(
                "hardware_stack_peak_bytes",
                0xfeu8.wrapping_sub(m.peek_ram(0xffff)) as u64,
            );
            if m.control_word() & RI != 0 {
                let address = m.mar;
                let region = if self.forth && (0x8000..0xd000).contains(&address) {
                    Some(("dictionary_written_span_bytes", 0x8000))
                } else if !self.forth && (0x2e00..0x3100).contains(&address) {
                    Some(("call_dictionary_written_span_bytes", 0x2e00))
                } else if !self.forth && (0x3100..0x3a00).contains(&address) {
                    Some(("variable_dictionary_written_span_bytes", 0x3100))
                } else if !self.forth && (0x3a00..0x3f80).contains(&address) {
                    Some(("temporary_data_written_span_bytes", 0x3a00))
                } else if (0xd000..0xd200).contains(&address) {
                    Some(("input_written_span_bytes", 0xd000))
                } else if (0xe000..0xf000).contains(&address) {
                    Some(("output_written_span_bytes", 0xe000))
                } else {
                    None
                };
                if let Some((key, base)) = region {
                    self.peak(key, (address - base + 1) as u64);
                }
            }
        }
    }

    pub fn json(&self) -> String {
        fn map(values: &BTreeMap<&str, u64>) -> String {
            format!(
                "{{{}}}",
                values
                    .iter()
                    .map(|(key, n)| format!("\"{key}\":{n}"))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        format!(
            "\"phases\":{},\"components\":{},\"calls\":{},\"memory\":{},\"events\":{}",
            map(&self.phases),
            map(&self.components),
            map(&self.calls),
            map(&self.memory),
            map(&self.events)
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use minredux_cs::{AO, CTRL_ENTRIES, ControlRom, IC};

    fn machine() -> Machine {
        Machine::new(
            ControlRom {
                words: vec![AO | RI | IC; CTRL_ENTRIES],
            },
            vec![255; 0x80000],
        )
    }

    fn poke(m: &mut Machine, addr: u16, byte: u8) {
        m.bank = 255;
        m.mar = addr;
        m.ar = byte;
        m.step();
    }

    fn observer() -> Profile {
        Profile {
            config: [
                ("prompt", 0x1500),
                ("app_entry", 0x1000),
                ("app_ready", 0x1100),
                ("loader", 0x1200),
                ("native_load", 0x1300),
                ("readline", 0x1400),
                ("tokenizer", 0x1600),
                ("source_end_ptr", 0x89),
                ("token_end_ptr", 0x1700),
            ]
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
            forth: false,
            active: true,
            frames: vec![],
            executing: false,
            phases: [
                "boot",
                "application_boot",
                "input",
                "load",
                "tokenize",
                "compile",
                "setup_execute",
                "dispatch",
                "execute",
            ]
            .into_iter()
            .map(|key| (key, 0))
            .collect(),
            components: BTreeMap::new(),
            calls: BTreeMap::new(),
            memory: BTreeMap::new(),
            events: [("minos_boot_end_cycle", 0), ("application_ready_cycle", 0)]
                .into_iter()
                .collect(),
        }
    }

    #[test]
    fn rts_target_uses_split_return_bytes_and_plus_two() {
        let mut m = machine();
        poke(&mut m, 0xffff, 0xfc);
        poke(&mut m, 0xfffd, 0x12);
        poke(&mut m, 0xfffe, 0x34);
        assert_eq!(return_target(&m), (0x1236, 0xfe));
    }

    #[test]
    fn entry_loops_do_not_duplicate_frames_and_matching_return_closes_them() {
        let mut m = machine();
        poke(&mut m, 0xffff, 0xfc);
        poke(&mut m, 0xfffd, 0x20);
        poke(&mut m, 0xfffe, 0x00);
        poke(&mut m, 0x89, 10);
        poke(&mut m, 0x8a, 0x80);
        m.pc = 0x1200;
        let mut p = observer();
        p.boundary(&m);
        p.boundary(&m);
        assert_eq!(p.frames.len(), 1);
        assert_eq!(p.calls["source_load"], 1);
        m.pc = 0x2002;
        poke(&mut m, 0xffff, 0xfe);
        p.boundary(&m);
        assert!(p.frames.is_empty());
        assert_eq!(p.memory["source_bytes"], 10);
    }

    #[test]
    fn phase_priority_is_disjoint_but_components_are_inclusive() {
        let m = machine();
        let mut p = observer();
        p.frames.push(Frame {
            role: Role::CompileWord,
            entry: 1,
            entry_sp: 1,
            return_pc: 2,
            return_sp: 2,
        });
        p.tick(&m);
        p.frames.push(Frame {
            role: Role::Input,
            entry: 3,
            entry_sp: 3,
            return_pc: 4,
            return_sp: 4,
        });
        p.tick(&m);
        p.executing = true;
        p.tick(&m);
        assert_eq!(p.phases.values().sum::<u64>(), 3);
        assert_eq!(
            (p.phases["compile"], p.phases["input"], p.phases["execute"]),
            (1, 1, 1)
        );
        assert_eq!(p.components["compile_word"], 3);
    }

    #[test]
    fn memory_span_tracks_real_write_addresses_without_changing_ram() {
        let mut m = machine();
        let mut p = observer();
        m.mar = 0x3a20;
        p.tick(&m);
        m.mar = 0x3a00;
        p.tick(&m);
        assert_eq!(p.memory["temporary_data_written_span_bytes"], 33);
        assert_eq!(m.peek_ram(0x3a20), 0);
    }
}
