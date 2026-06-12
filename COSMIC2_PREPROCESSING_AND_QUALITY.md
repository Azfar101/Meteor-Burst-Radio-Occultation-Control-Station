# COSMIC-2 Data Preprocessing & Quality Control
## What You Need to Know for Meteor Trail Detection

---

## Quick Answer

**YES, COSMIC-2 ionPrf data is heavily preprocessed.** You're working with **Level-2 data**, meaning:

- ✓ Raw GPS signals have been processed through complex inversion algorithms
- ✓ Electron density profiles have been derived using Abel inversion
- ✓ Quality control has been applied (though NOT specifically for meteor trails)
- ⚠️ Known artifacts exist in the D-region (95-120 km) where meteor trails occur
- ⚠️ Some real signals may be filtered out; some artifacts may remain

---

## COSMIC-2 Processing Pipeline

```
Raw GNSS Signals
    ↓
Level 1b: TEC measurements (podTc2)
    ↓
[Quality Control]
    ↓
[Abel Inversion Algorithm]
    ↓
[Additional Filtering]
    ↓
Level 2: ionPrf (Electron Density Profiles) ← YOU ARE HERE
```

---

## What Processing Has Been Applied

### 1. **Signal Processing**
- Receiver oscillator drift correction
- Bending angle calculation
- Ionospheric corrections
- SNR (Signal-to-Noise) thresholding

### 2. **Abel Inversion**
The ionPrf product provides electron density profile data derived using the Abel inversion algorithm, which:
- Converts TEC (Total Electron Content) measurements to electron density
- Assumes spherical symmetry and vertical stratification
- Works top-down: starts at high altitude, works downward
- **Sensitive to errors at higher altitudes that propagate downward**

### 3. **Quality Control**
- Quality control (QC) checks applied after inversion
- Comparisons with climatological models
- Removal of profiles with extreme deviations
- Data flagging for problematic retrievals

---

## Known Issues in the D-Region (95-120 km) - YOUR METEOR ZONE

### ⚠️ CRITICAL ISSUE: E-Region Oscillations & Negative Values

CDAAC Ne profiles in the lower ionosphere are often oscillatory, which can sometimes result in large negative Ne values in the E-region. This is an artifact of the OP retrieval because the method is particularly sensitive to the residual errors induced by the Ne retrievals from higher altitudes.

**Translation:** When COSMIC-2 inverts electron density from top-down, errors at higher altitudes (F-region) can introduce oscillations and negative values at lower altitudes.

### Why This Matters for Meteor Detection

1. **False Negatives** — Real meteor trails might be smoothed out or removed during QC
2. **False Positives** — Oscillations from poor F-region retrievals could mimic meteor trails
3. **Ambiguity** — Is a spike a real meteor or an artifact from F-region errors?

### Our Finding in Your Data

Your File 1 showed **29 negative electron densities** at 175-209 km (F-region), which could propagate artifacts down to your meteor zone.

---

## Comparison of Inversion Methods

Two main algorithms process COSMIC-2 data:

| Feature | OP Method (CDAAC) | OE Method (V6p) |
|---------|-------------------|-----------------|
| **Approach** | Onion-peeling (top-down) | Optimal Estimation |
| **E-region quality** | ⚠️ Oscillatory, negatives | ✓ Much better |
| **Used for** | Standard ionPrf product | Research alternative |
| **D-region (95-120km)** | Artifact-prone | More reliable |

The OE/V6p method is designed to balance the hTEC measurement uncertainties of all levels such that the bottom side of the F-layer is less prone to the oscillation problems.

**Key Point:** Your ionPrf files likely use the CDAAC/OP method, which has **known D-region artifacts**.

---

## What Quality Checks COSMIC-2 Does Apply

### Quality Tests Performed
- ✓ SNR (Signal-to-Noise) validation
- ✓ Bending angle consistency checks (±50% from climatology)
- ✓ Orbital position validation
- ✓ Data gap detection
- ✓ Extreme value flagging
- ✓ Comparison with independent TEC data

### What They DON'T Check For
- ✗ Meteor trails specifically (too rare/unexpected)
- ✗ Transient D-region phenomena
- ✗ Short-period density spikes
- ✗ Physics-based spike classification

**This is good news for you:** Meteor trails aren't being systematically filtered out. They slip through because they're not part of normal QC checks.

---

## Quality by Location & Time

The unqualified ratio of COSMIC-2 profiles is about 25% near the equator and about 15% in middle and low-latitude areas. In terms of seasonal distribution, the quality of profiles is the worst in winter, followed by summer, and best in spring and autumn. In terms of day–night distribution, the unqualified ratio is higher at night than daytime.

**For your files:**
- File 1 (C2E6): Equatorial region → ~25% unqualified profiles
- File 2 (C2E2): Mid-latitude (~25°S) → ~15% unqualified profiles

---

## Can You Access Raw Data to Bypass Processing?

### Yes, but with limitations:

**Available Levels:**
- **Level 1b** (podTc2): Raw TEC measurements
  - Can re-invert with alternative algorithms
  - More complex processing required
  - Requires GNSS-RO signal processing expertise

- **Level 2** (ionPrf): Already processed
  - Convenient
  - But locked into CDAAC processing choices
  - **What you're currently using**

### Accessing Different Products

```python
# CDAAC Alternative Retrieval (OP method) - Current files
ionPrf_CDAAC  # Standard product with OP inversion

# Alternative: V6p / OE method (Optimal Estimation)
# Contact: COSMIC Data Analysis Center
# May reduce D-region artifacts significantly
```

**Recommendation for MBC:** If detecting marginal meteor trails, consider requesting:
1. **Original files** for your best events (File 1)
2. **V6p/OE reprocessing** to eliminate OP artifacts
3. **Raw Level 1b data** for custom inversion if critical

---

## How Filtering Could Affect Meteor Trails

### Potential False Negatives (Missed Meteors)

**Scenario 1: Aggressive smoothing**
- QC may apply smoothing to remove noise
- Real but narrow meteor trails (0.5-1 km) could be smoothed out
- Your spike might be real but wasn't captured

**Scenario 2: F-region error propagation**
- Poor F-region retrieval → oscillations in E-region
- QC identifies as "bad profile" → entire profile rejected
- Meteor trail at 108 km lost along with bad F-region data

**Scenario 3: Spike removal**
- Automated QC might flag isolated peaks as errors
- "That looks like a data glitch" → removed
- Actual meteor trail deleted

### Potential False Positives (Noise Labeled as Real)

**Scenario 1: OP inversion artifacts**
- E-region oscillations propagate to D-region
- Look like spikes in raw data but are mathematical artifacts
- oscillatory profiles in the E-region from processing

**Scenario 2: Incomplete filtering**
- QC designed for typical ionospheric features
- Unexpected transient phenomena (like meteors) pass through
- Some noise slips through if it's not flagged as extreme

---

## Your Classifier Accounts for This!

Your new classifier is **actually quite robust** because it:

✓ Uses multi-criteria assessment (not just spike detection)  
✓ Checks physical plausibility (symmetry, shape, smoothness)  
✓ Doesn't rely on QC flags that might filter meteors  
✓ Catches artifacts (asymmetric, jagged shapes)  

The reason it correctly identified File 1 as real and File 2 as noise is that **physical criteria (symmetry, smoothness) are better than signal-level thresholds** at distinguishing real meteors from processing artifacts.

---

## Recommendations for Robust Meteor Detection

### 1. **Validate With Independent Data**
- ✓ Cross-check with ground-based meteor radar
- ✓ Compare with other satellite observations (Swarm, Spire)
- ✓ Verify with ionosonde measurements if available

### 2. **Use the Classifier Conservatively**
- Your asymmetry metric (0.11 vs 0.71) is excellent discriminator
- It's not affected by preprocessing choices
- **Rely on structure, not absolute magnitude**

### 3. **Request Alternative Processing**
For critical detections:
```python
# Option 1: V6p reprocessing
"Request OE inversion for comparison"
# Eliminates OP artifacts

# Option 2: Raw Level 1b data
"Obtain podTc2 (TEC) for custom inversion"
# Full control over processing

# Option 3: Validation satellite
"Cross-check with Spire constellation data"
# Different processing pipeline
```

### 4. **Understanding Your Data Quality**

For File 1 (Your acceptance):
- **What could have been filtered:** Some weak meteor trails (SNR < 1.5σ)
- **What could have been added:** OP artifacts in F-region (but asymmetry check catches them)
- **Confidence level:** Good (7.3/10) because structure is clean

For File 2 (Your rejection):
- **What you see:** OP inversion artifact or noise spike
- **Why it wasn't filtered:** Not extreme enough for QC
- **Classifier catches it:** Asymmetry = 0.71 (clearly not real)

---

## What Quality Flags Are Stored in ionPrf Files?

The ionPrf netCDF files contain metadata but **not the processing artifacts you'd hope to see**:

```
Variables in ionPrf:
✓ MSL_alt          - Altitude
✓ ELEC_dens        - Electron density
✓ GEO_lat/lon      - Location
? [Quality flags]  - Limited/non-standard
```

**Problem:** Quality flags in ionPrf are minimal and don't specify:
- Which inversion method was used (OP vs OE)
- Whether smoothing was applied
- If F-region errors propagated downward
- Whether the profile is questionable in D-region

---

## Bottom Line for Your MBC Application

| Concern | Impact | Your Protection |
|---------|--------|-----------------|
| Some meteors filtered out | False negatives | Use lenient thresholds (accept score 4+) |
| OP artifacts slip through | False positives | Asymmetry metric (0.71 → reject) |
| Processing not optimized for D-region | Uncertainty | Cross-validate with radar |
| Quality varies by location/time | Variable reliability | Check File 1 (good) vs File 2 (poor) locations |

**Verdict:** COSMIC-2 ionPrf is suitable for meteor detection **if you use your classifier**, which compensates for preprocessing ambiguities through physics-based criteria rather than trusting QC flags.

---

## References & Further Reading

Optimal Estimation Inversion of Ionospheric Electron Density Profiles - Explains OE vs OP method differences

Quality assessment of ionospheric density profiles based on long-term COSMIC 1 and 2 observations - Documents quality issues by location

Accuracy assessment of COSMIC-2 F2 peak parameters - Validation against ionosondes

---

## Accessing Original Data

If you want to explore alternative processing:

**Standard CDAAC ionPrf:**
- https://data.cosmic.ucar.edu/gnss-ro/cosmic2/postProc/
- Uses OP inversion
- What you have now

**Alternative Sources:**
- TACC (Taiwan Analysis Center): https://tacc.cwb.gov.tw/
- GeoOptics independent processing
- NASA UCAR alternative algorithms

---

**Key Takeaway:** Yes, COSMIC-2 is preprocessed with known D-region artifacts, but your classifier compensates by using **physics-based criteria** rather than relying on quality flags. Your approach of checking symmetry, shape, and SNR is actually **better** than trusting QC flags that aren't optimized for meteor detection.

For MBC applications requiring high confidence, cross-validation with ground-based radar is recommended for critical detections.
