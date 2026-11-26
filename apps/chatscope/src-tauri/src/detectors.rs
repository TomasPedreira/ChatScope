//! Detectors consume normalized signals, independent of the acquisition transport.
use crate::{
    clips::{ClipProfile, TimeRange},
    scope::{Moment, SignalPoint},
};

pub trait MomentDetector<T: ?Sized> {
    fn detect(&self, input: &T, bounds: TimeRange, profile: &ClipProfile) -> Vec<Moment>;
}
pub struct HeatmapDetector;
pub struct AudioEnergyDetector;
impl MomentDetector<[SignalPoint]> for AudioEnergyDetector {
    fn detect(
        &self,
        input: &[SignalPoint],
        bounds: TimeRange,
        profile: &ClipProfile,
    ) -> Vec<Moment> {
        let mut moments = detect_heatmap(input, bounds, profile);
        for moment in &mut moments {
            moment.signal = "audio_energy".into();
            moment.reason = "Pico de energia no áudio · confirmar contexto".into();
        }
        moments
    }
}
impl MomentDetector<[SignalPoint]> for HeatmapDetector {
    fn detect(
        &self,
        input: &[SignalPoint],
        bounds: TimeRange,
        profile: &ClipProfile,
    ) -> Vec<Moment> {
        detect_heatmap(input, bounds, profile)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn detector_uses_the_shared_duration_and_candidate_limit() {
        let points: Vec<_> = [0.1, 0.9, 0.1, 0.1, 0.1, 1.0, 0.1, 0.1, 0.8, 0.1]
            .iter()
            .enumerate()
            .map(|(index, value)| SignalPoint {
                start_time: index as f64 * 20.0,
                end_time: (index + 1) as f64 * 20.0,
                value: *value,
            })
            .collect();
        let profile = ClipProfile {
            duration: 40.0,
            before_peak: 25.0,
            max_moments: 2,
        };
        let moments = HeatmapDetector.detect(
            points.as_slice(),
            TimeRange {
                start: 0.0,
                end: 200.0,
            },
            &profile,
        );
        assert_eq!(moments.len(), 2);
        assert!(
            moments
                .iter()
                .all(|moment| (moment.end - moment.start - 40.0).abs() < 0.001)
        );
        assert_eq!(moments[0].peak, 110.0);
    }
}
pub struct ChatActivityDetector;
impl MomentDetector<crate::chat::Analysis> for ChatActivityDetector {
    fn detect(
        &self,
        input: &crate::chat::Analysis,
        bounds: TimeRange,
        profile: &ClipProfile,
    ) -> Vec<Moment> {
        let mut moments: Vec<Moment> = vec![];
        for highlight in &input.highlights {
            let peak = (highlight.end - 5.0)
                .max(bounds.start)
                .min((bounds.end - 0.001).max(bounds.start));
            let window = profile.window(peak, bounds);
            if window.end > window.start
                && moments
                    .iter()
                    .all(|other| window.end <= other.start || window.start >= other.end)
            {
                moments.push(Moment {
                    start: window.start,
                    end: window.end,
                    peak,
                    strength: f64::from(highlight.score) / 100.0,
                    signal: "chat_activity".into(),
                    reason: highlight.reason.clone(),
                });
                if moments.len() == profile.max_moments {
                    break;
                }
            }
        }
        moments
    }
}

/// Local maxima above the interval's median; plateau grouping and non-overlap
/// avoid offering eight copies of one replay spike. Context is a review suggestion.
fn detect_heatmap(points: &[SignalPoint], bounds: TimeRange, profile: &ClipProfile) -> Vec<Moment> {
    if points.is_empty() {
        return vec![];
    }
    let mut values: Vec<_> = points.iter().map(|point| point.value).collect();
    values.sort_by(f64::total_cmp);
    let min = values[0];
    let max = values[values.len() - 1];
    if max - min < 0.02 {
        return vec![];
    }
    let median = (values[(values.len() - 1) / 2] + values[values.len() / 2]) / 2.0;
    let threshold = median + ((max - min) * 0.15).max(0.05);
    let mut peaks = vec![];
    let mut index = 0;
    while index < points.len() {
        let first = index;
        while index + 1 < points.len()
            && (points[index + 1].value - points[first].value).abs() < 1e-9
        {
            index += 1;
        }
        let point = &points[first];
        let left = if first > 0 {
            points[first - 1].value
        } else {
            -1.0
        };
        let right = points.get(index + 1).map_or(-1.0, |point| point.value);
        if point.value >= threshold && point.value > left && point.value > right {
            let peak = (point.start_time + points[index].end_time) / 2.0;
            let window = profile.window(peak, bounds);
            peaks.push(Moment {
                start: window.start,
                end: window.end,
                peak,
                strength: point.value,
                signal: "youtube_heatmap".into(),
                reason: format!(
                    "Pico de repetição · intensidade relativa {:.2}/1",
                    point.value
                ),
            });
        }
        index += 1;
    }
    peaks.sort_by(|a, b| {
        b.strength
            .total_cmp(&a.strength)
            .then(a.peak.total_cmp(&b.peak))
    });
    let mut moments: Vec<Moment> = vec![];
    for candidate in peaks {
        if moments
            .iter()
            .all(|picked| candidate.end <= picked.start || candidate.start >= picked.end)
        {
            moments.push(candidate);
            if moments.len() == profile.max_moments {
                break;
            }
        }
    }
    moments
}
