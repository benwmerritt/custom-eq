# Custom EQ Repository

Personal headphone EQ presets in [OPRA](https://github.com/opra-project/OPRA) format for use with Roon's MUSE Headphone EQ custom repository feature, plus reference notes for squig.link/hangout.audio target curve workflows.

## Quick Start

```bash
# 1. Drop your EqualizerAPO .txt exports into inbox/
#    Named: "Vendor - Product - EQ Name.txt"
cp "HiFiMAN - Arya Organic - Ben Relaxed.txt" inbox/

# 2. Run the converter
python3 convert.py

# 3. Commit and push
git add -A && git commit -m "Add new EQ presets" && git push
```

Roon pulls from `dist/database_v1.jsonl` in this repo. After pushing, refresh or restart Roon to pick up changes.

## Repository Structure

```
custom-eq/
  inbox/                     # Drop raw .txt EQ exports here
  processed/                 # Files move here after conversion
  database/                  # Human-readable OPRA source files
    vendors/
      <vendor_slug>/
        info.json
        products/
          <product_slug>/
            info.json
            eq/
              <eq_slug>/
                info.json    # The actual EQ preset
  dist/
    database_v1.jsonl        # Auto-generated -- what Roon reads
  convert.py                 # The conversion script
```

## File Naming Convention

Files in `inbox/` must be named:

```
Vendor - Product - EQ Name.txt
```

Examples:
- `HiFiMAN - Arya Organic - Ben Relaxed.txt`
- `Hisenior - Mega7 - 5128 DF.txt`
- `Sennheiser - HD650 - Oratory Harman.txt`

If a file only has two parts (`Vendor - Product.txt`), the EQ name defaults to "custom". If the format can't be parsed at all, it falls back to `custom/filename/custom`.

## Roon Setup

In Roon:

1. Open **MUSE** (the DSP/audio controls)
2. Go to **Headphone EQ**
3. Find the **Custom Repository** field
4. Enter the raw dist URL: `https://raw.githubusercontent.com/benwmerritt/custom-eq/main/dist/`

If Roon expects a direct database file URL instead of a repository/base URL, use:
`https://raw.githubusercontent.com/benwmerritt/custom-eq/main/dist/database_v1.jsonl`
5. Your custom presets will appear alongside OPRA entries

Roon reads `database_v1.jsonl` from the URL you give it. On GitHub, the Roon-consumable file is exposed through the raw URL above, not the normal `https://github.com/...` repository page.

## How It Works

### The OPRA Format

Roon's headphone EQ system (OPRA) uses a JSONL database where each line is one of three entry types:

**Vendor:**
```json
{"type":"vendor","id":"hifiman","data":{"name":"HiFiMAN"}}
```

**Product:**
```json
{"type":"product","id":"hifiman::arya_organic","data":{"name":"Arya Organic","type":"headphones","subtype":"over_the_ear","vendor_id":"hifiman"}}
```

**EQ Preset:**
```json
{"type":"eq","id":"hifiman:arya_organic::ben_relaxed","data":{"author":"Ben Merritt","details":"Ben Relaxed","type":"parametric_eq","parameters":{"gain_db":-5.4,"bands":[{"type":"peak_dip","frequency":90,"gain_db":-2.8,"q":0.55}]},"product_id":"hifiman::arya_organic"}}
```

ID format:
- Vendor: `vendor_slug`
- Product: `vendor_slug::product_slug`
- EQ: `vendor_slug:product_slug::eq_slug`

### EqualizerAPO to OPRA Mapping

| APO Format | OPRA Type |
|---|---|
| `PK` (Peak) | `peak_dip` |
| `LSC` / `LS` (Low Shelf) | `low_shelf` |
| `HSC` / `HS` (High Shelf) | `high_shelf` |
| `Preamp: X dB` | `parameters.gain_db` |
| `Filter N: OFF ...` | Omitted (not included) |

OPRA only supports `peak_dip`, `low_shelf`, and `high_shelf`. Other APO filter types (notch, allpass, bandpass) have no OPRA equivalent and will be skipped with a warning.

### Adding EQs Manually

You can also create entries directly in `database/` without going through the inbox. Just follow the folder structure and run `python3 convert.py` to rebuild `dist/`.

Example `database/vendors/hifiman/products/arya_organic/eq/ben_relaxed/info.json`:
```json
{
  "author": "Ben Merritt",
  "details": "Relaxed preference target",
  "link": "https://github.com/benwmerritt/custom-eq",
  "type": "parametric_eq",
  "parameters": {
    "gain_db": -5.4,
    "bands": [
      { "type": "low_shelf", "frequency": 105, "gain_db": 5.5, "q": 0.71 },
      { "type": "peak_dip", "frequency": 1900, "gain_db": 6.0, "q": 1.2 },
      { "type": "peak_dip", "frequency": 2900, "gain_db": -4.0, "q": 2.3 },
      { "type": "high_shelf", "frequency": 10000, "gain_db": -1.0, "q": 0.71 }
    ]
  }
}
```

---

## Squig.link / Hangout.audio Target Curves

Separate from Roon, these tools are useful for generating EQ presets via AutoEQ.

### Upload Format

Both squig.link and hangout.audio accept `.txt` or `.csv` files with two numeric columns:

```
frequency_hz    level_db
20              -3.45
20.5            -3.40
21              -3.35
...
```

Requirements:
- Delimiter: spaces, tabs, or commas all work
- Minimum **128 data points** or you get "Parse frequency response file failed: invalid format"
- Should cover **20 Hz - 20 kHz**
- Header lines (non-numeric) are silently ignored
- Lines starting with `*` are ignored (REW comment format)

### Upload FR vs Upload Target

- **Upload FR** loads a curve as a headphone measurement -- you can then AutoEQ it toward any target
- **Upload Target** loads a curve as the goal -- AutoEQ will try to match other headphones to this curve

### Using Oratory1990 Data

Oratory's raw FR CSV files from the [AutoEQ GitHub repo](https://github.com/jaakkopasanen/AutoEq/tree/master/results) work directly with both Upload FR and Upload Target. The CSV has many columns but squig.link only reads the first two (frequency and raw dB).

For the Arya Organic specifically, download the CSV from AutoEQ's oratory1990 results and upload directly. The file has thousands of rows, well above the 128 minimum.

### Creating a Custom Preference Target

1. Download `zero.csv` from [AutoEQ's compensation folder](https://github.com/jaakkopasanen/AutoEq/blob/master/compensation/zero.csv) (flat line)
2. Upload it as FR on squig.link via "Upload FR"
3. Use the built-in parametric EQ to shape it to your preference (bass shelf, treble tilt, etc.)
4. Export the result
5. Re-upload as "Upload Target" for future AutoEQ use

Alternatively, start from an existing target (Harman, IEF Neutral, etc.) and modify it.

### Rig Compatibility Warning

Measurements from different rigs (oratory1990's GRAS vs Super* Review's coupler) are not directly comparable above ~3kHz. Using oratory FR as a target for another oratory-measured headphone is clean. Cross-rig comparisons will have high-frequency discrepancies.

---

## Dependencies

- Python 3.10+ (no external packages needed)
- Git

## Workflow Summary

```
Export EQ from squig.link/Peace/wherever
        |
        v
    inbox/*.txt
        |
   python3 convert.py
        |
        v
  database/  (human-readable JSON)
  dist/database_v1.jsonl  (Roon-consumable)
        |
   git push
        |
        v
  Roon picks up changes
```
