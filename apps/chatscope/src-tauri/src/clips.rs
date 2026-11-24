//! Editorial preferences are independent of the media provider and detector.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct ClipProfile {
    pub duration: f64,
    pub before_peak: f64,
    pub max_moments: usize,
}

impl Default for ClipProfile {
    fn default() -> Self {
        Self {
            duration: 30.0,
            before_peak: 20.0,
            max_moments: 8,
        }
    }
}

#[derive(Clone, Copy)]
pub struct TimeRange {
    pub start: f64,
    pub end: f64,
}

impl ClipProfile {
    pub fn validate(&self) -> Result<(), String> {
        if !self.duration.is_finite() || !(5.0..=180.0).contains(&self.duration) {
            return Err("A duração pretendida deve estar entre 5 e 180 segundos.".into());
        }
        if !self.before_peak.is_finite()
            || self.before_peak < 0.0
            || self.before_peak > self.duration
        {
            return Err(
                "O contexto antes do pico deve ficar entre zero e a duração do clip.".into(),
            );
        }
        if !(1..=30).contains(&self.max_moments) {
            return Err("Escolhe entre 1 e 30 candidatos.".into());
        }
        Ok(())
    }

    /// Shift at the edges instead of silently shortening a requested clip.
    /// A source/interval shorter than the target can only supply its own duration.
    pub fn window(&self, peak: f64, bounds: TimeRange) -> TimeRange {
        let length = self.duration.min((bounds.end - bounds.start).max(0.0));
        let start =
            (peak - self.before_peak).clamp(bounds.start, (bounds.end - length).max(bounds.start));
        TimeRange {
            start,
            end: start + length,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requested_duration_and_context_are_respected_including_edges() {
        let profile = ClipProfile {
            duration: 60.0,
            before_peak: 40.0,
            max_moments: 3,
        };
        profile.validate().unwrap();
        let bounds = TimeRange {
            start: 100.0,
            end: 300.0,
        };
        let middle = profile.window(180.0, bounds);
        assert_eq!((middle.start, middle.end), (140.0, 200.0));
        let first = profile.window(101.0, bounds);
        let last = profile.window(299.0, bounds);
        assert_eq!((first.start, first.end), (100.0, 160.0));
        assert_eq!((last.start, last.end), (240.0, 300.0));
        let short = profile.window(
            110.0,
            TimeRange {
                start: 100.0,
                end: 119.0,
            },
        );
        assert_eq!((short.start, short.end), (100.0, 119.0));
    }
    #[test]
    fn invalid_profiles_are_rejected_before_starting_a_session() {
        for profile in [
            ClipProfile {
                duration: f64::NAN,
                ..Default::default()
            },
            ClipProfile {
                duration: 4.0,
                ..Default::default()
            },
            ClipProfile {
                before_peak: 31.0,
                ..Default::default()
            },
            ClipProfile {
                max_moments: 0,
                ..Default::default()
            },
            ClipProfile {
                max_moments: 31,
                ..Default::default()
            },
        ] {
            assert!(profile.validate().is_err());
        }
    }
}
