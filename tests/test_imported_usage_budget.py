import json,time
from test_app import make_client, create_avatar
from openavatar.services.provider_hub import _spent


def test_importing_usage_history_does_not_charge_current_budget_twice(tmp_path):
    with make_client(tmp_path) as c:
        a=create_avatar(c); db=c.app.state.db
        db.execute('INSERT INTO usage_events(avatar_id,provider,model,operation,estimated_cost,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)',
                   (a['id'],'pc_budget_sample','test','chat',0.25,'{}',int(time.time())))
        package=c.post('/api/avatars/'+a['id']+'/export')
        b=c.post('/api/packages/import',content=package.content,headers={'Content-Type':'application/zip','X-File-Name':'usage.zip','X-Rights-Confirmed':'true'})
        assert b.status_code==201,b.text
        assert _spent(db,'pc_budget_sample',0)==0.25
        copied=db.one('SELECT metadata_json FROM usage_events WHERE avatar_id=?',(b.json()['id'],))
        assert json.loads(copied['metadata_json'])['imported_history']
        summary=c.get('/api/provider-hub').json()['usage']
        assert next(x for x in summary if x['provider']=='pc_budget_sample')['calls']==1
