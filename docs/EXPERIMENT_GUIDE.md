# Experiment Runbook

> Status: **engineering draft**. Do not collect final paper data until the preflight section is explicitly frozen.

## 1. Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp config/testbed.example.yaml config/testbed.yaml
```

Populate `config/testbed.yaml` locally. It is ignored by Git and must not be committed.

## 2. Freeze an experiment input before touching OAI

For every publishable TLE experiment:

1. save the exact constellation TLE snapshot under the private/untracked `data/tle/` directory;
2. record where and when it was obtained;
3. compute provenance and hash it;
4. select passes by the predeclared rule;
5. generate deterministic trace CSVs;
6. use those same traces for every repeated comparison.

Example provenance capture:

```bash
ntn-exp provenance \
  --config config/testbed.yaml \
  --framework-root . \
  --tle-file data/tle/constellation_snapshot.tle \
  --output results/engineering/provenance.json
```

## 3. Select the predeclared high/medium/low passes

```bash
ntn-exp select-passes \
  --tle-file data/tle/constellation_snapshot.tle \
  --start 2026-08-15T00:00:00Z \
  --horizon-hours 48 \
  --lat <UE_LATITUDE> \
  --lon <UE_LONGITUDE> \
  --alt-m <UE_ALTITUDE_METRES> \
  --elevation-mask-deg 10 \
  --output results/engineering/selected_passes.json
```

The script chooses the first chronological matching pass in each frozen geometry band:

- high: maximum elevation >= 75 degrees;
- medium: 40–60 degrees;
- low: 20–30 degrees.

If a band is missing, do **not** manually choose an attractive pass. Extend the documented search horizon or revise the band before inspecting network/application outcomes.

## 4. Generate a deterministic orbital trace

```bash
ntn-exp tle-trace \
  --tle-file data/tle/constellation_snapshot.tle \
  --satellite <NORAD_ID_OR_NAME> \
  --start <TRACE_START_UTC> \
  --duration-s <DURATION> \
  --step-s 1 \
  --ue-lat <UE_LATITUDE> \
  --ue-lon <UE_LONGITUDE> \
  --ue-alt-m <UE_ALTITUDE_METRES> \
  --gateway-lat <GATEWAY_LATITUDE> \
  --gateway-lon <GATEWAY_LONGITUDE> \
  --gateway-alt-m <GATEWAY_ALTITUDE_METRES> \
  --nr-carrier-hz <NR_CARRIER_HZ> \
  --feeder-carrier-hz <FEEDER_CARRIER_HZ> \
  --elevation-mask-deg 10 \
  --output results/engineering/pass_trace.csv
```

If the controlled architecture uses co-located logical UE and gateway ground positions, omit the gateway arguments; the generator then uses the UE point for both legs.

The trace retains access- and feeder-leg geometry separately and also reports the total transparent-path geometric delay.

## 5. Preflight gate — mandatory before final experiments

The following must all pass:

- [ ] exact OAI commit/tag recorded;
- [ ] exact Open5GS version recorded;
- [ ] gNB starts cleanly;
- [ ] UE registers and reaches `RRC_CONNECTED`;
- [ ] PDU session establishes;
- [ ] UE tunnel can reach the data-network endpoint bidirectionally;
- [ ] chrony/NTP offset is within the one-way-latency acceptance threshold when one-way delay will be reported;
- [ ] gNB log collector captures MCS, SNR/SINR, BLER, DTX/UL failure and sync events where available;
- [ ] UE log collector captures NTN/SIB19/timing/Doppler and RRC events where available;
- [ ] application metrics can be aligned to the same experiment timebase;
- [ ] every run writes a provenance manifest;
- [ ] failed runs are retained with an explicit failure reason instead of deleted.

## 6. Final campaign order

Do not jump directly into thirty TLE application runs. Execute in this order:

1. one terrestrial engineering run;
2. one GEO engineering run;
3. one OAI-native LEO engineering run;
4. one TLE-state-fidelity engineering run;
5. inspect all logs/metrics;
6. freeze configs and trace-generation settings;
7. perform five publishable terrestrial/GEO/static-LEO/native-LEO repetitions;
8. perform five repetitions for each selected Starlink and OneWeb TLE pass;
9. perform paired CUBIC/BBR transport runs using the same representative traces;
10. run the analysis/supportability pipeline only after the campaign is complete.

## 7. Data-handling rule

The public repository is code/documentation only. Final TLE snapshots, raw experiment data, logs, testbed-specific configuration and any non-redistributable surgical media remain outside Git or in the private project as appropriate.
