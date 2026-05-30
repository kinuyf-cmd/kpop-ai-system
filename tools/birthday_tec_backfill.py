import sys; sys.path.insert(0,'lib')
import popup_event_to_post as m

# 既にwp_tec_events登録済みを除く、未登録の誕生日イベント全件
rows = m.run_mysql("""
SELECT p.ID, ps.meta_value, pe.meta_value, psu.meta_value, peu.meta_value
FROM wp_posts p
JOIN wp_postmeta pk  ON pk.post_id=p.ID  AND pk.meta_key='kpj_event_kind' AND pk.meta_value='birthday'
JOIN wp_postmeta ps  ON ps.post_id=p.ID  AND ps.meta_key='_EventStartDate'
JOIN wp_postmeta pe  ON pe.post_id=p.ID  AND pe.meta_key='_EventEndDate'
JOIN wp_postmeta psu ON psu.post_id=p.ID AND psu.meta_key='_EventStartDateUTC'
JOIN wp_postmeta peu ON peu.post_id=p.ID AND peu.meta_key='_EventEndDateUTC'
LEFT JOIN wp_tec_events te ON te.post_id=p.ID
WHERE p.post_status='publish' AND te.post_id IS NULL;
""")
lines=[l for l in rows.split('\n') if l.strip() and not l.startswith('ID')]
print(f"未登録の誕生日イベント: {len(lines)}件")
ok=0; fail=0
for ln in lines:
    parts=ln.split('\t')
    if len(parts)<5: continue
    pid,sj,ej,su,eu=[x.strip() for x in parts[:5]]
    try:
        m.run_mysql(f"INSERT INTO wp_tec_events (post_id,start_date,end_date,timezone,start_date_utc,end_date_utc,duration,hash) VALUES ({pid},'{sj}','{ej}','Asia/Tokyo','{su}','{eu}',86399,MD5(CONCAT({pid},'{sj}'))) ON DUPLICATE KEY UPDATE start_date=VALUES(start_date);")
        eids=[x.strip() for x in m.run_mysql(f"SELECT event_id FROM wp_tec_events WHERE post_id={pid};").splitlines() if x.strip().isdigit()]
        if eids:
            eid=eids[0]
            m.run_mysql(f"INSERT IGNORE INTO wp_tec_occurrences (event_id,post_id,start_date,start_date_utc,end_date,end_date_utc,duration,hash) VALUES ({eid},{pid},'{sj}','{su}','{ej}','{eu}',86399,MD5(CONCAT({eid},{pid},'{sj}')));")
            ok+=1
        else: fail+=1
    except SystemExit as e:
        fail+=1
    if (ok+fail)%200==0: print(f"  進捗 {ok+fail}/{len(lines)} (ok={ok})")
print(f"=== 完了: ok={ok} fail={fail} ===")
