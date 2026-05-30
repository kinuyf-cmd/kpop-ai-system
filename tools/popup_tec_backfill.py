import sys; sys.path.insert(0,'lib')
import popup_event_to_post as m
from datetime import datetime

rows = m.run_mysql("""
SELECT p.ID, ps.meta_value, pe.meta_value, psu.meta_value, peu.meta_value
FROM wp_posts p
JOIN wp_postmeta pk  ON pk.post_id=p.ID  AND pk.meta_key='kpj_event_kind' AND pk.meta_value='popup'
JOIN wp_postmeta ps  ON ps.post_id=p.ID  AND ps.meta_key='_EventStartDate'
JOIN wp_postmeta pe  ON pe.post_id=p.ID  AND pe.meta_key='_EventEndDate'
JOIN wp_postmeta psu ON psu.post_id=p.ID AND psu.meta_key='_EventStartDateUTC'
JOIN wp_postmeta peu ON peu.post_id=p.ID AND peu.meta_key='_EventEndDateUTC'
LEFT JOIN wp_tec_events te ON te.post_id=p.ID
WHERE p.post_type='tribe_events' AND p.post_status='publish' AND te.post_id IS NULL;
""")
lines=[l for l in rows.split('\n') if l.strip() and not l.startswith('ID')]
print(f"未登録のpopup tribe_events: {len(lines)}件")
ok=0; fail=0
for ln in lines:
    parts=ln.split('\t')
    if len(parts)<5: continue
    pid,sj,ej,su,eu=[x.strip() for x in parts[:5]]
    # duration = end - start (秒)。popupは複数日。
    try:
        dur=int((datetime.strptime(ej,'%Y-%m-%d %H:%M:%S')-datetime.strptime(sj,'%Y-%m-%d %H:%M:%S')).total_seconds())
        if dur<=0: dur=86399
    except: dur=86399
    try:
        m.run_mysql(f"INSERT INTO wp_tec_events (post_id,start_date,end_date,timezone,start_date_utc,end_date_utc,duration,hash) VALUES ({pid},'{sj}','{ej}','Asia/Tokyo','{su}','{eu}',{dur},MD5(CONCAT({pid},'{sj}'))) ON DUPLICATE KEY UPDATE start_date=VALUES(start_date);")
        eids=[x.strip() for x in m.run_mysql(f"SELECT event_id FROM wp_tec_events WHERE post_id={pid};").splitlines() if x.strip().isdigit()]
        if eids:
            eid=eids[0]
            m.run_mysql(f"INSERT IGNORE INTO wp_tec_occurrences (event_id,post_id,start_date,start_date_utc,end_date,end_date_utc,duration,hash) VALUES ({eid},{pid},'{sj}','{su}','{ej}','{eu}',{dur},MD5(CONCAT({eid},{pid},'{sj}')));")
            ok+=1
        else: fail+=1
    except SystemExit: fail+=1
print(f"=== 完了: ok={ok} fail={fail} ===")
