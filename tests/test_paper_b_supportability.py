import json, subprocess, sys
from pathlib import Path

def test_connected_but_unusable(tmp_path: Path):
    w=tmp_path/'w'; (w/'core').mkdir(parents=True); (tmp_path/'out').mkdir()
    (w/'core/video_receiver.framehash').write_text('#tb 0: 1/30\n'+''.join(f'0, 0, {i}, 1, 1, x\n' for i in range(0,17*30)))
    def dump(path, rows): path.write_text(''.join(json.dumps(x)+'\n' for x in rows))
    sent=[]; recv=[]
    for i in range(20*50):
        e={'ssrc':1,'sequence':i%65536,'rtp_timestamp':i*960}; sent.append(e); recv.append(e)
    dump(w/'audio_uplink_sender_packets.jsonl',sent); dump(w/'core/audio_uplink_receiver_packets.jsonl',recv)
    dump(w/'core/audio_downlink_sender_packets.jsonl',sent); dump(w/'audio_downlink_receiver_packets.jsonl',recv)
    controls=[]
    for i in range(20*10): controls.append({'send_elapsed_s':i/10,'acknowledged':True,'rtt_ms':30})
    dump(w/'telestration_events.jsonl',controls)
    th=tmp_path/'t.yaml'; th.write_text('''primary_application_gates:\n  video_frame_delivery_ratio: {direction: lower, threshold: 0.99}\n  audio_uplink_packet_delivery_ratio: {direction: lower, threshold: 0.97}\n  audio_downlink_packet_delivery_ratio: {direction: lower, threshold: 0.97}\n  telestration_ack_delivery_ratio: {direction: lower, threshold: 1.0}\n  telestration_request_ack_rtt_ms: {direction: upper, threshold: 450}\n''')
    script=Path(__file__).parents[1]/'scripts/paper_b_supportability.py'
    subprocess.run([sys.executable,str(script),'--workload-dir',str(w),'--thresholds',str(th),'--duration','20','--warmup','10','--application-offset-s','100','--boundary-relative-s','125','--output-dir',str(tmp_path/'out')],check=True)
    s=json.loads((tmp_path/'out/usability_summary.json').read_text())
    assert s['RRC_alive_through_workload_end'] is True
    assert s['connected_but_unusable_confirmatory'] is True
    assert s['T_data_plane_end_media_s'] > s['T_AUSW_end_media_s']
