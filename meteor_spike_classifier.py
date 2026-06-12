"""
Meteor Spike Classifier for COSMIC-2 ionPrf Data
================================================

Automatically detects and classifies electron density spikes in the meteor zone (95-120 km)
as either real meteor trails or noise.

Author: Claude (Anthropic)
Date: April 2026
"""

import numpy as np
from scipy.optimize import curve_fit
from typing import Dict, Tuple, Optional
import warnings

warnings.filterwarnings('ignore')


class MeteorSpikeClassifier:
    """
    Classifies electron density spikes as real meteor trails or noise.
    
    Uses multi-criteria analysis:
    - Symmetry of spike (most discriminating)
    - Signal-to-noise ratio
    - Shape smoothness
    - Sampling quality
    - Width characteristics
    - Magnitude assessment
    """
    
    def __init__(self, 
                 meteor_zone_min: float = 95.0,
                 meteor_zone_max: float = 120.0,
                 min_points_warning: int = 15,
                 min_points_critical: int = 8):
        """
        Initialize the classifier.
        
        Parameters
        ----------
        meteor_zone_min : float
            Minimum altitude for meteor zone (km). Default: 95 km
        meteor_zone_max : float
            Maximum altitude for meteor zone (km). Default: 120 km
        min_points_warning : int
            Minimum points for reliable structure analysis. Default: 15
        min_points_critical : int
            Absolute minimum points for any analysis. Default: 8
        """
        self.meteor_zone_min = meteor_zone_min
        self.meteor_zone_max = meteor_zone_max
        self.min_points_warning = min_points_warning
        self.min_points_critical = min_points_critical
        
    def classify(self, 
                 altitude: np.ndarray, 
                 electron_density: np.ndarray) -> Tuple[str, Dict]:
        """
        Classify a spike as ACCEPT (real meteor) or REJECT (noise).
        
        Parameters
        ----------
        altitude : np.ndarray
            Altitude array in km
        electron_density : np.ndarray
            Electron density array in el/cm³
            
        Returns
        -------
        verdict : str
            "ACCEPT" (likely real meteor) or "REJECT" (likely noise)
        details : dict
            Detailed metrics and assessment
        """
        
        # Extract meteor zone
        mask = (altitude >= self.meteor_zone_min) & (altitude <= self.meteor_zone_max)
        alt_zone = altitude[mask]
        dens_zone = electron_density[mask]
        
        details = {
            'verdict': None,
            'confidence': None,
            'reality_score': None,
            'metrics': {},
            'flags': [],
            'recommendations': []
        }
        
        # Check if we have data in meteor zone
        if len(alt_zone) == 0:
            details['verdict'] = 'REJECT'
            details['confidence'] = 1.0
            details['flags'].append('NO_DATA_IN_METEOR_ZONE')
            return 'REJECT', details
        
        # Get peak properties
        peak_idx = np.nanargmax(dens_zone)
        peak_alt = alt_zone[peak_idx]
        peak_dens = dens_zone[peak_idx]
        
        # ===== METRIC 1: SYMMETRY (Most important) =====
        asymmetry_ratio, asymmetry_score = self._assess_symmetry(dens_zone, peak_idx)
        details['metrics']['asymmetry_ratio'] = asymmetry_ratio
        details['metrics']['asymmetry_score'] = asymmetry_score
        
        # ===== METRIC 2: SIGNAL-TO-NOISE RATIO =====
        snr, bg_mean, bg_std = self._assess_snr(dens_zone, peak_idx)
        details['metrics']['snr'] = snr
        details['metrics']['background_mean'] = bg_mean
        details['metrics']['background_std'] = bg_std
        details['metrics']['peak_excess'] = peak_dens - bg_mean
        snr_score = self._score_snr(snr)
        
        # ===== METRIC 3: SHAPE SMOOTHNESS =====
        curvature_ratio, curvature_score = self._assess_smoothness(dens_zone, peak_idx)
        details['metrics']['curvature_ratio'] = curvature_ratio
        details['metrics']['curvature_score'] = curvature_score
        
        # ===== METRIC 4: WIDTH ANALYSIS =====
        fwhm, width_score = self._assess_width(alt_zone, dens_zone, peak_idx)
        details['metrics']['fwhm_km'] = fwhm
        details['metrics']['width_score'] = width_score
        
        # ===== METRIC 5: SAMPLING QUALITY =====
        sampling_score, n_points = self._assess_sampling(alt_zone)
        details['metrics']['n_points'] = n_points
        details['metrics']['mean_interval_km'] = np.mean(np.diff(alt_zone)) if len(alt_zone) > 1 else np.nan
        details['metrics']['sampling_score'] = sampling_score
        
        if n_points < self.min_points_warning:
            details['flags'].append('SPARSE_SAMPLING')
        
        if n_points < self.min_points_critical:
            details['verdict'] = 'REJECT'
            details['confidence'] = 0.95
            details['flags'].append('INSUFFICIENT_DATA')
            return 'REJECT', details
        
        # ===== METRIC 6: MAGNITUDE ASSESSMENT =====
        magnitude_score = self._assess_magnitude(peak_dens, bg_mean)
        details['metrics']['magnitude_score'] = magnitude_score
        
        # ===== COMPUTE REALITY SCORE =====
        reality_score = (
            asymmetry_score * 2.0 +    # Asymmetry weighted heavily (most discriminating)
            snr_score * 1.5 +           # SNR moderately weighted
            curvature_score * 1.0 +     # Smoothness moderately weighted
            width_score * 1.0 +         # Width moderately weighted
            sampling_score * 0.5 +      # Sampling quality lightly weighted
            magnitude_score * 0.5       # Magnitude lightly weighted
        )
        
        # Normalize to 0-10 scale
        max_possible = (2.0 + 1.5 + 1.0 + 1.0 + 0.5 + 0.5) * 2.0  # Max possible score
        reality_score_normalized = (reality_score / max_possible) * 10.0
        reality_score_normalized = np.clip(reality_score_normalized, 0, 10)
        
        details['reality_score'] = round(reality_score_normalized, 1)
        
        # ===== GENERATE VERDICT =====
        verdict, confidence = self._generate_verdict(
            reality_score_normalized,
            asymmetry_ratio,
            snr,
            n_points
        )
        
        details['verdict'] = verdict
        details['confidence'] = confidence
        
        # ===== ADD DIAGNOSTIC FLAGS =====
        if asymmetry_ratio > 0.5:
            details['flags'].append('HIGHLY_ASYMMETRIC_RED_FLAG')
        
        if snr < 1.5:
            details['flags'].append('WEAK_SNR')
        
        if curvature_ratio > 4.0:
            details['flags'].append('JAGGED_SHAPE')
        
        if not np.isnan(fwhm) and (fwhm > 20 or fwhm < 0.5):
            details['flags'].append('UNUSUAL_WIDTH')
        
        if peak_dens < 1e4:
            details['flags'].append('LOW_ABSOLUTE_DENSITY')
        
        # ===== ADD RECOMMENDATIONS =====
        if verdict == 'ACCEPT':
            if confidence < 0.7:
                details['recommendations'].append('Cross-validate with radar data for confirmation')
            if snr < 2.0:
                details['recommendations'].append('SNR is marginal - use with caution')
            if 'SPARSE_SAMPLING' in details['flags']:
                details['recommendations'].append('Limited sampling - consider as tentative detection')
        
        if verdict == 'REJECT':
            details['recommendations'].append('Profile shows noise characteristics')
            if asymmetry_ratio > 0.5:
                details['recommendations'].append('Asymmetry pattern is hallmark of noise - not a real meteor')
            if snr < 1.5:
                details['recommendations'].append('Signal too weak to distinguish from background fluctuation')
        
        return verdict, details
    
    def _assess_symmetry(self, dens_zone: np.ndarray, peak_idx: int) -> Tuple[float, float]:
        """
        Assess symmetry of the spike.
        
        Returns
        -------
        asymmetry_ratio : float
            0 (perfect) to 1 (completely asymmetric)
        score : float
            0 (bad) to 2 (excellent)
        """
        half_max = dens_zone[peak_idx] / 2
        above_half = dens_zone >= half_max
        indices_above = np.where(above_half)[0]
        
        if len(indices_above) < 3:
            # Can't assess symmetry with fewer than 3 points above half-max
            return np.nan, 0.0
        
        left_idx = indices_above[0]
        right_idx = indices_above[-1]
        
        left_dist = peak_idx - left_idx
        right_dist = right_idx - peak_idx
        
        if max(left_dist, right_dist) == 0:
            asymmetry_ratio = 0.0
        else:
            asymmetry_ratio = abs(left_dist - right_dist) / max(left_dist, right_dist)
        
        # Score: real meteors have asymmetry < 0.3, noise has > 0.5
        if asymmetry_ratio < 0.25:
            score = 2.0
        elif asymmetry_ratio < 0.35:
            score = 1.5
        elif asymmetry_ratio < 0.5:
            score = 1.0
        elif asymmetry_ratio < 0.65:
            score = 0.5
        else:
            score = 0.0
        
        return asymmetry_ratio, score
    
    def _assess_snr(self, dens_zone: np.ndarray, peak_idx: int) -> Tuple[float, float, float]:
        """
        Assess signal-to-noise ratio.
        
        Returns
        -------
        snr : float
            Signal-to-noise ratio in sigma
        bg_mean : float
            Background mean
        bg_std : float
            Background standard deviation
        """
        background = np.delete(dens_zone, peak_idx)
        bg_mean = np.nanmean(background)
        bg_std = np.nanstd(background)
        
        peak_val = dens_zone[peak_idx]
        snr = (peak_val - bg_mean) / bg_std if bg_std > 0 else 0
        
        return snr, bg_mean, bg_std
    
    def _score_snr(self, snr: float) -> float:
        """Score SNR (0-2 scale)."""
        if snr > 3.0:
            return 2.0
        elif snr > 2.0:
            return 1.5
        elif snr > 1.5:
            return 1.0
        elif snr > 1.0:
            return 0.5
        else:
            return 0.0
    
    def _assess_smoothness(self, dens_zone: np.ndarray, peak_idx: int) -> Tuple[float, float]:
        """
        Assess shape smoothness via curvature analysis.
        
        Returns
        -------
        curvature_ratio : float
            Peak curvature / mean curvature
        score : float
            0 (jagged) to 2 (smooth)
        """
        if len(dens_zone) < 3:
            return np.nan, 1.0  # Neutral score
        
        grad1 = np.gradient(dens_zone)
        grad2 = np.gradient(grad1)
        curvature = np.abs(grad2)
        
        peak_curv = curvature[peak_idx]
        mean_curv_without_peak = np.mean(np.delete(curvature, peak_idx))
        
        if mean_curv_without_peak == 0:
            curvature_ratio = 0.0
        else:
            curvature_ratio = peak_curv / mean_curv_without_peak
        
        # Score: smooth profiles have ratio < 3, jagged > 4
        if curvature_ratio < 2.5:
            score = 2.0
        elif curvature_ratio < 3.0:
            score = 1.5
        elif curvature_ratio < 3.5:
            score = 1.0
        elif curvature_ratio < 4.0:
            score = 0.5
        else:
            score = 0.0
        
        return curvature_ratio, score
    
    def _assess_width(self, alt_zone: np.ndarray, dens_zone: np.ndarray, peak_idx: int) -> Tuple[float, float]:
        """
        Assess width (FWHM) of spike.
        
        Returns
        -------
        fwhm : float
            Full width at half maximum in km
        score : float
            0-2 scale
        """
        half_max = dens_zone[peak_idx] / 2
        above_half = dens_zone >= half_max
        indices_above = np.where(above_half)[0]
        
        if len(indices_above) < 2:
            return np.nan, 1.0  # Neutral score
        
        fwhm = alt_zone[indices_above[-1]] - alt_zone[indices_above[0]]
        
        # Real meteor trails: 0.5-5 km
        # Aged/convolved: up to ~20 km
        # Broader than 20 km: likely noise or artifact
        
        if 0.5 <= fwhm <= 5.0:
            score = 2.0
        elif 5.0 < fwhm <= 10.0:
            score = 1.5
        elif 0.3 <= fwhm <= 0.5 or 10.0 < fwhm <= 20.0:
            score = 1.0
        elif fwhm < 0.3 or fwhm > 20.0:
            score = 0.5
        else:
            score = 0.0
        
        return fwhm, score
    
    def _assess_sampling(self, alt_zone: np.ndarray) -> Tuple[float, int]:
        """
        Assess sampling quality.
        
        Returns
        -------
        score : float
            0-2 scale
        n_points : int
            Number of points in zone
        """
        n_points = len(alt_zone)
        
        if n_points >= 20:
            score = 2.0
        elif n_points >= 15:
            score = 1.5
        elif n_points >= 12:
            score = 1.0
        elif n_points >= 8:
            score = 0.5
        else:
            score = 0.0
        
        return score, n_points
    
    def _assess_magnitude(self, peak_dens: float, bg_mean: float) -> float:
        """
        Assess magnitude appropriateness.
        
        Returns
        -------
        score : float
            0-2 scale
        """
        # Typical meteor trails: 10^4 to 10^6 el/cm³
        
        if 1e4 <= peak_dens <= 1e7:
            excess_ratio = (peak_dens - bg_mean) / bg_mean if bg_mean > 0 else 0
            
            if excess_ratio > 0.2:  # 20% above background
                score = 2.0
            elif excess_ratio > 0.1:  # 10% above background
                score = 1.5
            elif excess_ratio > 0.05:  # 5% above background
                score = 1.0
            else:
                score = 0.5
        else:
            score = 0.5  # Outside typical range but not impossible
        
        return score
    
    def _generate_verdict(self, 
                         reality_score: float, 
                         asymmetry_ratio: float, 
                         snr: float,
                         n_points: int) -> Tuple[str, float]:
        """
        Generate final verdict and confidence.
        
        Returns
        -------
        verdict : str
            "ACCEPT" or "REJECT"
        confidence : float
            Confidence level (0-1)
        """
        
        # Asymmetry is the primary discriminant
        if not np.isnan(asymmetry_ratio) and asymmetry_ratio > 0.5:
            # Highly asymmetric = almost certainly noise
            return "REJECT", 0.95
        
        # Primary decision on reality score
        if reality_score >= 6.0:
            # Good candidate
            if snr > 2.0:
                confidence = 0.90
            elif snr > 1.5:
                confidence = 0.75
            else:
                confidence = 0.65
            return "ACCEPT", confidence
        
        elif reality_score >= 4.0:
            # Marginal candidate
            if snr > 2.0 and not np.isnan(asymmetry_ratio) and asymmetry_ratio < 0.3:
                confidence = 0.70
            else:
                confidence = 0.55
            return "ACCEPT", confidence
        
        elif reality_score >= 2.0:
            # Weak candidate - lean toward rejection
            if snr > 2.0:
                confidence = 0.60
                return "ACCEPT", confidence
            else:
                confidence = 0.70
                return "REJECT", confidence
        
        else:
            # Clear rejection
            confidence = 0.85
            return "REJECT", confidence
    
    def print_report(self, verdict: str, details: Dict) -> None:
        """
        Print a formatted analysis report.
        
        Parameters
        ----------
        verdict : str
            "ACCEPT" or "REJECT"
        details : dict
            Details dictionary from classify()
        """
        print("=" * 80)
        print("METEOR SPIKE CLASSIFICATION REPORT")
        print("=" * 80)
        
        # Verdict
        emoji = "✓" if verdict == "ACCEPT" else "✗"
        print(f"\n{emoji} VERDICT: {verdict}")
        print(f"Reality Score: {details['reality_score']}/10.0")
        print(f"Confidence: {details['confidence']*100:.0f}%")
        
        # Metrics
        print("\n" + "-" * 80)
        print("DIAGNOSTIC METRICS")
        print("-" * 80)
        metrics = details['metrics']
        
        if 'asymmetry_ratio' in metrics and not np.isnan(metrics['asymmetry_ratio']):
            print(f"Asymmetry Ratio:        {metrics['asymmetry_ratio']:.3f} (0=symmetric, 1=asymmetric)")
        
        if 'snr' in metrics:
            print(f"Signal-to-Noise Ratio:  {metrics['snr']:.2f} σ")
        
        if 'curvature_ratio' in metrics:
            print(f"Curvature Ratio:        {metrics['curvature_ratio']:.2f}x (smoothness)")
        
        if 'fwhm_km' in metrics and not np.isnan(metrics['fwhm_km']):
            print(f"FWHM:                   {metrics['fwhm_km']:.2f} km")
        
        print(f"Sampling Points:        {metrics['n_points']}")
        print(f"Mean Interval:          {metrics['mean_interval_km']:.2f} km")
        
        if 'peak_excess' in metrics:
            print(f"Peak Excess:            {metrics['peak_excess']:.3e} el/cm³")
        
        # Flags
        if details['flags']:
            print("\n" + "-" * 80)
            print("FLAGS")
            print("-" * 80)
            for flag in details['flags']:
                print(f"  ⚠️  {flag}")
        
        # Recommendations
        if details['recommendations']:
            print("\n" + "-" * 80)
            print("RECOMMENDATIONS")
            print("-" * 80)
            for rec in details['recommendations']:
                print(f"  → {rec}")
        
        print("\n" + "=" * 80)


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    """
    Example usage with sample data
    """
    
    # Create sample data (File 1: Real meteor)
    print("\n" + "="*80)
    print("EXAMPLE 1: Real Meteor Trail (File 1 - C2E6)")
    print("="*80)
    
    alt_file1 = np.array([104.03, 105.38, 106.72, 108.06, 109.39, 110.73, 112.06])
    dens_file1 = np.array([1.55e6, 1.69e6, 1.90e6, 1.95e6, 1.84e6, 1.71e6, 1.65e6])
    
    classifier = MeteorSpikeClassifier()
    verdict1, details1 = classifier.classify(alt_file1, dens_file1)
    classifier.print_report(verdict1, details1)
    
    # Create sample data (File 2: Noise)
    print("\n" + "="*80)
    print("EXAMPLE 2: Noise Spike (File 2 - C2E2)")
    print("="*80)
    
    alt_file2 = np.array([96.72, 99.19, 101.65, 104.11, 106.56])
    dens_file2 = np.array([7.29e4, 7.83e4, 9.63e4, 8.23e4, 8.28e4])
    
    verdict2, details2 = classifier.classify(alt_file2, dens_file2)
    classifier.print_report(verdict2, details2)
