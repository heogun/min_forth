//! Dependency-free audio capture and mono 16-bit WAV output.
//!
//! Each CPU clock contributes one sample of the current PSG level.  An exact
//! fractional accumulator resamples that stream to the requested host rate,
//! so the number of output samples is `rate * cycles / 8_000_000` (rounded by
//! the same arithmetic the real stream would use).

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::psg::CPU_CLOCK_HZ;

pub struct AudioCapture {
    pub rate: u32,
    phase: u64,
    weighted: i64,
    cycles: u64,
    pub samples: Vec<i16>,
    /// The capture only grows while enabled; the PSG always keeps running.
    pub enabled: bool,
}

impl Default for AudioCapture {
    fn default() -> Self {
        Self::new(48_000)
    }
}

impl AudioCapture {
    pub fn new(rate: u32) -> Self {
        Self {
            rate: rate.max(1),
            phase: 0,
            weighted: 0,
            cycles: 0,
            samples: Vec::new(),
            enabled: false,
        }
    }

    pub fn set_rate(&mut self, rate: u32) {
        self.rate = rate.max(1);
    }

    /// Record one CPU clock at the given PSG level.
    pub fn push(&mut self, level: i32) {
        if !self.enabled {
            return;
        }
        self.weighted += level as i64;
        self.cycles += 1;
        self.phase += self.rate as u64;
        while self.phase >= CPU_CLOCK_HZ {
            self.phase -= CPU_CLOCK_HZ;
            let average = self.weighted / self.cycles.max(1) as i64;
            self.samples
                .push(average.clamp(i16::MIN as i64, i16::MAX as i64) as i16);
            self.weighted = 0;
            self.cycles = 0;
        }
    }

    pub fn duration_seconds(&self) -> f64 {
        self.samples.len() as f64 / self.rate as f64
    }
}

/// Serialize mono signed 16-bit PCM as a canonical RIFF/WAVE file.
pub fn wav_bytes(samples: &[i16], rate: u32) -> Vec<u8> {
    let data_len = (samples.len() * 2) as u32;
    let mut out = Vec::with_capacity(44 + data_len as usize);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&(36 + data_len).to_le_bytes());
    out.extend_from_slice(b"WAVE");
    out.extend_from_slice(b"fmt ");
    out.extend_from_slice(&16u32.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes()); // PCM
    out.extend_from_slice(&1u16.to_le_bytes()); // mono
    out.extend_from_slice(&rate.to_le_bytes());
    out.extend_from_slice(&(rate * 2).to_le_bytes());
    out.extend_from_slice(&2u16.to_le_bytes()); // block align
    out.extend_from_slice(&16u16.to_le_bytes()); // bits per sample
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        out.extend_from_slice(&sample.to_le_bytes());
    }
    out
}

pub fn write_wav<P: AsRef<Path>>(path: P, samples: &[i16], rate: u32) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writer.write_all(&wav_bytes(samples, rate))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wav_header_is_canonical_and_data_length_matches() {
        let bytes = wav_bytes(&[1, -1, 256], 48_000);
        assert_eq!(&bytes[0..4], b"RIFF");
        assert_eq!(&bytes[8..12], b"WAVE");
        assert_eq!(&bytes[36..40], b"data");
        assert_eq!(u32::from_le_bytes(bytes[40..44].try_into().unwrap()), 6);
        assert_eq!(bytes.len(), 44 + 6);
        assert_eq!(u32::from_le_bytes(bytes[4..8].try_into().unwrap()), 42);
        assert_eq!(
            u32::from_le_bytes(bytes[24..28].try_into().unwrap()),
            48_000
        );
    }

    #[test]
    fn resampling_accumulates_average_per_output_sample() {
        let mut a = AudioCapture::new(48_000);
        a.enabled = true;
        for _ in 0..166 {
            a.push(100);
        }
        assert!(a.samples.is_empty());
        a.push(100);
        assert_eq!(a.samples, vec![100]);
        assert_eq!(a.duration_seconds(), 1.0 / 48_000.0);
    }
}
