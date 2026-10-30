use std::time::{Duration, Instant};

pub const CPU_HZ: u64 = 8_000_000;

/// Time represented by emulated clocks, independent of host speed.
pub fn clock_duration(clocks: u64) -> Duration {
    Duration::new(clocks / CPU_HZ, ((clocks % CPU_HZ) * 125) as u32)
}

/// Optional host throttle, separate from all emulated hardware timing.
/// A slow host falls behind rather than skipping virtual clocks.
pub struct RealtimePacer {
    start: Instant,
    start_cycles: u64,
}

impl RealtimePacer {
    pub fn new(start_cycles: u64) -> Self {
        Self {
            start: Instant::now(),
            start_cycles,
        }
    }

    pub fn wait(&self, cycles: u64) {
        let target = clock_duration(cycles.saturating_sub(self.start_cycles));
        if let Some(delay) = target.checked_sub(self.start.elapsed()) {
            std::thread::sleep(delay);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duration_is_125_ns_per_cpu_clock_without_float_drift() {
        assert_eq!(clock_duration(1), Duration::from_nanos(125));
        assert_eq!(clock_duration(8_000_000), Duration::from_secs(1));
        assert_eq!(clock_duration(8_000_001), Duration::new(1, 125));
        assert_eq!(clock_duration(u64::MAX).as_nanos(), u64::MAX as u128 * 125);
    }
}
