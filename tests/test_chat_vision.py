import io
import json
from PIL import Image
from test_chat_media import upload
from test_runtime import make_client, create_avatar
from openavatar.services import chat_vision


def configure(c, avatar, consent=True):
    connection=c.post('/api/provider-connections',json={'display_name':'Vision test','provider_kind':'minimax','base_url':'https://api.example.com/v1','api_key':'test-only','capabilities':['vision'],'models':{'vision':'MiniMax-M3'},'consent':{'image':consent}}).json()
    c.put('/api/capability-routes',json={'scope_type':'avatar','avatar_id':avatar,'capability':'vision','primary_connection_id':connection['id']})
    return connection


def image_message(c, a, **kwargs):
    image=io.BytesIO();Image.new('RGB',(20,12),'red').save(image,format='PNG')
    return upload(c,a,image.getvalue(),'red.png','image',**kwargs).json()


def test_image_understanding_sends_pixels_caches_and_preserves_persona(tmp_path,monkeypatch):
    seen=[]
    def vision(self,messages,**kwargs):
        seen.append(messages)
        assert messages[-1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        return json.dumps({'description':'一张红色图片','reply':'这张红色图片很鲜明。'+'好'*100},ensure_ascii=False)
    monkeypatch.setattr(chat_vision.VisionClient,'chat',vision)
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c); configure(c,a); row=image_message(c,a); path=f'/api/avatars/{a}/messages/{row["id"]}/understand'
        assert c.post(path,json={}).status_code==400
        first=c.post(path,json={'confirm_billable_call':True}); assert first.status_code==200,first.text
        assert len(first.json()['reply'])==80
        assert c.post(path,json={'confirm_billable_call':True}).json()['cached']
        assert len(seen)==1
        rows=c.get(f'/api/avatars/{a}/messages').json()
        assert len(rows)==2 and rows[0]['message_kind']=='image'
        assert '红色' in rows[0]['content'] and rows[0]['attachment']['vision']['status']=='done'
        assert rows[1]['role']=='assistant'
        assert c.get(rows[0]['media_url']).content
        assert '你是数字人' in seen[0][0]['content']
        assert len(c.app.state.db.all("SELECT * FROM usage_events WHERE operation='vision' AND status='ok'"))==1


def test_image_understanding_enforces_ownership_timeline_and_authorization(tmp_path,monkeypatch):
    monkeypatch.setattr(chat_vision.VisionClient,'chat',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Must not call provider')))
    with make_client(tmp_path,monkeypatch) as c:
        a,b=create_avatar(c),create_avatar(c);row=image_message(c,a,preview_mode=True)
        payload={'confirm_billable_call':True}
        assert c.post(f'/api/avatars/{b}/messages/{row["id"]}/understand',json=payload).status_code==404
        path=f'/api/avatars/{a}/messages/{row["id"]}/understand'
        assert c.post(path,json=payload).status_code==404
        payload['preview_mode']=True
        assert c.post(path,json=payload).status_code==409
        configure(c,a,False)
        assert not c.get(f'/api/avatars/{a}/image-understanding').json()['ready']
        assert c.post(path,json=payload).status_code==409
        assert len(c.get(f'/api/avatars/{a}/messages?timeline_kind=preview').json())==1


def test_image_understanding_failure_retains_photo_no_automatic_retry(tmp_path,monkeypatch):
    calls=[]
    def invalid(*a,**k):calls.append(1);return 'not valid JSON'
    monkeypatch.setattr(chat_vision.VisionClient,'chat',invalid)
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c);configure(c,a);row=image_message(c,a)
        response=c.post(f'/api/avatars/{a}/messages/{row["id"]}/understand',json={'confirm_billable_call':True})
        assert response.status_code==502 and len(calls)==1
        messages=c.get(f'/api/avatars/{a}/messages').json()
        assert len(messages)==1 and messages[0]['attachment']['vision']['status']=='failed'
        assert c.get(row['media_url']).status_code==200
