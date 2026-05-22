---
name: anonymize-timeseries
description: "De-identify time series data files (CSV, parquet, XML, JSON) so they can be safely shared or used as test fixtures. Preserves file format, column structure, and approximate signal trajectories while removing all patient/subject identifiers, shifting dates, distorting values non-linearly, and trimming duration. Use this skill whenever the user wants to anonymize clinical data, create synthetic test data from real recordings, strip patient identifiers from physiological signals, prepare shareable example datasets, or make data 'safe to commit'. Also trigger when the user mentions de-identification, data anonymization, HIPAA-safe data, removing PHI from files, or creating test fixtures from real patient recordings."
---

# Anonymize Time Series Data

Turn real clinical/physiological recordings into safe-to-share test data that preserves format and signal shape but cannot be traced back to any individual.

## Workflow

### Step 1: Assess the data

- List all files in the input folder (recursively if needed).
- Identify file types: CSV, TSV, parquet, JSON, XML, or other.
- Open a sample file of each type to understand column names, data shapes, and what looks like PII.
- **Flag non-data files** (text, logs, PDFs, images, etc.) — these must NOT be blindly copied. Ask the user what to do with them, or skip them with a warning.

### Step 2: Identify PII columns and values

Scan column names and sample values for identifiers. Use these patterns as a starting point, but also apply judgment — any column that could single out a person is PII.

**Column name patterns** (case-insensitive):
- Patient/subject IDs: `patient`, `pat_id`, `subject`, `subj`, `person`, `individual`, `mrn`, `medical_record`, `ssn`, `national_id`, `nhs`
- Names: `first_name`, `last_name`, `surname`, `family_name`, `given_name`, `full_name`
- Contact/location: `address`, `street`, `city`, `zip`, `postal`, `phone`, `email`, `fax`
- Dates of birth: `birth_date`, `dob`, `date_of_birth`
- Facility/staff: `bed_id`, `room_num`, `ward`, `serial_number`, `device_id`, `doctor`, `physician`, `nurse`, `clinician`, `provider`, `hospital`, `facility`, `institution`
- Admission info: `admission_date`, `admit_date`, `discharge_date`

**Cell value patterns**:
- IDs like `P00123`, `MRN1234567` (1-3 uppercase letters followed by 4+ digits)
- SSN format: `123-45-6789`
- Full names: `FirstName LastName` (two capitalized words) — but be aware this has false positives; use column context to decide

**Also check for**: custom study codes, device serial formats, or facility-specific ID schemes in the user's data. Ask if unsure.

### Step 3: Write a tailored anonymization script

Write a Python script (using pandas + numpy) specific to the user's data. The script must apply ALL of the following layers:

#### 3a. Time axis shifting
Shift all timestamps so data starts at `2004-09-15T08:12:33`. Apply to:
- DatetimeIndex in parquet
- Datetime columns (auto-detected or explicitly identified)
- String-formatted timestamps (parse, shift, reformat in original format)

#### 3b. Duration trimming
Trim to a maximum of **50 minutes** from the earliest timestamp (configurable). This keeps files small and removes temporal fingerprinting from recording length.

#### 3c. Non-linear value distortion
Transform every numeric signal column through these layers so no original value survives:

```
1. Random multiplicative scale:  value *= uniform(0.82, 1.18)
2. Additive offset:              value += uniform(-0.08, 0.08) * signal_range
3. Quadratic warping:            value += uniform(-0.0005, 0.0005) * (value - mean)^2
4. Slow sinusoidal perturbation: value += 0.03 * range * sin(freq * i + phase)
                                 where freq = uniform(1,3) * 2pi / n_samples
5. Gaussian noise:               value += normal(0, 0.005 * range)
```

This preserves the general trajectory (a rising signal still rises) but no individual sample matches the original. Keep integer columns as integers (round after transforms). Use a deterministic seed per column for reproducibility.

#### 3d. Identifier replacement
- Replace values in PII columns with `SYNTHETIC`
- Replace cell values matching ID patterns with `SYNTHETIC`
- Sanitize filenames:
  - Replace patient/subject identifiers with `SYNTH`: `Patient01_waves.csv` → `patient_SYNTH_waves.csv`
  - **Preserve date/time structure** in filenames by replacing original dates/times with the shifted reference datetime (`2004-09-15T08:12:33`), formatted to match the original pattern. For example: `Patient01_25_03_12-13_42_47_waves.csv` → `patient_SYNTH_04_09_15-08_12_33_waves.csv`. This avoids losing temporal metadata that downstream tools or users may rely on for file identification.

#### 3e. Metadata sanitization
- **JSON config files**: Recursively walk the structure. Replace identifying keys/values with `SYNTHETIC`. Clean path-like strings containing patient references. Preserve structure.
- **XML files**: Replace content in identifying elements (`<patientId>`, `<subjectId>`, `<mrn>`, `<firstName>`, `<lastName>`, etc.) and attributes (`patientId="..."`, `mrn="..."`) with `SYNTHETIC`.

### Step 4: Run and verify

After running, spot-check the output:

1. **No original timestamps survive** — compare a few rows between input and output
2. **No identifying strings in any file** — grep for known patient IDs, names, or facility names across all output files
3. **Signal shapes are plausible** — values should be in a realistic range, not garbage
4. **File format is identical** — the output should load with the exact same code as the original
5. **Filenames are clean** — no patient identifiers in directory names or filenames
6. **No un-sanitized files were copied through** — every file in the output was deliberately handled

Report the verification results to the user.

## Adaptation guidance

- **Binary/proprietary formats**: Write a loader that converts to DataFrame, apply the numeric + datetime + PII transforms, save back in the original format.
- **Very high frequency signals** (>1 kHz): Increase sinusoidal perturbation frequency proportionally.
- **Unusual ID formats**: Ask the user about any domain-specific identifier schemes before processing.

## Dependencies

Only `pandas` and `numpy` are required.

**Before writing or running any Python code**, ask the user which Python environment to use (e.g. a virtualenv path to source, a conda env name, or system Python). Use their answer to activate the environment before every Python invocation. Do not assume system Python has the required packages.
