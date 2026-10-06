#!/usr/bin/env python3
"""Fitment calculator for the AE86 K24 swap. Crude but useful.

Compares bay dimensions against donor + mount geometry to predict the two
clearances that matter: oil pan to crossmember, and hood clearance over
the intake. Reads measurements/bay-dimensions.csv.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Constants from donor/donor-specs.md (published figures)
ENGINE_HEIGHT_MM = 548.6          # sump to valve cover, stock pan
OIL_PAN_DEPTH_MM = 180.0          # at sump
INTAKE_STACK_MM = 210.0           # RBC manifold + filter stack above cam cover

def load_bay():
    rows = {}
    with open(os.path.join(HERE, "..", "measurements", "bay-dimensions.csv")) as fh:
        for row in csv.DictReader(fh):
            rows[row["measurement"]] = (float(row["value_mm"]), row["status"])
    return rows

def check(rows):
    problems = []
    # Oil pan clearance: crossmember distance minus pan depth
    pan_avail = rows["crossmember_to_oilpan_area"][0]
    pan_clear = pan_avail - OIL_PAN_DEPTH_MM
    if pan_clear < 15.0:
        problems.append(f"oil pan clearance {pan_clear:.0f}mm < 15mm minimum - needs pan swap or notch")
    # Hood clearance: bay height minus engine height minus intake stack
    hood = rows["bay_height_hood_underside"][0]
    stack_total = ENGINE_HEIGHT_MM + INTAKE_STACK_MM
    if hood < stack_total:
        problems.append(f"hood clearance tight: bay {hood:.0f}mm vs stack {stack_total:.0f}mm")
    # Bay width sanity: rails vs engine length
    width = rows["bay_width_rail_to_rail"][0]
    if width < 600:
        problems.append("bay width implausible - check measurement")
    return problems

def main():
    rows = load_bay()
    problems = check(rows)
    if problems:
        print("FITMENT PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("all clearances nominal")

if __name__ == "__main__":
    main()
