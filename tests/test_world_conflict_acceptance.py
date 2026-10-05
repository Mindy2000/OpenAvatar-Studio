import json
import time
from test_app import make_client, create_avatar


def test_accept_conflict_candidate_waits_for_review(tmp_path):
    with make_client(tmp_path) as client:
        a=create_avatar(client,subject_kind='fictional'); aid=a['id'];base=f'/api/avatars/{aid}';db=client.app.state.db
        cid=db.execute('INSERT INTO world_conflicts(avatar_id,fact_key,existing_value_json,candidate_value_json,reason,created_at) VALUES(?,?,?,?,?,?)',
                       (aid,'tutorial.library_hours','null',json.dumps('21:00'),'test candidate',int(time.time())))
        response=client.post(base+f'/world/conflicts/{cid}/review',json={'action':'accept_candidate'})
        assert response.status_code==200
        proposals=client.get(base+'/world/proposals').json()
        p=next(x for x in proposals if x['fact_key']=='tutorial.library_hours')
        assert p['status']=='pending'
        assert not any(x['fact_key']=='tutorial.library_hours' for x in client.get(base+'/world').json()['facts'])
        assert client.post(base+f"/world/proposals/{p['id']}/review",json={'action':'approve'}).status_code==200
        assert any(x['fact_key']=='tutorial.library_hours' and x['value']=='21:00' for x in client.get(base+'/world').json()['facts'])
