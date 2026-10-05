from test_app import make_client, create_avatar


def test_merge_rejects_self_and_retired_duplicate_without_corrupting_memory(tmp_path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        base = '/api/avatars/' + avatar['id']
        imported = client.post(base + '/imports?category=conversation', content=b'Me: Library Wednesday\nMe: Library afternoon', headers={'X-File-Name':'memory.txt'}).json()
        assert client.post(base + f"/imports/{imported['id']}/confirm", json={'avatar_speakers':['Me']}).status_code == 200
        primary, duplicate = client.get(base + '/memories').json()[:2]
        assert client.post(base + '/memories/merge', json={'primary_id':primary['id'],'duplicate_id':primary['id']}).status_code == 400
        assert client.get(base + '/memory-revisions').json() == []
        response = client.post(base + '/memories/merge', json={'primary_id':primary['id'],'duplicate_id':duplicate['id']})
        assert response.status_code == 200
        merged = response.json()['content']
        assert primary['content'] in merged and duplicate['content'] in merged
        assert client.post(base + '/memories/merge', json={'primary_id':primary['id'],'duplicate_id':duplicate['id']}).status_code == 400
        assert len(client.get(base + '/memory-revisions').json()) == 2
        assert next(r for r in client.get(base + '/memories').json() if r['id']==primary['id'])['content'] == merged
