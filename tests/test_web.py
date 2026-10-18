import uuid

from fastapi.testclient import TestClient

from gemma_codenames.board import load_words
from gemma_codenames.bots import BotService, DemoEncoder
from gemma_codenames.service import EmbeddingService
from gemma_codenames.web import create_app


def demo_app():
    return create_app(BotService(EmbeddingService(DemoEncoder(), load_words()), 'demo'), delay=.01)


def send(ws, state, kind, **fields):
    ws.send_json({'actionId':uuid.uuid4().hex,'version':state['version'],
                  'action':{'type':kind, **fields}})


def until(ws, predicate):
    for _ in range(100):
        message=ws.receive_json()
        assert message['type'] != 'error', message
        if message['type']=='state' and predicate(message['room']):
            return message['room']
    raise AssertionError('Expected room state did not arrive')


def test_room_step_analysis_and_reconnect():
    with TestClient(demo_app()) as client:
        response=client.get('/')
        assert response.status_code==200 and 'gemma_session' in client.cookies
        result=client.post('/api/rooms',json={}).json()
        assert client.get(result['url']).status_code==200
        with client.websocket_connect('/ws/'+result['code']) as ws:
            state=until(ws,lambda s:True)
            send(ws,state,'spectate')
            state=until(ws,lambda s:s['spectator'])
            send(ws,state,'start')
            state=until(ws,lambda s:s['phase']=='clue')
            assert state['paused']
            send(ws,state,'step')
            searching=until(ws,lambda s:s.get('liveSearch') is not None)
            assert searching['pending'] and searching['liveSearch']['depth'] == 1
            state=until(ws,lambda s:s['phase']=='guess' and not s['pending'])
            assert state['liveSearch'] is None
            assert state['analysis']['matrixShape']==[len(load_words()),25]
            assert len(state['plot']['points'])==27+len(state['clue']['message']['components'])
            assert len(state['analysis']['heatmap']['rows'])==1+len(state['clue']['message']['components'])
            assert state['history'][0]['clue']['analysis']
        with client.websocket_connect('/ws/'+result['code']) as ws:
            state=until(ws,lambda s:True)
            assert state['isHost'] and state['spectator'] and state['phase']=='guess'


def test_remote_origin_rejection_and_nonhost_commands():
    app=demo_app()
    with TestClient(app) as host:
        host.get('/')
        assert host.post('/api/rooms',json={},headers={'origin':'https://evil.example'}).status_code==403
        result=host.post('/api/rooms',json={}).json()
        with TestClient(app) as guest:
            guest.get('/')
            with guest.websocket_connect('/ws/'+result['code']) as ws:
                state=until(ws,lambda s:True)
                assert not state['isHost']
                send(ws,state,'start')
                assert ws.receive_json()['type']=='error'


def test_model_error_is_visible_and_never_falls_back_to_synthetic_scores():
    class BrokenEncoder(DemoEncoder):
        def encode(self, words):
            raise RuntimeError('simulated model failure')
    bot=BotService(EmbeddingService(BrokenEncoder(),load_words()),'gemma')
    with TestClient(create_app(bot,delay=.01)) as client:
        client.get('/')
        code=client.post('/api/rooms',json={}).json()['code']
        with client.websocket_connect('/ws/'+code) as ws:
            state=until(ws,lambda s:True)
            send(ws,state,'start');state=until(ws,lambda s:s['phase']=='clue')
            send(ws,state,'step');state=until(ws,lambda s:s['botError'])
            assert state['clue'] is None and state['botMode']=='gemma'
            assert not state['pending']


def test_all_bot_game_finishes_and_history_is_available():
    with TestClient(demo_app()) as client:
        client.get('/')
        code=client.post('/api/rooms',json={}).json()['code']
        with client.websocket_connect('/ws/'+code) as ws:
            state=until(ws,lambda s:True)
            send(ws,state,'start');state=until(ws,lambda s:s['phase']=='clue')
            send(ws,state,'pause')
            for _ in range(500):
                data=ws.receive_json()
                assert data['type']=='state', data
                state=data['room']
                if state['phase']=='finished':
                    break
            assert state['phase']=='finished'
            assert state['winner'] in ('red','blue')
            assert state['canSeeKey']
            assert state['history'][0]['clue']['analysis']['heatmap']


def test_human_clue_scores_are_computed_before_guessing():
    with TestClient(demo_app()) as client:
        client.get('/')
        code=client.post('/api/rooms',json={}).json()['code']
        with client.websocket_connect('/ws/'+code) as ws:
            state=until(ws,lambda s:True)
            send(ws,state,'claim',slotId='red-spymaster',controller='human',name='Tester')
            state=until(ws,lambda s:s['yourSeat']=='red-spymaster')
            send(ws,state,'ready');state=until(ws,lambda s:s['canStart'])
            send(ws,state,'start');state=until(ws,lambda s:s['phase']=='clue')
            from gemma_codenames.board import Card
            from gemma_codenames.optimizer import CluePolicy
            policy=CluePolicy([Card(c['word'],c['kind']) for c in state['board']])
            word=next(w for w in load_words() if policy.allows(w))
            send(ws,state,'clue',word=word,count=1)
            state=until(ws,lambda s:s['phase']=='guess' and not s['pending'])
            assert state['plot'] is None and state['analysis'] is None
            assert not state['canSeeAnalysis']
            assert all(c['score'] is None for c in state['board'])
            assert 'plot' not in state['history'][0]['clue']


def test_lab_round_trip_is_seeded_owner_private_and_validated():
    import time
    with TestClient(demo_app()) as client:
        assert client.post('/api/lab', json={}).status_code == 403
        assert client.get('/lab').status_code == 200
        assert client.post('/api/lab', json={'communication': {'max_words': 13}}).status_code == 422
        assert client.post('/api/lab', json={}, headers={'origin': 'https://evil.example'}).status_code == 403
        options = {'seed': 42, 'synthetic': True, 'board_size': 36,
                   'communication': {'max_words': 1, 'common_words_only': True}}
        job = client.post('/api/lab', json=options).json()['job_id']
        for _ in range(200):
            response = client.get('/api/lab/'+job)
            data = response.json()
            if data['status'] != 'running':
                break
            time.sleep(.02)
        assert data['status'] == 'complete', data
        result = data['result']
        assert result['source'] == 'demo' and result['seed'] == 42
        assert len(result['board']) == result['board_size'] == 36
        assert result['config']['common_words_only']
        from importlib.resources import files
        common = load_words(files('gemma_codenames').joinpath('data/clue_words_common.csv'), clues=True)
        assert result['matrix_shape'] == [len(common), 36]
        report = result['communication']
        assert report['reconstruction_error'] < 1e-10
        assert len(report['message']['components']) == 1
        assert set(report['message']) == {'version', 'weighted', 'precision', 'components', 'count', 'model'}
        assert 'owner' not in data
        client.cookies.clear()
        client.get('/lab')
        assert client.get('/api/lab/'+job).status_code == 404


def test_small_common_only_room_restricts_bot_candidates():
    from pathlib import Path
    common = set(load_words(Path('gemma_codenames/data/clue_words_common.csv'), clues=True))
    bot = BotService(EmbeddingService(DemoEncoder(), ['air', 'ant', 'zebra', 'zzzzrare']), 'demo')
    with TestClient(create_app(bot, delay=.01)) as client:
        client.get('/')
        assert client.post('/api/rooms', json={'board_size': 10}).status_code == 422
        assert client.post('/api/rooms', json={'communication': {'common_words_only': 'yes'}}).status_code == 422
        code = client.post('/api/rooms', json={'board_size': 9, 'communication': {
            'common_words_only': True, 'max_words': 1}}).json()['code']
        with client.websocket_connect('/ws/'+code) as ws:
            state = until(ws, lambda s: True)
            assert len(state['board']) == state['board_size'] == 9
            send(ws, state, 'spectate'); state = until(ws, lambda s: s['spectator'])
            send(ws, state, 'start'); state = until(ws, lambda s: s['phase'] == 'clue')
            send(ws, state, 'step'); state = until(ws, lambda s: s['phase'] == 'guess')
            assert state['analysis']['matrixShape'] == [3, 9]
            assert state['analysis']['config']['common_words_only']
            assert all(c['word'] in common for c in state['clue']['message']['components'])
    assert bot.service.vocabulary == ['air', 'ant', 'zebra', 'zzzzrare']


def test_room_codes_are_unique_board_words_and_join_case_insensitively():
    with TestClient(demo_app()) as client:
        client.get('/')
        rooms = [client.post('/api/rooms', json={}).json() for _ in range(3)]
        codes = [room['code'] for room in rooms]
        assert len(set(codes)) == 3
        assert all(code.lower() in load_words() and code.isalpha() and len(code) <= 4 for code in codes)
        for room in rooms:
            assert client.get(room['url'].lower()).status_code == 200
            with client.websocket_connect('/ws/' + room['code'].lower()) as ws:
                state = until(ws, lambda s: True)
                assert state['code'] == room['code']
