"""DATA-01..13: all fixtures and API adapters are local and disposable."""
import io
import json
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest

from test_runtime import create_avatar, make_client, FakeStreamingProvider
from openavatar.services.memory_intelligence import effective_memories, review_memory, sleep_consolidation
from openavatar.services.packages import export_avatar, import_avatar_package, inspect_avatar_package
from openavatar.services.persona import relevant_memories
from openavatar.services.persona_core import current_persona_core
from openavatar.services.timeline_archive import correct_historical_memory
from openavatar.services.world_model import propose_fact, review_proposal, WorldModelError
from openavatar.services.world_runtime import advance_world, rollback_last_event, runtime_state


def package_bytes(*, version=3, messages=None, extra=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', json.dumps({'format': 'openavatar.package', 'version': version, 'avatar': {'id': 'source-uuid', 'name': 'Package fixture'}}))
        archive.writestr('memories.json', '[]')
        archive.writestr('messages.json', json.dumps(messages or []))
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return data.getvalue()


def add_memory(db, avatar_id, content, *, kind='fact', origin='legacy_baseline', scope='official', is_avatar=0):
    return db.execute('INSERT INTO memories(avatar_id,speaker,content,kind,origin_kind,timeline_kind,is_avatar,created_at) VALUES(?,?,?,?,?,?,?,0)', (avatar_id, 'fixture', content, kind, origin, scope, is_avatar))


def test_restore_rejects_foreign_and_newer_databases_without_changes(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        folder = tmp_path / 'backups'
        folder.mkdir()
        foreign = folder / 'openavatar-foreign.sqlite'
        with sqlite3.connect(foreign) as conn:
            conn.execute('CREATE TABLE unrelated(value TEXT)')
        response = client.post('/api/system/backups/openavatar-foreign.sqlite/restore', params={'confirmation': 'RESTORE OPENAVATAR DATABASE'})
        assert response.status_code == 400
        assert db.one('SELECT id FROM avatars WHERE id=?', (aid,))
        newer = db.backup(folder / 'openavatar-newer.sqlite')
        with sqlite3.connect(newer) as conn:
            conn.execute("UPDATE schema_meta SET value='9999' WHERE key='schema_version'")
        response = client.post('/api/system/backups/openavatar-newer.sqlite/restore', params={'confirmation': 'RESTORE OPENAVATAR DATABASE'})
        assert response.status_code == 400
        assert db.one('SELECT id FROM avatars WHERE id=?', (aid,))


def test_restore_safety_copy_is_listed_and_can_undo(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        first = client.post('/api/system/backup').json()['filename']
        db.execute("UPDATE avatars SET name='After backup' WHERE id=?", (aid,))
        epoch = db.notification_epoch()
        restore = client.post(f'/api/system/backups/{first}/restore', params={'confirmation': 'RESTORE OPENAVATAR DATABASE'})
        assert restore.status_code == 200, restore.text
        safety = restore.json()['safety_backup']
        assert safety in [row['filename'] for row in client.get('/api/system/backups').json()['items']]
        assert db.notification_epoch() != epoch
        assert db.one('SELECT name FROM avatars WHERE id=?', (aid,))['name'] != 'After backup'
        undo = client.post(f'/api/system/backups/{safety}/restore', params={'confirmation': 'RESTORE OPENAVATAR DATABASE'})
        assert undo.status_code == 200
        assert db.one('SELECT name FROM avatars WHERE id=?', (aid,))['name'] == 'After backup'


@pytest.mark.parametrize('bad', ['crc', 'attachment', 'optional_type', 'numeric'])
def test_package_preflight_and_import_reject_corruption_atomically(tmp_path, monkeypatch, bad):
    with make_client(tmp_path, monkeypatch) as client:
        kwargs = {}
        if bad == 'attachment':
            kwargs['messages'] = [{'role': 'user', 'content': 'fixture', 'attachment_json': [{'bad': 'type'}]}]
        elif bad == 'optional_type':
            kwargs['extra'] = {'world_snapshots.json': '{}'}
        elif bad == 'numeric':
            kwargs['messages'] = [{'role': 'user', 'created_at': []}]
        else:
            kwargs['extra'] = {'assets/fixture.txt': 'CRC_MARKER_7812'}
        payload = package_bytes(**kwargs)
        if bad == 'crc':
            payload = payload.replace(b'CRC_MARKER_7812', b'CRC_MARKER_7813', 1)
        headers = {'X-File-Name': 'fixture.zip', 'X-Rights-Confirmed': 'true'}
        for route in ('inspect', 'import'):
            response = client.post('/api/packages/' + route, content=payload, headers=headers)
            assert response.status_code == 400, response.text
        assert client.app.state.db.one('SELECT COUNT(*) n FROM avatars')['n'] == 0
        assert not list((tmp_path / 'avatars').glob('*'))


def test_package_disk_failure_rolls_back_db_and_staged_files(tmp_path, monkeypatch):
    import openavatar.services.packages as packages
    with make_client(tmp_path, monkeypatch) as client:
        target = tmp_path / 'fixture.zip'
        target.write_bytes(package_bytes(extra={'assets/fixture.txt': 'asset'}))
        def fail(*args, **kwargs):
            raise OSError('simulated disk full')
        monkeypatch.setattr(packages.shutil, 'copyfileobj', fail)
        with pytest.raises(ValueError, match='未新增人物'):
            import_avatar_package(client.app.state.db, tmp_path / 'avatars', target)
        assert client.app.state.db.one('SELECT COUNT(*) n FROM avatars')['n'] == 0
        assert list((tmp_path / 'avatars').iterdir()) == []


@pytest.mark.parametrize('version', [1, 2, 3])
def test_legacy_minimal_package_and_modern_uuid_round_trip(tmp_path, monkeypatch, version):
    with make_client(tmp_path, monkeypatch) as client:
        path = tmp_path / 'legacy.zip'
        path.write_bytes(package_bytes(version=version))
        assert inspect_avatar_package(path)['ok']
        db = client.app.state.db
        imported = import_avatar_package(db, tmp_path / 'avatars', path)
        archive = export_avatar(db, tmp_path / 'avatars', tmp_path / 'exports', imported['id'])
        assert inspect_avatar_package(archive)['ok']
        second = import_avatar_package(db, tmp_path / 'avatars', archive)
        assert second['id'] != imported['id']


def test_persona_reads_current_import_and_world_dependencies(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, messages, **kw: captured.append(messages) or '好的')
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        base = '/api/avatars/' + aid
        db = client.app.state.db
        first = current_persona_core(db, aid)
        assert current_persona_core(db, aid)['updated_at'] == first['updated_at']
        data = '# 角色\n## 人物简介\nNEW_PROFILE_8841 是大三学生。\n'.encode()
        uploaded = client.post(base + '/imports?category=fictional', content=data, headers={'X-File-Name': 'fixture.md'}).json()
        response = client.post(base + f"/imports/{uploaded['id']}/confirm", json={'apply_mode': 'replace'})
        assert response.status_code == 200, response.text
        propose_fact(db, aid, fact_key='campus.name', value='CAMPUS_CHANGED_6217')
        response = client.post(base + '/chat', json={'message': '介绍校园'})
        assert response.status_code == 200
        prompt = json.dumps(captured[-1], ensure_ascii=False)
        assert 'NEW_PROFILE_8841' in prompt and 'CAMPUS_CHANGED_6217' in prompt
        advance_world(db, aid, seconds=21600)
        assert any(row['key'] == 'runtime.local_minute' and row['value'] == 360 for row in current_persona_core(db, aid)['core']['world_context'])
        rollback_last_event(db, aid)
        assert not any(row['key'] == 'runtime.local_minute' and row['value'] == 360 for row in current_persona_core(db, aid)['core']['world_context'])


def test_analyze_uses_only_corrected_active_official_inputs(tmp_path, monkeypatch):
    import openavatar.routes.identity as identity
    captured = []
    monkeypatch.setattr(identity, 'model_client', lambda *args: FakeStreamingProvider())
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **kw: captured.append(rows) or json.dumps({'summary': 'fixture', 'traits': [], 'speaking_style': '', 'boundaries': ''}))
    with make_client(tmp_path, monkeypatch) as client:
        aid = client.post('/api/avatars', json={'name': 'Fixture', 'subject_kind': 'fictional', 'adult_subject': True, 'consent_confirmed': True}).json()['id']
        db = client.app.state.db
        rejected = add_memory(db, aid, 'REJECTED_SOURCE', is_avatar=1)
        review_memory(db, aid, rejected, 'reject')
        add_memory(db, aid, 'PREVIEW_SOURCE', origin='runtime_chat', scope='preview', is_avatar=1)
        original = add_memory(db, aid, 'OLD_SOURCE', is_avatar=1)
        correct_historical_memory(db, aid, original, {'content': 'CORRECT_SOURCE'})
        result = client.post(f'/api/avatars/{aid}/analyze')
        assert result.status_code == 200, result.text
        prompt = json.dumps(captured[-1])
        assert 'CORRECT_SOURCE' in prompt
        assert not any(marker in prompt for marker in ('REJECTED_SOURCE', 'PREVIEW_SOURCE', 'OLD_SOURCE'))


def test_import_review_pages_preserve_explicit_review_scope(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        base = f'/api/avatars/{aid}'
        def upload():
            return client.post(base + '/imports?category=conversation', content='\n'.join(f'Me: row {i}' for i in range(305)).encode(), headers={'X-File-Name': 'rows.txt'}).json()['id']
        iid = upload()
        first = client.get(f'{base}/imports/{iid}/preview').json()
        second = client.get(f'{base}/imports/{iid}/preview?offset=300').json()
        assert len(first['rows']) == 300 and len(second['rows']) == 5
        reviewed = [row['id'] for row in first['rows'] + second['rows']]
        response = client.post(f'{base}/imports/{iid}/confirm', json={'reviewed_row_ids': reviewed, 'excluded_row_ids': [row['id'] for row in first['rows']]})
        assert response.json()['accepted'] == 5
        iid = upload()
        first = client.get(f'{base}/imports/{iid}/preview').json()
        # A legacy client excluding all visible rows must not import hidden rows.
        response = client.post(f'{base}/imports/{iid}/confirm', json={'excluded_row_ids': [row['id'] for row in first['rows']]})
        assert response.json()['accepted'] == 0


def test_maintenance_edits_visible_old_row_without_truncated_refetch():
    source = Path(__file__).resolve().parents[1] / 'openavatar/static/maintenance.js'
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const requests=[];
const context={state:{currentId:'avatar',maintenanceMemories:{avatarId:'avatar',items:[{id:1,content:'old row'}]}},ui:(a)=>a,prompt:()=> 'edited row',api:async(url,options)=>{requests.push([url,options]); return [];}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.openMaintenance=async()=>{};
(async()=>{await context.handleMaintenance('maintenance-edit-memory',{dataset:{id:'1'}});assert.equal(requests.length,1);assert.equal(requests[0][0],'/api/avatars/avatar/memories/1');assert.equal(JSON.parse(requests[0][1].body).content,'edited row');})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(['node', '-e', script, str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_review_page_navigation_keeps_checkbox_and_speaker_choices():
    source = Path(__file__).resolve().parents[1] / 'openavatar/static/imports.js'
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let checks=[{dataset:{rowId:'1'},checked:false},{dataset:{rowId:'2'},checked:true}];
const elements={};const $=key=>elements[key] ||= {classList:{toggle(){}},append(){}};
const preview={import:{category:'conversation'},speakers:[{speaker:'Me',count:305}],rows:[{id:301,speaker:'Me',content:'last page'}],total:305,offset:300,limit:300,truncated:false};
const current={id:9,avatarId:'avatar',reviewed:new Set(),excluded:new Set(),speakers:null,preview};
const context={state:{currentId:'avatar',currentImport:current},$,$$:key=>key.startsWith('#reviewRows')?checks:[{value:'Me'}],api:async()=>preview,ui:(a)=>a,tr:(a)=>a,escapeHtml:a=>a,document:{createElement:()=>({addEventListener(){}})}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{await context.changeImportReviewPage(300);assert(current.reviewed.has(1));assert(current.reviewed.has(301));assert(current.excluded.has(1));assert(!current.excluded.has(2));assert.deepEqual(current.speakers,['Me']);checks=[{dataset:{rowId:'301'},checked:false}];context.saveImportReviewSelection();assert(current.excluded.has(1)&&current.excluded.has(301));})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(['node', '-e', script, str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_image_text_save_does_not_replace_a_new_import_review():
    source = Path(__file__).resolve().parents[1] / 'openavatar/static/imports.js'
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');let resolve,rendered=0;
const before={id:1,avatarId:'a',preview:{marker:'before'}};
const after={id:2,avatarId:'b',preview:{marker:'after'}};
const context={state:{currentId:'a',currentImport:before},$:()=>({value:'new image text'}),api:()=>new Promise(done=>resolve=done)};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);context.renderImportReview=()=>rendered++;
(async()=>{const work=context.saveImportImageText();context.state.currentId='b';context.state.currentImport=after;resolve({marker:'late',rows:[],total:0});await work;assert.equal(after.preview.marker,'after');assert.equal(rendered,0);})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(['node', '-e', script, str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_approve_restores_previous_memory_kind_and_context(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        mid = add_memory(db, aid, 'approved fact')
        review_memory(db, aid, mid, 'reject')
        assert not effective_memories(db, aid)
        approved = review_memory(db, aid, mid, 'approve')
        assert approved['kind'] == 'fact' and approved['confidence'] == 1
        assert effective_memories(db, aid)[0]['content'] == 'approved fact'


def test_consolidation_is_idempotent_and_correction_retires_old_summary(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        mids = [add_memory(db, aid, f'Campus OLD_NAME_{i}', kind='conversation') for i in range(3)]
        assert sleep_consolidation(db, aid)['created'] == 1
        assert sleep_consolidation(db, aid)['created'] == 0
        correct_historical_memory(db, aid, mids[0], {'content': 'Campus CORRECT_NAME'})
        assert all('OLD_NAME_0' not in row['content'] for row in effective_memories(db, aid))
        assert sleep_consolidation(db, aid)['created'] == 1
        assert sleep_consolidation(db, aid)['created'] == 0
        active = [row for row in effective_memories(db, aid) if row['kind'] == 'consolidated_summary']
        assert len(active) == 1 and 'CORRECT_NAME' in active[0]['content']
        archive = export_avatar(db, tmp_path / 'avatars', tmp_path / 'exports', aid, include_conversations=False)
        with zipfile.ZipFile(archive) as z:
            assert not any(b'OLD_NAME_' in z.read(name) or b'CORRECT_NAME' in z.read(name) for name in z.namelist())


def test_old_explicit_memory_is_retrieved_after_thousand_newer_notes(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **kw: captured.append(rows) or '好的')
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        add_memory(db, aid, 'ANCHOR_7318 是大学的名字', origin='runtime_chat', kind='chat_note')
        with db.transaction() as connection:
            connection.executemany("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'x',?,'fact',0)", [(aid, f'其他独立资料 {i}') for i in range(1001)])
        result = client.post(f'/api/avatars/{aid}/chat', json={'message': 'ANCHOR_7318'})
        assert result.status_code == 200
        assert 'ANCHOR_7318 是大学的名字' in json.dumps(captured[-1], ensure_ascii=False)
    rows = [{'content': f'无关资料{i}'} for i in range(20)] + [{'content': '我在清华大学读书。'}]
    assert any('清华' in row['content'] for row in relevant_memories(rows, '你记得我在哪所大学读书吗？'))


def test_world_rollback_retires_event_and_readvance_reapplies_effects(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        resource = lambda state: {r['fact_key']: r['value'] for r in state['facts'] if r['fact_key'].startswith('resource.')}
        before = runtime_state(db, aid)
        first = advance_world(db, aid, seconds=21600, force_minor_event=True)
        rollback = rollback_last_event(db, aid)
        assert resource(rollback) == resource(before)
        assert all(row['status'] == 'rolled_back' for row in rollback['events'])
        second = advance_world(db, aid, seconds=21600, force_minor_event=True)
        assert resource(second) == resource(first)
        assert second['event']['id'] != first['event']['id']


def test_pending_proposal_conflict_is_explicit(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        first = propose_fact(db, aid, fact_key='campus', value='old', mutability='locked')
        assert propose_fact(db, aid, fact_key='campus', value='old', mutability='locked')['id'] == first['id']
        with pytest.raises(WorldModelError, match='待审批'):
            propose_fact(db, aid, fact_key='campus', value='new', mutability='locked')
        review_proposal(db, aid, first['id'], 'reject')
        second = propose_fact(db, aid, fact_key='campus', value='new', mutability='locked')
        assert review_proposal(db, aid, second['id'], 'approve')['value'] == 'new'


def test_package_world_snapshot_remaps_evidence_and_events(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        other = create_avatar(client)
        db = client.app.state.db
        db.execute("INSERT INTO evidence(avatar_id,source_type,title,content,created_at) VALUES(?,'fixture','other','other',0)", (other,))
        eid = db.execute("INSERT INTO evidence(avatar_id,source_type,title,content,created_at) VALUES(?,'fixture','source','source',0)", (aid,))
        propose_fact(db, aid, fact_key='campus', value='Campus', source_evidence_id=eid)
        advance_world(db, aid, seconds=21600, force_minor_event=True)
        advance_world(db, aid, seconds=21600, force_minor_event=True)
        archive = export_avatar(db, tmp_path / 'avatars', tmp_path / 'exports', aid)
        new_id = import_avatar_package(db, tmp_path / 'avatars', archive)['id']
        rollback_last_event(db, new_id)
        restored = db.one("SELECT source_evidence_id FROM world_facts WHERE avatar_id=? AND fact_key='campus' AND active=1", (new_id,))
        source = db.one('SELECT avatar_id,title FROM evidence WHERE id=?', (restored['source_evidence_id'],))
        assert source == {'avatar_id': new_id, 'title': 'source'}
        assert restored['source_evidence_id'] != eid
        live_events = db.all("SELECT * FROM world_events WHERE avatar_id=? AND status='fact'", (new_id,))
        assert len(live_events) == 1
        with db.connect() as connection:
            assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_consolidation_idempotence_survives_package_id_remap(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        aid = create_avatar(client)
        db = client.app.state.db
        for i in range(3):
            add_memory(db, aid, f'Topic fixture {i}', kind='conversation')
        assert sleep_consolidation(db, aid)['created'] == 1
        archive = export_avatar(db, tmp_path / 'avatars', tmp_path / 'exports', aid)
        imported = import_avatar_package(db, tmp_path / 'avatars', archive)['id']
        assert sleep_consolidation(db, imported)['created'] == 0
