#!/usr/bin/env python3
"""Compute application-usable, data-plane and RRC windows for Paper B.

No cross-host one-way clock synchronization is required: media delivery is aligned
with RTP/media sequence time, and control latency uses request/ack RTT.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any
import yaml


def jsonl(path: Path) -> list[dict[str,Any]]:
    if not path.exists(): return []
    with path.open(encoding='utf-8') as f:
        return [json.loads(x) for x in f if x.strip()]


def frame_times(path: Path) -> list[float]:
    if not path.exists(): return []
    tb=None; times=[]
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        if line.startswith('#tb 0:'):
            n,d=line.split(':',1)[1].strip().split('/'); tb=float(n)/float(d)
        elif line and not line.startswith('#') and tb is not None:
            parts=[p.strip() for p in line.split(',')]
            if len(parts)>=3:
                try: times.append(int(parts[2])*tb)
                except ValueError: pass
    return times


def rtp_windows(sent_path: Path, recv_path: Path, warmup: int, end: int):
    sent=jsonl(sent_path); recv=jsonl(recv_path)
    if not sent: return {}, None
    received={(e.get('ssrc'),e.get('sequence'),e.get('rtp_timestamp')) for e in recv}
    first=int(sent[0]['rtp_timestamp']); result={}; key_elapsed={}
    for e in sent:
        elapsed=((int(e['rtp_timestamp'])-first)&0xffffffff)/48000.0
        key=(e.get('ssrc'),e.get('sequence'),e.get('rtp_timestamp')); key_elapsed[key]=elapsed
        w=math.floor(elapsed)
        if warmup<=w<end:
            row=result.setdefault(w,[0,0]); row[0]+=1; row[1]+= int(key in received)
    delivered=[key_elapsed[k] for k in received if k in key_elapsed]
    return result, (max(delivered) if delivered else None)


def margin(value: float, direction: str, threshold: float) -> float:
    return (value-threshold)/threshold if direction=='lower' else (threshold-value)/threshold


def percentile(values: list[float], q: float) -> float | None:
    if not values: return None
    x=sorted(values); pos=(len(x)-1)*q; lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi: return x[lo]
    return x[lo]*(hi-pos)+x[hi]*(pos-lo)


def contiguous_prefix(rows: list[dict[str,Any]], key: str) -> int:
    n=0
    for r in rows:
        if r[key]: n+=1
        else: break
    return n


def longest_run(rows: list[dict[str,Any]], key: str) -> int:
    best=cur=0
    for r in rows:
        cur=cur+1 if r[key] else 0; best=max(best,cur)
    return best


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--workload-dir',required=True); p.add_argument('--thresholds',required=True)
    p.add_argument('--duration',type=float,required=True); p.add_argument('--warmup',type=int,required=True)
    p.add_argument('--application-offset-s',type=float,required=True)
    p.add_argument('--boundary-relative-s',type=float,required=True,help='T310 boundary seconds from radio anchor')
    p.add_argument('--expected-video-fps',type=float,default=30.0); p.add_argument('--output-dir',required=True)
    p.add_argument('--confirmatory-min-gap-s',type=float,default=.5)
    a=p.parse_args(); root=Path(a.workload_dir); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    cfg=yaml.safe_load(Path(a.thresholds).read_text()); gates=cfg['primary_application_gates']; end=math.floor(a.duration)
    if end<=a.warmup: raise SystemExit('duration must exceed warmup')

    video=frame_times(root/'core/video_receiver.framehash')
    video_windows={w:0 for w in range(a.warmup,end)}
    for t in video:
        w=math.floor(t)
        if a.warmup<=w<end: video_windows[w]+=1
    ul, ul_last=rtp_windows(root/'audio_uplink_sender_packets.jsonl',root/'core/audio_uplink_receiver_packets.jsonl',a.warmup,end)
    dl, dl_last=rtp_windows(root/'core/audio_downlink_sender_packets.jsonl',root/'audio_downlink_receiver_packets.jsonl',a.warmup,end)
    control=jsonl(root/'telestration_events.jsonl'); control_windows={}; control_last=None
    for e in control:
        s=float(e.get('send_elapsed_s',0.0)); w=math.floor(s)
        if a.warmup<=w<end: control_windows.setdefault(w,[]).append(e)
        if e.get('acknowledged'):
            at=s+(float(e.get('rtt_ms') or 0.0)/1000.0); control_last=max(control_last or at,at)
    video_last=max(video) if video else None
    data_last=max([x for x in (video_last,ul_last,dl_last,control_last) if x is not None],default=None)
    rrc_end=a.boundary_relative_s-a.application_offset_s

    rows=[]
    for w in range(a.warmup,end):
        cv=control_windows.get(w,[]); su,ru=ul.get(w,(0,0)); sd,rd=dl.get(w,(0,0))
        acked=[e for e in cv if e.get('acknowledged')]
        values={
          'video_frame_delivery_ratio':min(1.0,video_windows[w]/a.expected_video_fps),
          'audio_uplink_packet_delivery_ratio':ru/su if su else 0.0,
          'audio_downlink_packet_delivery_ratio':rd/sd if sd else 0.0,
          'telestration_ack_delivery_ratio':len(acked)/len(cv) if cv else 0.0,
          'telestration_request_ack_rtt_ms':max((float(e['rtt_ms']) for e in acked if e.get('rtt_ms') is not None),default=float('inf')),
        }
        margins={name:margin(values[name],g['direction'],float(g['threshold'])) for name,g in gates.items()}
        app_supported=all(m>=0 and math.isfinite(m) for m in margins.values())
        rrc_connected=(w+1)<=rrc_end+1e-9
        data_alive=(video_windows[w]>0 or ru>0 or rd>0 or len(acked)>0)
        rows.append({'window_index':w-a.warmup,'media_start_s':w,'media_end_s':w+1,
                     'metrics':values,'margins':margins,'M_t':min(margins.values()),
                     'application_supported':app_supported,'rrc_connected':rrc_connected,
                     'data_plane_alive':data_alive,'ausw_supported':app_supported and rrc_connected})
    with (out/'usability_windows.jsonl').open('w',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r,sort_keys=True)+'\n')

    prefix=contiguous_prefix(rows,'ausw_supported'); total=sum(r['ausw_supported'] for r in rows); lsi=longest_run(rows,'ausw_supported')
    ausw_end=a.warmup+prefix; data_end=min(a.duration,data_last) if data_last is not None else 0.0
    gap_data=data_end-ausw_end; gap_rrc=rrc_end-ausw_end
    tol=float(a.confirmatory_min_gap_s)
    connected_but_unusable=(ausw_end < min(a.duration,rrc_end)-tol and data_end>ausw_end+tol and rrc_end>ausw_end+tol)
    summary={
      'complete_windows':len(rows),'warmup_s':a.warmup,'duration_s':a.duration,
      'AUSW_total_seconds':total,'AUSW_ratio':total/len(rows),'AUSW_prefix_length_seconds':prefix,
      'T_AUSW_end_media_s':ausw_end,'AUSW_LSI_seconds':lsi,
      'RM_p05':percentile([r['M_t'] for r in rows],.05),'RM_min':min(r['M_t'] for r in rows),
      'T_data_plane_end_media_s':data_end,'T_RRC_end_media_s':rrc_end,
      'gap_data_plane_minus_AUSW_s':gap_data,'gap_RRC_minus_AUSW_s':gap_rrc,
      'RRC_alive_through_workload_end':rrc_end>=a.duration,
      'data_plane_alive_after_AUSW':data_end>ausw_end+tol,
      'connected_but_unusable_confirmatory':connected_but_unusable,
      'primary_gate_thresholds':{k:{'direction':v['direction'],'threshold':v['threshold']} for k,v in gates.items()},
      'one_way_clock_sync_required':False,'run_is_statistical_unit':True,
    }
    (out/'usability_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')

if __name__=='__main__': main()
