# Wiring conversion plan — pin by pin

K20A2 ECU (K-Pro v4) on the K24A2 harness, integrated to the AE86 SR5 chassis
harness. Binder transcription 2026-10.

## Engine-side (K20A2 ECU connector A/B, key pins)

| ECU pin | Function | Goes to | Note |
|---|---|---|---|
| A4 | INJ1 | injector 1 | via resistor box delete |
| A5 | INJ2 | injector 2 | |
| A6 | INJ3 | injector 3 | |
| A7 | INJ4 | injector 4 | |
| A12 | IGP+ | main relay 87 | fused 10A |
| A13 | IGP+ | main relay 87 | paired |
| A24 | PG | grounds G101/G102 | twin ground |
| B2 | CKP sensor | CKP shield pair | twisted, shield grounded one end |
| B10 | TPS1 | throttle position sensor | calibrate at K-Pro stage |
| B11 | MAP | MAP sensor | RBC intake, keep OE hose route |
| B15 | IAT | intake air temp | relocate to intake, post-filter |
| B32 | ECT1 | coolant temp (ECU) | single-wire OEM gauge separate |
| A10 | VSS | AE86 speed sensor interface | DRB conversion at gearbox |
| A21 | A/C relay | n/c (no A/C planned) | taped off |
| A26 | Alternator L | K24 alternator L terminal | charge lamp polarity |

## Chassis-side (AE86 SR5)

- Ignition switch start/run feeds relocated to relay panel (G104).
- Fuel pump feed: OE circuit retained, relay trigger from main relay 86.
- Gauge cluster: tach recalibration deferred to K-Pro output; temp gauge
  uses separate single-wire sender in housing port 2.
- Reverse lamp switch: 6MT position switch, pin A26 pigtail.
- Every splice solder + adhesive heat-shrink; binder rule: no crimp-only
  splices in the engine bay.

## Grounds

| Point | Joins |
|---|---|
| G101 | ECU PG, engine block, left of thermostat housing |
| G102 | ECU PG, chassis rail, battery negative strut |
| G104 | relay panel star, firewall |
