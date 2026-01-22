# tokenomics/issuance.py
"""
$BTFI Token Issuance Calculator

Implements the token issuance formula from the BeautiFi Tokenomics
Technical White Paper v1.

Formula:
    Units_of_Work = (TAR × EI × ERR%) / BCAI

Where:
    TAR = Toxic Air Removed (CFM-minutes)
    EI = Energy Input factor (efficiency adjustment, clamped 0.8-1.2)
    ERR% = Error reduction factor / Quality Factor (valid events / total events)
    BCAI = BeautiFi Clean Air Index (price adjustment multiplier)

Issuance per epoch:
    Tokens = Base_issuance_rate × TAR × EI × Quality_Factor / BCAI
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class ValidationStatus(Enum):
    """Event validation status."""
    VALID = "valid"
    INVALID_VOC_HIGH = "invalid_voc_high"
    INVALID_VOC_LOW = "invalid_voc_low"
    INVALID_FAN_OFF = "invalid_fan_off"
    INVALID_DATA = "invalid_data"


@dataclass
class TokenomicsConfig:
    """
    Configuration parameters for token issuance.

    These values are governance-configurable within bounds.
    Based on BTFI v1 Tokenomics Simulator spreadsheet.
    """
    # Base issuance
    base_issuance_rate: float = 0.001  # Tokens per CFM-min

    # Energy Efficiency settings
    baseline_fan_efficiency: float = 9.0  # CFM/W (reference efficiency)
    ei_min: float = 0.8  # Minimum EI clamp
    ei_max: float = 1.2  # Maximum EI clamp
    eff_min_cfm_per_w: float = 2.0  # Minimum valid efficiency
    eff_max_cfm_per_w: float = 40.0  # Maximum valid efficiency

    # CFM bounds
    cfm_min: float = 50.0  # Minimum CFM to count as "running"
    cfm_max: float = 800.0  # Maximum valid CFM

    # VOC gating (convert PPM to PPB for internal use)
    voc_gating_enabled: bool = True
    voc_min_ppm: float = 0.01  # 10 PPB
    voc_max_ppm: float = 2.0   # 2000 PPB

    # BCAI (BeautiFi Clean Air Index) - price adjustment factor
    bcai_scalar: float = 1.0

    # Issuance splits (must sum to 1.0)
    pct_to_facilities: float = 0.75
    pct_to_verifiers: float = 0.05
    pct_to_treasury: float = 0.10
    pct_to_team: float = 0.10

    # Team emission cap
    team_emission_cap_btfi: float = 75_000_000.0

    # Epoch settings
    events_per_epoch: int = 5
    minutes_per_event: int = 12
    samples_per_event: int = 60
    sample_interval_seconds: int = 12

    @property
    def voc_min_ppb(self) -> float:
        """VOC minimum in PPB."""
        return self.voc_min_ppm * 1000

    @property
    def voc_max_ppb(self) -> float:
        """VOC maximum in PPB."""
        return self.voc_max_ppm * 1000

    def validate_splits(self) -> bool:
        """Validate that issuance splits sum to 1.0."""
        total = (
            self.pct_to_facilities +
            self.pct_to_verifiers +
            self.pct_to_treasury +
            self.pct_to_team
        )
        return abs(total - 1.0) < 0.001


@dataclass
class EventValidation:
    """Validation result for a single event (12-minute period)."""
    event_id: int
    is_valid: bool
    status: ValidationStatus
    tar_cfm_min: float  # Raw TAR value
    tar_valid_cfm_min: float  # TAR if valid, 0 if invalid
    energy_wh: float
    energy_valid_wh: float
    efficiency_cfm_w: float
    voc_avg_ppm: float
    cfm_avg: float

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "is_valid": self.is_valid,
            "status": self.status.value,
            "tar_cfm_min": round(self.tar_cfm_min, 2),
            "tar_valid_cfm_min": round(self.tar_valid_cfm_min, 2),
            "energy_wh": round(self.energy_wh, 3),
            "energy_valid_wh": round(self.energy_valid_wh, 3),
            "efficiency_cfm_w": round(self.efficiency_cfm_w, 3) if self.efficiency_cfm_w else 0,
            "voc_avg_ppm": round(self.voc_avg_ppm, 4),
            "cfm_avg": round(self.cfm_avg, 1),
        }


@dataclass
class IssuanceSplit:
    """Token issuance split across recipients."""
    total_tokens: float
    to_facilities: float
    to_verifiers: float
    to_treasury: float
    to_team: float
    team_cap_reached: bool = False

    def to_dict(self) -> dict:
        return {
            "total_tokens": round(self.total_tokens, 6),
            "to_facilities": round(self.to_facilities, 6),
            "to_verifiers": round(self.to_verifiers, 6),
            "to_treasury": round(self.to_treasury, 6),
            "to_team": round(self.to_team, 6),
            "team_cap_reached": self.team_cap_reached,
        }


@dataclass
class EpochIssuance:
    """Complete issuance calculation result for an epoch."""
    epoch_id: str
    device_id: str

    # Raw metrics
    total_tar_cfm_min: float
    total_energy_wh: float
    avg_cfm: float
    avg_watts: float
    avg_efficiency_cfm_w: float

    # Validation
    total_events: int
    valid_events: int
    event_validations: List[EventValidation]

    # Efficiency factor
    eef_vs_baseline: float  # Efficiency vs baseline (before clamp)
    ei_clamped: float  # Energy Input factor (after clamp)

    # Quality factor
    quality_factor: float  # valid_events / total_events

    # Token calculation
    tokens_base: float  # Base rate × EI × TAR
    tokens_after_quality: float  # After quality factor
    tokens_issued: float  # Final (after BCAI)

    # Issuance split
    split: IssuanceSplit

    # Config used
    bcai: float
    base_rate: float

    def to_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "device_id": self.device_id,
            "metrics": {
                "total_tar_cfm_min": round(self.total_tar_cfm_min, 2),
                "total_energy_wh": round(self.total_energy_wh, 3),
                "avg_cfm": round(self.avg_cfm, 1),
                "avg_watts": round(self.avg_watts, 1),
                "avg_efficiency_cfm_w": round(self.avg_efficiency_cfm_w, 3),
            },
            "validation": {
                "total_events": self.total_events,
                "valid_events": self.valid_events,
                "quality_factor": round(self.quality_factor, 3),
                "events": [ev.to_dict() for ev in self.event_validations],
            },
            "efficiency": {
                "eef_vs_baseline": round(self.eef_vs_baseline, 4),
                "ei_clamped": round(self.ei_clamped, 2),
            },
            "issuance": {
                "base_rate": self.base_rate,
                "bcai": self.bcai,
                "tokens_base": round(self.tokens_base, 6),
                "tokens_after_quality": round(self.tokens_after_quality, 6),
                "tokens_issued": round(self.tokens_issued, 6),
            },
            "split": self.split.to_dict(),
        }


class IssuanceCalculator:
    """
    Calculates $BTFI token issuance for telemetry epochs.

    Implements the formula:
        Tokens = (Base_rate × TAR × EI × Quality_Factor) / BCAI

    With VOC gating, efficiency clamping, and issuance splits.
    """

    def __init__(self, config: Optional[TokenomicsConfig] = None):
        self.config = config or TokenomicsConfig()
        self._team_tokens_issued: float = 0.0

    def set_team_tokens_issued(self, amount: float):
        """Set the current total team tokens issued (for cap tracking)."""
        self._team_tokens_issued = amount

    def _validate_event(
        self,
        event_id: int,
        samples: List[dict],
    ) -> EventValidation:
        """
        Validate a single event (12-minute period) and calculate its contribution.

        An event is valid if:
        1. Fan is running (CFM > cfm_min)
        2. VOC is within acceptable range (voc_min to voc_max)
        3. Data is complete and plausible
        """
        if not samples:
            return EventValidation(
                event_id=event_id,
                is_valid=False,
                status=ValidationStatus.INVALID_DATA,
                tar_cfm_min=0,
                tar_valid_cfm_min=0,
                energy_wh=0,
                energy_valid_wh=0,
                efficiency_cfm_w=0,
                voc_avg_ppm=0,
                cfm_avg=0,
            )

        # Calculate event metrics
        cfm_values = [s.get("fan", {}).get("cfm", 0) for s in samples]
        watts_values = [s.get("fan", {}).get("watts", 0) for s in samples]
        voc_values = [s.get("environment", {}).get("voc_ppb", 0) for s in samples]

        cfm_avg = sum(cfm_values) / len(cfm_values)
        watts_avg = sum(watts_values) / len(watts_values)
        voc_avg_ppb = sum(voc_values) / len(voc_values)
        voc_avg_ppm = voc_avg_ppb / 1000.0

        # Calculate TAR for event (CFM × minutes)
        minutes = len(samples) * (self.config.sample_interval_seconds / 60)
        tar_cfm_min = cfm_avg * minutes

        # Calculate energy (Wh)
        hours = minutes / 60
        energy_wh = watts_avg * hours

        # Calculate efficiency
        efficiency = cfm_avg / watts_avg if watts_avg > 0 else 0

        # Validation checks
        is_valid = True
        status = ValidationStatus.VALID

        # Check 1: Fan must be running
        if cfm_avg < self.config.cfm_min:
            is_valid = False
            status = ValidationStatus.INVALID_FAN_OFF

        # Check 2: VOC gating (if enabled)
        elif self.config.voc_gating_enabled:
            if voc_avg_ppm < self.config.voc_min_ppm:
                is_valid = False
                status = ValidationStatus.INVALID_VOC_LOW
            elif voc_avg_ppm > self.config.voc_max_ppm:
                is_valid = False
                status = ValidationStatus.INVALID_VOC_HIGH

        return EventValidation(
            event_id=event_id,
            is_valid=is_valid,
            status=status,
            tar_cfm_min=tar_cfm_min,
            tar_valid_cfm_min=tar_cfm_min if is_valid else 0,
            energy_wh=energy_wh,
            energy_valid_wh=energy_wh if is_valid else 0,
            efficiency_cfm_w=efficiency,
            voc_avg_ppm=voc_avg_ppm,
            cfm_avg=cfm_avg,
        )

    def _calculate_ei(self, efficiency_cfm_w: float) -> tuple[float, float]:
        """
        Calculate Energy Input factor (EI) from efficiency.

        EI = Efficiency / Baseline, clamped to [ei_min, ei_max]

        Returns:
            tuple: (eef_vs_baseline, ei_clamped)
        """
        if efficiency_cfm_w <= 0:
            return 0.0, self.config.ei_min

        eef = efficiency_cfm_w / self.config.baseline_fan_efficiency
        ei_clamped = max(self.config.ei_min, min(self.config.ei_max, eef))

        return eef, ei_clamped

    def _calculate_split(
        self,
        total_tokens: float,
    ) -> IssuanceSplit:
        """
        Split issued tokens across recipients.

        Respects team emission cap.
        """
        team_cap_reached = False

        # Calculate initial splits
        to_facilities = total_tokens * self.config.pct_to_facilities
        to_verifiers = total_tokens * self.config.pct_to_verifiers
        to_treasury = total_tokens * self.config.pct_to_treasury
        to_team = total_tokens * self.config.pct_to_team

        # Check team cap
        if self._team_tokens_issued + to_team > self.config.team_emission_cap_btfi:
            # Cap reached - redirect team allocation to treasury
            team_cap_reached = True
            remaining_team_allowance = max(
                0, self.config.team_emission_cap_btfi - self._team_tokens_issued
            )
            overflow = to_team - remaining_team_allowance
            to_team = remaining_team_allowance
            to_treasury += overflow  # Redirect overflow to treasury

        return IssuanceSplit(
            total_tokens=total_tokens,
            to_facilities=to_facilities,
            to_verifiers=to_verifiers,
            to_treasury=to_treasury,
            to_team=to_team,
            team_cap_reached=team_cap_reached,
        )

    def calculate_epoch_issuance(
        self,
        epoch_id: str,
        device_id: str,
        samples: List[dict],
        samples_per_event: Optional[int] = None,
    ) -> EpochIssuance:
        """
        Calculate token issuance for an epoch.

        Args:
            epoch_id: Unique epoch identifier
            device_id: Device that generated the epoch
            samples: List of telemetry samples in the epoch
            samples_per_event: Override samples per event (default from config)

        Returns:
            EpochIssuance with complete calculation results
        """
        samples_per_event = samples_per_event or self.config.samples_per_event

        # Group samples into events
        events = []
        for i in range(0, len(samples), samples_per_event):
            event_samples = samples[i:i + samples_per_event]
            if event_samples:
                events.append(event_samples)

        # Validate each event
        event_validations = []
        for idx, event_samples in enumerate(events):
            validation = self._validate_event(idx + 1, event_samples)
            event_validations.append(validation)

        total_events = len(event_validations)
        valid_events = sum(1 for ev in event_validations if ev.is_valid)

        # Calculate quality factor
        quality_factor = valid_events / total_events if total_events > 0 else 0

        # Sum valid TAR and energy
        total_tar = sum(ev.tar_valid_cfm_min for ev in event_validations)
        total_energy = sum(ev.energy_valid_wh for ev in event_validations)

        # Calculate overall efficiency (from valid events only)
        if total_energy > 0:
            # TAR is CFM-min, energy is Wh
            # Efficiency = (TAR / minutes) / (energy / hours) = CFM/W
            valid_minutes = sum(
                ev.tar_valid_cfm_min / ev.cfm_avg if ev.cfm_avg > 0 else 0
                for ev in event_validations if ev.is_valid
            )
            valid_hours = total_energy / sum(
                ev.energy_valid_wh / (ev.tar_valid_cfm_min / ev.cfm_avg * 60)
                if ev.cfm_avg > 0 and ev.tar_valid_cfm_min > 0 else 0
                for ev in event_validations if ev.is_valid
            ) if total_energy > 0 else 0

            # Simpler: average efficiency of valid events
            valid_efficiencies = [
                ev.efficiency_cfm_w
                for ev in event_validations
                if ev.is_valid and ev.efficiency_cfm_w > 0
            ]
            avg_efficiency = (
                sum(valid_efficiencies) / len(valid_efficiencies)
                if valid_efficiencies else 0
            )
        else:
            avg_efficiency = 0

        # Calculate EI
        eef_vs_baseline, ei_clamped = self._calculate_ei(avg_efficiency)

        # Calculate raw metrics for reporting
        all_cfm = [s.get("fan", {}).get("cfm", 0) for s in samples]
        all_watts = [s.get("fan", {}).get("watts", 0) for s in samples]
        raw_avg_cfm = sum(all_cfm) / len(all_cfm) if all_cfm else 0
        raw_avg_watts = sum(all_watts) / len(all_watts) if all_watts else 0
        raw_total_tar = sum(ev.tar_cfm_min for ev in event_validations)
        raw_total_energy = sum(ev.energy_wh for ev in event_validations)

        # Token calculation
        # Formula: Tokens = Base_rate × TAR × EI × Quality_Factor / BCAI
        tokens_base = self.config.base_issuance_rate * ei_clamped * total_tar
        tokens_after_quality = tokens_base * quality_factor
        tokens_issued = tokens_after_quality / self.config.bcai_scalar

        # Calculate split
        split = self._calculate_split(tokens_issued)

        return EpochIssuance(
            epoch_id=epoch_id,
            device_id=device_id,
            total_tar_cfm_min=total_tar,
            total_energy_wh=total_energy,
            avg_cfm=raw_avg_cfm,
            avg_watts=raw_avg_watts,
            avg_efficiency_cfm_w=avg_efficiency,
            total_events=total_events,
            valid_events=valid_events,
            event_validations=event_validations,
            eef_vs_baseline=eef_vs_baseline,
            ei_clamped=ei_clamped,
            quality_factor=quality_factor,
            tokens_base=tokens_base,
            tokens_after_quality=tokens_after_quality,
            tokens_issued=tokens_issued,
            split=split,
            bcai=self.config.bcai_scalar,
            base_rate=self.config.base_issuance_rate,
        )

    def calculate_from_summary(
        self,
        epoch_id: str,
        device_id: str,
        total_tar_cfm_min: float,
        avg_efficiency_cfm_w: float,
        quality_factor: float = 1.0,
    ) -> EpochIssuance:
        """
        Simplified calculation from epoch summary (when samples not available).

        Useful for backend/verifier calculations where only aggregated
        metrics are available.
        """
        eef_vs_baseline, ei_clamped = self._calculate_ei(avg_efficiency_cfm_w)

        tokens_base = self.config.base_issuance_rate * ei_clamped * total_tar_cfm_min
        tokens_after_quality = tokens_base * quality_factor
        tokens_issued = tokens_after_quality / self.config.bcai_scalar

        split = self._calculate_split(tokens_issued)

        return EpochIssuance(
            epoch_id=epoch_id,
            device_id=device_id,
            total_tar_cfm_min=total_tar_cfm_min,
            total_energy_wh=0,
            avg_cfm=0,
            avg_watts=0,
            avg_efficiency_cfm_w=avg_efficiency_cfm_w,
            total_events=0,
            valid_events=0,
            event_validations=[],
            eef_vs_baseline=eef_vs_baseline,
            ei_clamped=ei_clamped,
            quality_factor=quality_factor,
            tokens_base=tokens_base,
            tokens_after_quality=tokens_after_quality,
            tokens_issued=tokens_issued,
            split=split,
            bcai=self.config.bcai_scalar,
            base_rate=self.config.base_issuance_rate,
        )


# Quick test
if __name__ == "__main__":
    print("BeautiFi Token Issuance Calculator Test")
    print("=" * 60)

    # Create calculator with default config
    calc = IssuanceCalculator()

    print("\nConfiguration:")
    print(f"  Base rate: {calc.config.base_issuance_rate} tokens/CFM-min")
    print(f"  Baseline efficiency: {calc.config.baseline_fan_efficiency} CFM/W")
    print(f"  EI range: [{calc.config.ei_min}, {calc.config.ei_max}]")
    print(f"  VOC range: [{calc.config.voc_min_ppm}, {calc.config.voc_max_ppm}] ppm")
    print(f"  BCAI scalar: {calc.config.bcai_scalar}")

    # Test with mock epoch data (matching Excel example)
    print("\n" + "=" * 60)
    print("Test: Epoch with 21,540 CFM-min, 3.78 CFM/W efficiency")
    print("=" * 60)

    result = calc.calculate_from_summary(
        epoch_id="ep-test-001",
        device_id="btfi-iot-001",
        total_tar_cfm_min=21540,
        avg_efficiency_cfm_w=3.78,
        quality_factor=1.0,
    )

    print(f"\nEfficiency Analysis:")
    print(f"  EEF vs baseline: {result.eef_vs_baseline:.4f}")
    print(f"  EI (clamped): {result.ei_clamped:.2f}")

    print(f"\nToken Issuance:")
    print(f"  Tokens (base): {result.tokens_base:.4f}")
    print(f"  Tokens (after quality): {result.tokens_after_quality:.4f}")
    print(f"  Tokens (issued): {result.tokens_issued:.4f}")

    print(f"\nIssuance Split:")
    print(f"  Facilities (75%): {result.split.to_facilities:.4f}")
    print(f"  Verifiers (5%): {result.split.to_verifiers:.4f}")
    print(f"  Treasury (10%): {result.split.to_treasury:.4f}")
    print(f"  Team (10%): {result.split.to_team:.4f}")

    # Compare with Excel expectation: 17.232 BTFI
    expected = 17.232
    print(f"\n  Expected (from Excel): {expected}")
    print(f"  Calculated: {result.tokens_issued:.4f}")
    print(f"  Match: {'YES' if abs(result.tokens_issued - expected) < 0.01 else 'NO'}")
