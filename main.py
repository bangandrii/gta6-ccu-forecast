"""Forecasting program that predicts 24-hour launch viewer curves using weighted comparable historical launches.
It computes hour-1 baseline viewers, weights historical curves by baseline similarity, and blends empirical weighted quantiles with a weighted normal fit in log space.
The resulting quantiles are clamped, rounded, and saved as JSON output per case."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


# Tuning, chosen by cross-validation over the practice cases' comparables
# (each comparable in turn forecast from the others): launches of a similar
# size carry the most signal, and the normal fit steadies the extreme
# quantiles the small sample cannot pin down.
BANDWIDTH = 0.8
EMPIRICAL_BLEND = 0.3


def parse_time(t):
    """Parse timestamp string or number into float seconds."""
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, str):
        try:
            s = t.replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            return dt.timestamp()
        except Exception:
            try:
                return float(t)
            except Exception:
                return t
    return t


def hour_one_print(case):
    """Determine hour-1 print viewers (p) for the case."""
    # 1. case["known"]["viewers"] when present and positive
    known = case.get("known")
    if known and isinstance(known, dict):
        v = known.get("viewers")
        if v is not None and v > 0:
            return float(v)

    day_start = case.get("day_start")
    parsed_day_start = parse_time(day_start)

    # 2. viewers of history_hourly row whose "from" equals day_start
    history_hourly = case.get("history_hourly", [])
    if day_start is not None:
        for row in history_hourly:
            rf = row.get("from")
            if rf is not None and (rf == day_start or parse_time(rf) == parsed_day_start):
                v = row.get("viewers")
                if v is not None and v > 0:
                    return float(v)

    # 3. mean of history points inside the day's first hour
    if parsed_day_start is not None and isinstance(parsed_day_start, (int, float)):
        end_t = parsed_day_start + 3600.0
        first_hour_viewers = []
        for row in history_hourly:
            rf = row.get("from")
            v = row.get("viewers")
            if rf is not None and v is not None and v > 0:
                pt = parse_time(rf)
                if isinstance(pt, (int, float)) and parsed_day_start <= pt < end_t:
                    first_hour_viewers.append(float(v))
        if first_hour_viewers:
            mean_v = sum(first_hour_viewers) / len(first_hour_viewers)
            if mean_v >= 1.0:
                return mean_v

    # 4. if below 1, use 1
    return 1.0


def comparable_curves(case, p):
    """Process and filter comparable past launches, returning valid curves with weights and log ratios."""
    comparables = case.get("comparables", [])
    kept = []

    for comp in comparables:
        comp_day_start = comp.get("day_start")
        hourly = comp.get("hourly", [])
        if not comp_day_start or not hourly:
            continue

        t1 = parse_time(comp_day_start)
        hourly_map = {}
        for pt in hourly:
            rf = pt.get("from")
            rv = pt.get("viewers")
            if rf is not None and rv is not None:
                hourly_map[parse_time(rf)] = float(rv)

        v1 = hourly_map.get(t1)
        if v1 is None or v1 <= 0:
            continue

        # Check hours 2..24 (23 hours)
        hour_viewers = {}
        valid_count = 0
        for h in range(2, 25):
            th = t1 + (h - 1) * 3600.0 if isinstance(t1, (int, float)) else None
            # Also check exact matching or close float matching if needed
            val = None
            if th is not None:
                # Try exact float match or search within small tolerance
                for k, v in hourly_map.items():
                    if isinstance(k, (int, float)) and abs(k - th) < 1.0:
                        val = v
                        break
            if val is not None and val > 0:
                hour_viewers[h] = val
                valid_count += 1

        if valid_count < 20:
            continue

        # Fill missing hours with nearer present hour's ratio
        ratios = {}
        present_hours = sorted(hour_viewers.keys())
        for h in range(2, 25):
            if h in hour_viewers:
                ratios[h] = math.log(hour_viewers[h] / v1)
            else:
                # Find nearer present hour
                nearest_h = min(present_hours, key=lambda ph: abs(ph - h))
                ratios[h] = math.log(hour_viewers[nearest_h] / v1)

        weight = math.exp(-abs(math.log(p) - math.log(v1)) / BANDWIDTH)
        kept.append({"ratios": ratios, "weight": weight})

    return kept


def weighted_quantile(pairs, levels):
    """Compute weighted empirical quantiles given (value, weight) pairs."""
    if not pairs:
        return [0.0] * len(levels)

    sorted_pairs = sorted(pairs, key=lambda x: x[0])
    total_weight = sum(w for _, w in sorted_pairs)
    if total_weight <= 0:
        val = sorted_pairs[0][0]
        return [val] * len(levels)

    # Build cumulative weights
    cum_weights = []
    cum = 0.0
    for v, w in sorted_pairs:
        cum += w
        cum_weights.append(cum)

    quantiles = []
    for q in levels:
        target = q * total_weight
        # Find first index where cum_weight >= target
        idx = 0
        while idx < len(cum_weights) and cum_weights[idx] < target:
            idx += 1

        if idx == 0:
            quantiles.append(sorted_pairs[0][0])
        elif idx >= len(sorted_pairs):
            quantiles.append(sorted_pairs[-1][0])
        else:
            w_prev = cum_weights[idx - 1]
            w_curr = cum_weights[idx]
            x_prev = sorted_pairs[idx - 1][0]
            x_curr = sorted_pairs[idx][0]
            if w_curr == w_prev:
                quantiles.append(x_curr)
            else:
                frac = (target - w_prev) / (w_curr - w_prev)
                quantiles.append(x_prev + frac * (x_curr - x_prev))

    return quantiles


def weighted_mean_sd(pairs):
    """Compute weighted mean and standard deviation given (value, weight) pairs."""
    if not pairs:
        return 0.0, 1.0

    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        mean_v = sum(v for v, w in pairs) / len(pairs)
        return mean_v, 1.0

    mean_v = sum(v * w for v, w in pairs) / total_weight
    variance = sum(w * (v - mean_v) ** 2 for v, w in pairs) / total_weight
    sd = math.sqrt(variance)
    if sd <= 0:
        sd = 1e-6

    return mean_v, sd


def fallback_rows(p):
    """Generate fallback 24-hour forecast curves using widening log-normal spread."""
    hours_output = []
    z_vals = [-1.644854, -0.674490, 0.0, 0.674490, 1.644854]

    for h in range(2, 25):
        raw_qs = [p * math.exp(z * 0.15 * math.sqrt(h - 1)) for z in z_vals]

        # Post-process: non-decreasing, clamp into (0, 1e9], round to 2 decimals
        qs = []
        prev = 0.0
        for val in raw_qs:
            val = max(val, prev)
            prev = val
            val = max(1e-9, min(val, 1e9))
            qs.append(round(val, 2))

        hours_output.append({"hour": h, "q": qs})

    return {"hours": hours_output}


def forecast_case(case):
    """Generate the 24-hour forecast curves for a single case object."""
    p = hour_one_print(case)
    kept_comps = comparable_curves(case, p)

    hours_output = []
    z_vals = [-1.644854, -0.674490, 0.0, 0.674490, 1.644854]
    levels = [0.05, 0.25, 0.5, 0.75, 0.95]

    for h in range(2, 25):
        pairs = []
        for comp in kept_comps:
            r = comp["ratios"].get(h)
            w = comp["weight"]
            if r is not None:
                pairs.append((r, w))

        if not pairs:
            # Fallback if no pairs
            eqs = [0.0] * 5
            norms = [0.0] * 5
        else:
            eqs = weighted_quantile(pairs, levels)
            mu, sd = weighted_mean_sd(pairs)
            norms = [mu + z * sd for z in z_vals]

        blended = [EMPIRICAL_BLEND * eq + (1 - EMPIRICAL_BLEND) * n for eq, n in zip(eqs, norms)]
        raw_qs = [p * math.exp(b) for b in blended]

        # Post-process: non-decreasing, clamp into (0, 1e9], round to 2 decimals
        qs = []
        prev = 0.0
        for val in raw_qs:
            val = max(val, prev)
            prev = val
            val = max(1e-9, min(val, 1e9))
            qs.append(round(val, 2))

        hours_output.append({"hour": h, "q": qs})

    return {"hours": hours_output}


def main():
    """Main execution entry point for processing input cases and writing outputs."""
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        return

    in_files = sorted(input_dir.glob("*.in"))
    for in_path in in_files:
        # One bad case must not sink the whole run.
        try:
            with open(in_path, "r", encoding="utf-8") as f:
                case = json.load(f)

            result = forecast_case(case)
            case_id = case.get("id", in_path.stem)
        except Exception:
            try:
                with open(in_path, "r", encoding="utf-8") as f:
                    case = json.load(f)
                p = hour_one_print(case)
                case_id = case.get("id", in_path.stem)
            except Exception:
                p = 1.0
                case_id = in_path.stem
            result = fallback_rows(p)

        out_path = output_dir / f"{case_id}.out"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f)


if __name__ == "__main__":
    main()
