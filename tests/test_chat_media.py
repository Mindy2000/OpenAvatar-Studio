import io
import json
from PIL import Image
from test_runtime import make_client, create_avatar


def upload(client, avatar, data=b'hello', name='note.txt', kind='file', key='one', **params):
    from urllib.parse import quote
    return client.post(f'/api/avatars/{avatar}/messages/attachment', params={'kind':kind,'client_key':key,**params}, content=data, headers={'X-File-Name':quote(name)})


def test_attachment_roundtrip_retry_favorite_and_avatar_isolation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        a,b=create_avatar(c),create_avatar(c)
        first=upload(c,a).json()
        assert upload(c,a).json()['id']==first['id']
        rows=c.get(f'/api/avatars/{a}/messages').json()
        assert len(rows)==1 and rows[0]['message_kind']=='file'
        assert 'stored_name' not in rows[0]['attachment']
        assert c.get(rows[0]['media_url']).content==b'hello'
        assert 'attachment' in c.get(rows[0]['media_url']).headers['content-disposition']
        assert c.get(f'/api/avatars/{b}/messages/{first["id"]}/file').status_code==404
        assert c.patch(f'/api/avatars/{a}/messages/{first["id"]}/favorite',json={'starred':True}).status_code==200
        assert len(c.get(f'/api/avatars/{a}/favorites').json())==1
        copied=c.post(f'/api/avatars/{a}/messages/{first["id"]}/resend',json={'name':'收藏','client_key':'copy'}).json()
        assert copied['id']!=first['id'] and c.get(copied['media_url']).content==b'hello'
        assert not c.app.state.db.all('SELECT * FROM imports WHERE avatar_id=?',(a,))


def test_media_validation_and_preview_timeline(tmp_path,monkeypatch):
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        assert upload(c,a,b'<script>alert(1)</script>','bad.png','image').status_code==415
        assert upload(c,a,b'','empty.txt').status_code==400
        assert upload(c,a,b'<svg/>','bad.svg','image').status_code==415
        png=io.BytesIO();Image.new('RGB',(4,4),'green').save(png,format='PNG')
        row=upload(c,a,png.getvalue(),'图片.png','image',preview_mode=True).json()
        assert c.get(row['media_url']).headers['content-type'].startswith('image/png')
        assert c.get(f'/api/avatars/{a}/messages').json()==[]
        assert len(c.get(f'/api/avatars/{a}/messages?timeline_kind=preview').json())==1
        assert not list((tmp_path/'avatars'/a/'chat-attachments').glob('*.svg'))


def test_voice_transcript_reply_preserves_one_audio_bubble(tmp_path,monkeypatch):
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        row=upload(c,a,b'RIFF'+b'\x00'*40,'voice.wav','audio',duration=3).json()
        response=c.post(f'/api/avatars/{a}/chat/stream',json={'message':'今天一起散步吧','source_message_id':row['id']})
        assert response.status_code==200
        rows=c.get(f'/api/avatars/{a}/messages').json()
        assert len(rows)==2 and rows[0]['message_kind']=='audio'
        assert rows[0]['content']=='今天一起散步吧' and rows[1]['role']=='assistant'
        other=create_avatar(c)
        assert c.post(f'/api/avatars/{other}/chat',json={'message':'越界','source_message_id':row['id']}).status_code==404


def test_manual_location_and_idempotency(tmp_path,monkeypatch):
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        payload={'name':'图书馆','address':'南门','client_key':'location-1'}
        row=c.post(f'/api/avatars/{a}/messages/location',json=payload).json()
        assert row['message_kind']=='location' and row['attachment']['address']=='南门'
        assert c.post(f'/api/avatars/{a}/messages/location',json=payload).json()['id']==row['id']


def test_attachment_export_import_and_privacy_filter(tmp_path,monkeypatch):
    import zipfile
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        row=upload(c,a,b'private attachment').json()
        c.patch(f'/api/avatars/{a}/messages/{row["id"]}/favorite',json={'starred':True})
        full=c.post(f'/api/avatars/{a}/export')
        assert full.status_code==200
        imported=c.post('/api/packages/import',content=full.content,headers={'Content-Type':'application/zip','X-File-Name':'avatar.openavatar.zip','X-Rights-Confirmed':'true'})
        assert imported.status_code==201, imported.text
        b=imported.json()['id']
        rows=c.get(f'/api/avatars/{b}/messages').json()
        assert rows[0]['message_kind']=='file' and rows[0]['starred']==1
        assert c.get(rows[0]['media_url']).content==b'private attachment'
        limited=c.post(f'/api/avatars/{a}/export?include_conversations=false')
        with zipfile.ZipFile(io.BytesIO(limited.content)) as z:
            assert not any('chat-attachments' in n for n in z.namelist())


def test_voice_note_keeps_80_character_limit(tmp_path,monkeypatch):
    from test_runtime import FakeStreamingProvider
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        row=upload(c,a,b'RIFF'+b'\x00'*40,'voice.wav','audio').json()
        monkeypatch.setattr(FakeStreamingProvider,'stream_chat',lambda *_:iter(['甲'*60,'乙'*60]))
        response=c.post(f'/api/avatars/{a}/chat/stream',json={'message':'介绍自己','source_message_id':row['id']})
        done=json.loads(response.text.splitlines()[-1])
        assert len(done['reply'])==80
        assert len(c.get(f'/api/avatars/{a}/messages').json()[-1]['content'])==80


def test_preview_voice_reply_stays_with_its_audio_message(tmp_path,monkeypatch):
    with make_client(tmp_path,monkeypatch) as c:
        a=create_avatar(c)
        row=upload(c,a,b'RIFF'+b'\x00'*40,'preview.wav','audio',preview_mode=True).json()
        reply=c.post(f'/api/avatars/{a}/chat/stream',json={'message':'预览语音','source_message_id':row['id'],'preview_mode':True})
        assert reply.status_code==200
        rows=c.get(f'/api/avatars/{a}/messages?timeline_kind=preview').json()
        assert len(rows)==2 and rows[0]['message_kind']=='audio' and rows[1]['role']=='assistant'
        assert c.get(f'/api/avatars/{a}/messages').json()==[]
