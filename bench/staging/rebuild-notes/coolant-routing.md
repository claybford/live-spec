# Coolant routing plan

Binder transcription 2026-10. Driven by the bench overflow events
(known-issues.md): air pockets after refill are the working suspicion, so
the plan routes to keep the system purge-able.

## Circuit

- RADI-42 42mm aluminium radiator: top-left outlet → K24 thermostat housing
  (52mm stat, 82 °C), bottom-right return to water pump inlet.
- Heater core feed tees from the throttle-body bypass port on the RBC
  manifold (K-series needs the bypass bleed even without a heater loop
  restriction).
- Expansion/overflow bottle retained: recovery line to radiator neck,
  15 psi cap.
- Fill strategy per binder: front-end raised, heater full hot, funnel
  bleed at thermostat housing, idle 10 min with cap off, top-up, cap,
  road-test warm, re-check cold.

## Notes tied to known issues

- 2026-09-20 overflow (~200 ml) and later recurrences are logged in
  known-issues.md; this routing does not yet change the diagnosis
  (suspected air pocket after refill, unconfirmed).
- If overflow recurs after the swap with a properly bled system, revisit
  head-gasket direction and log the recurrence in the spec.

## Hose spec

- 19 mm ID for bypass/heater small circuit, 32 mm ID main returns.
- Fittings at radiator are 34 mm OD clamshells — stock AE86 hoses do not fit.
