#!/usr/bin/env python3
"""Unattended UCT Paper-B AUSW campaign supervisor.

This supervisor deliberately separates application usability from service failure.
Final-condition timing is frozen solely from radio-only Timer-T310 calibration.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, signal, statistics, subprocess, sys, threading, time, zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

ROOT=Path(__file__).resolve().parents[1]

def utc(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def sha(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def atomic_json(p:Path,v:Any):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_name(p.name+f'.tmp.{os.getpid()}'); t.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n'); os.replace(t,p)
def run(cmd,check=True,timeout=None,**kw):
    cp=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout,**kw)
    if check and cp.returncode: raise RuntimeError(f"command failed {cp.returncode}: {' '.join(map(str,cmd))}\n{cp.stdout}\n{cp.stderr}")
    return cp

class LoggedProcess:
    def __init__(self,cmd:list[str],log:Path,anchor:float):
        self.cmd=cmd; self.log=log; self.anchor=anchor
        log.parent.mkdir(parents=True,exist_ok=True)
        self.proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
        self.thread=threading.Thread(target=self._pump,daemon=True); self.thread.start()
    def _pump(self):
        assert self.proc.stdout is not None
        with self.log.open('a',encoding='utf-8',buffering=1) as f:
            for line in self.proc.stdout:
                elapsed=time.monotonic()-self.anchor
                f.write(f"{utc()} elapsed={elapsed:.3f} {line.rstrip()}\n")
    def stop(self):
        if self.proc.poll() is None:
            try: os.killpg(self.proc.pid,signal.SIGINT)
            except ProcessLookupError: pass
            try: self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try: os.killpg(self.proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try: os.killpg(self.proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
        self.thread.join(timeout=2)

class Supervisor:
    def __init__(self,config:Path):
        self.config_path=config; self.cfg=yaml.safe_load(config.read_text()); self.lab=self.cfg['lab']; self.campaign=self.cfg['campaign']; self.work=self.cfg['workload']
        self.results=ROOT/self.cfg['outputs']['results_root']; self.results.mkdir(parents=True,exist_ok=True)
        self.state_path=self.results/'campaign_state.json'; self.procs:list[LoggedProcess]=[]
        self.state={'campaign_id':self.cfg['campaign_id'],'status':'idle','phase':'init','active_run':None,'last_heartbeat_utc':utc(),'runs':[],'blocker':None}
        if self.state_path.exists():
            try: self.state.update(json.loads(self.state_path.read_text()))
            except Exception: pass
        self.oai=Path(self.lab['oai_root']); self.build=self.oai/'cmake_targets/ran_build/build'
    def write_state(self): self.state['last_heartbeat_utc']=utc(); atomic_json(self.state_path,self.state)
    def phase(self,x): self.state['phase']=x; self.write_state()
    def fail(self,msg): self.state['status']='blocked'; self.state['blocker']=msg; self.write_state(); raise RuntimeError(msg)
    def cleanup(self):
        for p in reversed(self.procs): p.stop()
        self.procs.clear()
        run(['sudo','-n','pkill','-INT','-x','nr-uesoftmodem'],check=False); run(['sudo','-n','pkill','-INT','-x','nr-softmodem'],check=False)
    def preflight(self):
        self.phase('preflight')
        req=[self.build/'nr-softmodem',self.build/'nr-uesoftmodem',Path(self.lab['gnb_config']),Path(self.lab['ue_config']),ROOT/self.work['script'],ROOT/'scripts/paper_b_supportability.py',ROOT/'scripts/plan_paper_b_usability_campaign.py',ROOT/Path(self.cfg['thresholds_file'])]
        missing=[str(x) for x in req if not x.exists()]
        if missing: self.fail(f'missing required paths: {missing}')
        if run(['sudo','-n','true'],check=False).returncode: self.fail('passwordless sudo is required for unattended radio launch')
        if run(['pgrep','-x','nr-softmodem'],check=False).returncode==0 or run(['pgrep','-x','nr-uesoftmodem'],check=False).returncode==0: self.fail('OAI processes already running; refuse to collide')
        report={'valid':True,'checked_utc':utc(),'oai_head':run(['git','-C',str(self.oai),'rev-parse','HEAD']).stdout.strip(),'framework_head':run(['git','-C',str(ROOT),'rev-parse','HEAD'],check=False).stdout.strip(),'required_paths':[str(x) for x in req]}
        atomic_json(self.results/'preflight.json',report); return report
    def launch_radio(self,out:Path):
        anchor=time.monotonic(); gnb=[str(self.build/'nr-softmodem'),'-O',self.lab['gnb_config'],'--rfsim','--rfsimulator.[0].options','chanmod,realtime_pacing']
        ue=[str(self.build/'nr-uesoftmodem'),'-O',self.lab['ue_config'],'--band','254','-C','2488400000','--CO','-873500000','-r','25','--numerology','0','--ssb','60','--rfsim','--rfsimulator.[0].prop_delay','20','--rfsimulator.[0].options','chanmod','--time-sync-I','0.1','--ntn-initial-time-drift','-46','--initial-fo','57340','--cont-fo-comp','2']
        gp=LoggedProcess(['sudo','-n',*gnb],out/'gnb.log',anchor); self.procs.append(gp); time.sleep(float(self.lab.get('gnb_start_lead_s',1)))
        up=LoggedProcess(['sudo','-n',*ue],out/'ue.log',anchor); self.procs.append(up); return anchor
    def wait_anchor(self,log:Path):
        deadline=time.monotonic()+90; pat=re.compile(r'elapsed=([0-9.]+).*Satellite orbit:')
        while time.monotonic()<deadline:
            if log.exists():
                for line in log.read_text(errors='replace').splitlines():
                    m=pat.search(line)
                    if m: return float(m.group(1)),line
            if any(p.proc.poll() is not None for p in self.procs): self.fail('OAI exited before radio anchor')
            time.sleep(.5); self.write_state()
        self.fail('radio anchor not observed')
    def wait_attach(self):
        deadline=time.monotonic()+float(self.lab['attach_timeout_s'])
        while time.monotonic()<deadline:
            cp=run(['ip','-4','-o','addr','show','dev',self.lab['ue_tunnel']],check=False)
            m=re.search(r'inet\s+([0-9.]+)/',cp.stdout)
            if m:
                ip=m.group(1)
                ping=run(['ping','-I',self.lab['ue_tunnel'],'-c','2','-W','3',self.lab['remote_application_ip']],check=False,timeout=10)
                if ping.returncode==0: return ip
            if any(p.proc.poll() is not None for p in self.procs): self.fail('OAI exited before attach/data path')
            time.sleep(1); self.write_state()
        self.fail('attach/data path timeout')
    def find_boundary(self,log:Path,anchor_elapsed:float,timeout_s:float):
        deadline=time.monotonic()+timeout_s; sig=re.compile(self.campaign['boundary_signature_regex']); ep=re.compile(r'elapsed=([0-9.]+)')
        while time.monotonic()<deadline:
            if log.exists():
                lines=log.read_text(errors='replace').splitlines()
                for line in lines:
                    if sig.search(line):
                        m=ep.search(line)
                        if not m: continue
                        raw=float(m.group(1)); rel=raw-anchor_elapsed
                        return {'detected':True,'boundary_elapsed_s':round(rel,3),'raw_process_elapsed_s':raw,'raw_line':line,'rule':self.campaign['boundary_signature_regex'],'detected_utc':utc()}
            exited=[p.proc.returncode for p in self.procs if p.proc.poll() is not None]
            if exited: self.fail(f'OAI exited before independent T310 evidence: {exited}')
            time.sleep(.5); self.write_state()
        self.fail('T310 boundary not found before timeout')
    def calibrate(self):
        self.phase('radio_only_calibration'); caldir=self.results/'calibration'; caldir.mkdir(exist_ok=True)
        records=[]
        for i in range(1,int(self.campaign['calibration_repetitions'])+1):
            out=caldir/f'CAL_{i:02d}'
            if (out/'radio_boundary.json').exists(): records.append(json.loads((out/'radio_boundary.json').read_text())); continue
            if out.exists() and any(out.iterdir()): self.fail(f'refusing to overwrite partial calibration {out}')
            out.mkdir(parents=True,exist_ok=True); self.state['active_run']=out.name; self.write_state()
            try:
                start=self.launch_radio(out); ae,aline=self.wait_anchor(out/'ue.log'); self.wait_attach()
                b=self.find_boundary(out/'ue.log',ae,float(self.lab['boundary_timeout_s'])); b['radio_anchor_raw_line']=aline; atomic_json(out/'radio_boundary.json',b); records.append(b)
            finally: self.cleanup()
            time.sleep(float(self.campaign['inter_run_cooldown_s']))
        vals=[float(x['boundary_elapsed_s']) for x in records]; earliest=min(vals); latest=max(vals); spread=latest-earliest
        if spread>float(self.campaign['boundary_spread_limit_s']): self.fail(f'calibrated boundary spread {spread:.3f}s exceeds frozen limit')
        summary={'runs':records,'earliest_s':round(earliest,3),'latest_s':round(latest,3),'median_s':round(statistics.median(vals),3),'spread_s':round(spread,3),'source':'radio-only Timer-T310 calibration; no application outcomes used'}
        atomic_json(caldir/'summary.json',summary)
        run([sys.executable,str(ROOT/'scripts/plan_paper_b_usability_campaign.py'),'--config',str(self.config_path),'--calibration',str(caldir/'summary.json'),'--output-json',str(self.results/'campaign_plan.json'),'--output-csv',str(self.results/'campaign_plan.csv')])
        freeze=[self.config_path,ROOT/Path(self.cfg['thresholds_file']),ROOT/self.work['script'],ROOT/'scripts/paper_b_supportability.py',self.results/'campaign_plan.json']
        (self.results/'FREEZE_SHA256.txt').write_text(''.join(f"{sha(x)}  {x}\n" for x in freeze))
        return summary
    def wait_until(self,target:float):
        while time.monotonic()<target:
            if any(p.proc.poll() is not None for p in self.procs): self.fail('OAI exited before scheduled action')
            time.sleep(min(.5,max(.05,target-time.monotonic()))); self.write_state()
    def run_spec(self,spec:dict[str,Any],engineering=False):
        run_id=('ENG_'+spec['run_id']) if engineering else spec['run_id']; base=self.results/('engineering' if engineering else 'final')/run_id
        if base.exists(): self.fail(f'refusing to overwrite {base}')
        (base/'application').mkdir(parents=True); (base/'analysis').mkdir(); self.state['active_run']=run_id; self.write_state()
        app_offset=float(spec['application_launch_offset_s']); duration=float(spec['duration_s']); gate=base/'measurement_start.signal'
        try:
            start=self.launch_radio(base); anchor_elapsed,anchor_line=self.wait_anchor(base/'ue.log'); ue_ip=self.wait_attach()
            target=start+anchor_elapsed+app_offset; prep=target-float(self.work['preparation_lead_s']); self.wait_until(prep)
            env=os.environ.copy(); env['WORKLOAD_START_GATE']=str(gate); env['WORKLOAD_WARMUP_S']=str(self.work['warmup_s'])
            console=(base/'application/bundled_workload_console.log').open('w',encoding='utf-8')
            wp=subprocess.Popen([str(ROOT/self.work['script']),str(duration),str(base/'application')],stdout=console,stderr=subprocess.STDOUT,text=True,start_new_session=True,env=env)
            ready=base/'application/instrumentation_ready.json'; ready_deadline=time.monotonic()+max(5,float(self.work['preparation_lead_s'])-1)
            while time.monotonic()<ready_deadline and not ready.exists():
                if wp.poll() is not None: self.fail(f'workload preparation exited {wp.returncode}')
                time.sleep(.2); self.write_state()
            if not ready.exists(): self.fail('workload instrumentation did not become ready before launch gate')
            self.wait_until(target); gate.touch(); app_start_utc=utc()
            deadline=time.monotonic()+duration+90
            while wp.poll() is None and time.monotonic()<deadline: time.sleep(1); self.write_state()
            if wp.poll() is None:
                try: os.killpg(wp.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                self.fail('bundled workload timeout')
            workload_rc=wp.returncode; console.close(); app_end_utc=utc()
            elapsed_after_anchor=time.monotonic()-(start+anchor_elapsed); remaining=max(30,float(self.lab['boundary_timeout_s'])-elapsed_after_anchor)
            boundary=self.find_boundary(base/'ue.log',anchor_elapsed,remaining); atomic_json(base/'radio_boundary.json',boundary)
            actual=float(boundary['boundary_elapsed_s']); app_end_elapsed=app_offset+duration
            run([sys.executable,str(ROOT/'scripts/paper_b_supportability.py'),'--workload-dir',str(base/'application'),'--thresholds',str(ROOT/Path(self.cfg['thresholds_file'])),'--duration',str(duration),'--warmup',str(self.work['warmup_s']),'--application-offset-s',str(app_offset),'--boundary-relative-s',str(actual),'--expected-video-fps',str(self.work['expected_video_fps']),'--confirmatory-min-gap-s',str(self.campaign['confirmatory_min_gap_s']),'--output-dir',str(base/'analysis')])
            ana=json.loads((base/'analysis/usability_summary.json').read_text())
            cond=spec['condition']; margin=actual-app_end_elapsed
            if cond=='nominal': timing_ok=margin>=float(self.campaign['nominal_end_margin_s'])
            elif cond=='degraded_connected': timing_ok=(margin>=float(self.campaign['degraded_connected_end_margin_s'])-0.5 and margin<=float(self.campaign['degraded_connected_max_end_margin_s']))
            else: timing_ok=(actual>app_offset and actual<app_end_elapsed and app_end_elapsed-actual>=float(self.campaign['near_failure_overrun_s'])-2.0)
            required=[base/'application/run_status.json',base/'analysis/usability_summary.json',base/'radio_boundary.json',base/'gnb.log',base/'ue.log']
            artifacts_ok=all(x.exists() for x in required)
            workload_ok=(workload_rc==0 or cond=='near_failure') and artifacts_ok
            valid=timing_ok and workload_ok
            status='valid_success' if valid else ('design_boundary_failure' if not timing_ok else 'instrumentation_failure')
            if valid and cond=='near_failure': status='condition_induced_failure'
            manifest={'run_id':run_id,'planned_run_id':spec['run_id'],'engineering':engineering,'condition':cond,'repetition':spec['repetition'],'paired_seed':spec['paired_seed'],'application_launch_offset_s':app_offset,'workload_duration_s':duration,'actual_T310_boundary_s':actual,'application_end_elapsed_s':app_end_elapsed,'margin_T310_minus_app_end_s':margin,'run_status':status,'workload_exit_code':workload_rc,'application_start_utc':app_start_utc,'application_end_utc':app_end_utc,'radio_anchor_raw_line':anchor_line,'analysis':ana,'framework_commit':run(['git','-C',str(ROOT),'rev-parse','HEAD'],check=False).stdout.strip(),'oai_commit':run(['git','-C',str(self.oai),'rev-parse','HEAD'],check=False).stdout.strip()}
            atomic_json(base/'run_manifest.json',manifest); atomic_json(base/'qc.json',{'valid':valid,'timing_ok':timing_ok,'workload_artifacts_ok':workload_ok,'status':status,'required_files':[str(x.relative_to(base)) for x in required]})
            if not engineering:
                self.state['runs']=[x for x in self.state.get('runs',[]) if x.get('run_id')!=run_id]+[{'run_id':run_id,'condition':cond,'repetition':spec['repetition'],'status':status,'AUSW_prefix_s':ana['AUSW_prefix_length_seconds'],'gap_data_s':ana['gap_data_plane_minus_AUSW_s'],'gap_rrc_s':ana['gap_RRC_minus_AUSW_s'],'confirmatory':ana['connected_but_unusable_confirmatory']}]; self.write_state()
            if not valid: self.fail(f'{run_id} invalid: timing_ok={timing_ok} workload_ok={workload_ok}; preserved for diagnosis')
            return manifest
        finally: self.cleanup(); time.sleep(float(self.campaign['inter_run_cooldown_s']))
    def dry_run(self):
        self.phase('engineering_dry_runs'); plan=json.loads((self.results/'campaign_plan.json').read_text())
        for cond in ('nominal','degraded_connected','near_failure'):
            spec=next(x for x in plan['runs'] if x['condition']==cond); name='ENG_'+spec['run_id']
            if (self.results/'engineering'/name/'qc.json').exists(): continue
            self.run_spec(dict(spec),engineering=True)
    def final_campaign(self):
        self.phase('final_campaign'); plan=json.loads((self.results/'campaign_plan.json').read_text())
        for spec in plan['runs']:
            qc=self.results/'final'/spec['run_id']/'qc.json'
            if qc.exists() and json.loads(qc.read_text()).get('valid'): continue
            if (self.results/'final'/spec['run_id']).exists(): self.fail(f'partial/invalid final run already exists for {spec["run_id"]}; classify explicitly before replacement')
            self.run_spec(dict(spec),engineering=False)
        self.summarize()
    def summarize(self):
        self.phase('summary'); rows=[]
        for p in sorted((self.results/'final').glob('*/run_manifest.json')):
            m=json.loads(p.read_text()); a=m['analysis']; rows.append({'run_id':m['run_id'],'condition':m['condition'],'repetition':m['repetition'],'status':m['run_status'],'AUSW_prefix_s':a['AUSW_prefix_length_seconds'],'AUSW_total_s':a['AUSW_total_seconds'],'AUSW_ratio':a['AUSW_ratio'],'T_data_end_s':a['T_data_plane_end_media_s'],'T_RRC_end_s':a['T_RRC_end_media_s'],'gap_data_s':a['gap_data_plane_minus_AUSW_s'],'gap_rrc_s':a['gap_RRC_minus_AUSW_s'],'rrc_alive_entire':a['RRC_alive_through_workload_end'],'confirmatory':a['connected_but_unusable_confirmatory']})
        import csv
        out=self.results/'analysis'; out.mkdir(exist_ok=True)
        with (out/'run_level_summary.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        by={}
        for cond in ('nominal','degraded_connected','near_failure'):
            rr=[x for x in rows if x['condition']==cond]
            def stats(k):
                v=[float(x[k]) for x in rr]; n=len(v); mean=statistics.mean(v); sd=statistics.stdev(v) if n>1 else 0; half=(2.776*sd/math.sqrt(n)) if n==5 else (1.96*sd/math.sqrt(n) if n>1 else 0); return {'n':n,'mean':mean,'sd':sd,'ci95':[mean-half,mean+half]}
            by[cond]={'AUSW_prefix_s':stats('AUSW_prefix_s'),'AUSW_ratio':stats('AUSW_ratio'),'gap_data_s':stats('gap_data_s'),'gap_rrc_s':stats('gap_rrc_s'),'confirmatory_count':sum(bool(x['confirmatory']) for x in rr)}
        deg=by['degraded_connected']; threshold=int(self.campaign['confirmatory_min_supporting_repetitions']); campaign_support=deg['confirmatory_count']>=threshold
        summary={'campaign_id':self.cfg['campaign_id'],'run_count':len(rows),'conditions':by,'predeclared_confirmatory_rule':f'at least {threshold}/5 degraded-connected repetitions show AUSW ending while RRC and data plane remain available','confirmatory_hypothesis_supported':campaign_support,'generated_utc':utc(),'interpretation_deferred_to_paper_analysis':True}
        atomic_json(out/'campaign_summary.json',summary); return summary
    def package(self):
        self.phase('package'); pkg=self.results/'package'; pkg.mkdir(exist_ok=True); stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); z=pkg/f'UCT_PAPER_B_AUSW_RESULTS_{stamp}.zip'
        with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zz:
            for f in sorted(self.results.rglob('*')):
                if f.is_file() and f!=z and not f.name.endswith('.tmp'): zz.write(f,f.relative_to(self.results))
        checksum=Path(str(z)+'.sha256'); checksum.write_text(f'{sha(z)}  {z.name}\n')
        atomic_json(pkg/'latest_package.json',{'zip':str(z),'sha256_file':str(checksum),'zip_sha256':sha(z),'created_utc':utc()})
        return z
    def upload(self, z:Path|None=None):
        self.phase('upload_google_drive')
        delivery=self.cfg.get('delivery') or {}
        dest=str(delivery.get('rclone_destination') or '').strip()
        required=bool(delivery.get('require_upload', True))
        if not dest:
            if required: self.fail('delivery.rclone_destination is not configured; Codex must populate it from the existing RAN-host rclone Google Drive remote before final campaign launch')
            return {'uploaded':False,'reason':'destination_not_configured'}
        if run(['rclone','version'],check=False).returncode != 0:
            if required: self.fail('rclone is required for final Google Drive delivery but is unavailable')
            return {'uploaded':False,'reason':'rclone_unavailable'}
        if z is None:
            meta=self.results/'package/latest_package.json'
            if not meta.exists(): z=self.package()
            else: z=Path(json.loads(meta.read_text())['zip'])
        checksum=Path(str(z)+'.sha256')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        remote_dir=f"{dest.rstrip('/')}/{self.cfg['campaign_id']}_{stamp}"
        cp=run(['rclone','mkdir',remote_dir],check=False)
        if cp.returncode: self.fail(f'rclone mkdir failed for {remote_dir}: {cp.stderr.strip()}')
        for f in (z,checksum):
            cp=run(['rclone','copyto',str(f),f"{remote_dir}/{f.name}",'--checksum','--progress'],check=False)
            if cp.returncode: self.fail(f'rclone upload failed for {f.name}: {cp.stderr.strip()}')
        listing=run(['rclone','lsjson',remote_dir],check=False)
        if listing.returncode: self.fail(f'rclone post-upload verification failed: {listing.stderr.strip()}')
        report={'uploaded':True,'destination':remote_dir,'files':[z.name,checksum.name],'verified_listing':json.loads(listing.stdout or '[]'),'uploaded_utc':utc()}
        atomic_json(self.results/'package/upload_report.json',report)
        return report
    def all(self):
        self.state['status']='running'; self.write_state()
        try:
            self.preflight()
            if not (self.results/'calibration/summary.json').exists(): self.calibrate()
            if not (self.results/'campaign_plan.json').exists(): self.calibrate()
            self.dry_run(); self.final_campaign(); z=self.package(); self.upload(z); self.state['status']='complete'; self.state['phase']='complete'; self.state['active_run']=None; self.write_state()
        except Exception as e:
            if self.state.get('status')!='blocked': self.state['status']='blocked'; self.state['blocker']=str(e); self.write_state()
            raise

def main():
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('action',choices=['preflight','calibrate','dry-run','campaign','summary','package','upload','all'])
    a=p.parse_args(); s=Supervisor(Path(a.config))
    try:
        {'preflight':s.preflight,'calibrate':s.calibrate,'dry-run':s.dry_run,'campaign':s.final_campaign,'summary':s.summarize,'package':s.package,'upload':s.upload,'all':s.all}[a.action]()
    finally:
        try:s.cleanup()
        except Exception:pass

if __name__=='__main__': main()
