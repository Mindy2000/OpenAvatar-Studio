from openavatar.services.minimax import MiniMaxClient

def test_clone_sends_integer_file_id_and_keeps_selected_identity(tmp_path, monkeypatch):
    client = MiniMaxClient('local-test')
    monkeypatch.setattr(client, '_upload', lambda path: {'file': {'file_id': '365182159339614'}})
    sent = []
    monkeypatch.setattr(client, '_request', lambda capability, payload: sent.append((capability, payload)) or {'base_resp': {'status_code': 0}})
    result = client.clone_voice(tmp_path/'sample.wav', voice_id='approved_sample', config={'request': {'file_id': 9, 'voice_id': 'wrong', 'need_noise_reduction': False}})
    assert sent[0][1]['file_id'] == 365182159339614
    assert sent[0][1]['voice_id'] == 'approved_sample'
    assert result['voice_id'] == 'approved_sample'
