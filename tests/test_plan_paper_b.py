import json, subprocess, sys
from pathlib import Path

def test_plan_is_radio_only_and_15_runs(tmp_path: Path):
    cfg=tmp_path/'c.yaml'; cfg.write_text('''campaign_id: X\nworkload: {duration_s: 180}\ncampaign:\n  repetitions_per_condition: 5\n  scheduler_guard_s: 0.25\n  nominal_end_margin_s: 60\n  degraded_connected_end_margin_s: 1\n  near_failure_overrun_s: 30\n  paired_seeds: [1,2,3,4,5]\n''')
    cal=tmp_path/'cal.json'; cal.write_text(json.dumps({'earliest_s':772.76,'latest_s':772.781,'median_s':772.761}))
    script=Path(__file__).parents[1]/'scripts/plan_paper_b_usability_campaign.py'; out=tmp_path/'p.json'; csv=tmp_path/'p.csv'
    subprocess.run([sys.executable,str(script),'--config',str(cfg),'--calibration',str(cal),'--output-json',str(out),'--output-csv',str(csv)],check=True)
    p=json.loads(out.read_text()); assert p['run_count']==15
    d=next(x for x in p['runs'] if x['condition']=='degraded_connected')
    assert d['planned_margin_to_earliest_boundary_s'] > 1.0
    assert 'application outcomes' in p['scientific_design']
