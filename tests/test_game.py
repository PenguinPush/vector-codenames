import json
import uuid

import pytest

from gemma_codenames.board import load_words
from gemma_codenames.game import (Command, GameError, accept_clue, apply_action,
                                  make_room, project, reveal)

WORDS = load_words()


def action(room, user, kind, **fields):
    command = Command(actionId=uuid.uuid4().hex, version=room['version'],
                      action={'type': kind, **fields})
    apply_action(room, user, command, WORDS, 'demo')
    return command


def test_spectator_and_spymaster_secrets_are_absent_from_public_payload():
    room = make_room('ABC', 'host', WORDS)
    action(room, 'viewer', 'spectate')
    action(room, 'master', 'claim', slotId='red-spymaster', controller='human')
    action(room, 'guesser', 'claim', slotId='red-guesser', controller='human')
    action(room, 'master', 'ready')
    action(room, 'guesser', 'ready')
    action(room, 'host', 'start')
    clue = {'word': 'secret', 'count': 1, 'team': 'red', 'scores': {},
            'message': {'components': [{'word': 'secret', 'coefficient': 1}], 'count': 1},
            'analysis': {'targets': ['HIDDEN_TARGET'], 'heatmap': {'secret': 1},
                         'communication': {'vectors': {'ideal': ['PRIVATE_IDEAL']}}},
            'plot': {'points': [{'word': 'SECRET', 'x': 0, 'y': 0}]}}
    accept_clue(room, clue)
    room["liveSearch"] = {"best": "PRIVATE_SEARCH"}
    for user in ['public', 'guesser', 'host']:
        view = project(room, user, 'demo')
        assert not any(c['kind'] for c in view['board'])
        assert view['analysis'] is None
        assert 'HIDDEN_TARGET' not in json.dumps(view)
        assert 'heatmap' not in json.dumps(view)
        assert view['liveSearch'] is None
        assert 'PRIVATE_IDEAL' not in json.dumps(view)
        assert view['clue']['message']['components'][0]['word'] == 'secret'
    assert project(room, 'viewer', 'demo')['analysis']['targets'] == ['HIDDEN_TARGET']
    assert project(room, 'viewer', 'demo')['liveSearch'] == {'best': 'PRIVATE_SEARCH'}
    for user in ['master', 'guesser']:
        for phase in ['guess', 'finished']:
            room['phase'] = phase
            view = project(room, user, 'demo')
            assert not view['canSeeAnalysis']
            assert view['liveSearch'] is None
            assert view['analysis'] is None and view['plot'] is None
            assert all(c['score'] is None for c in view['board'])
            assert 'PRIVATE_IDEAL' not in json.dumps(view)
            assert 'plot' not in view['history'][0]['clue']
    room['phase'] = 'guess'
    assert project(room, 'master', 'demo')['canSeeKey']
    with pytest.raises(GameError):
        action(room, 'viewer', 'claim', slotId='blue-guesser', controller='bot')
    with pytest.raises(GameError):
        action(room, 'master', 'spectate')


def test_duplicate_guess_is_idempotent_and_old_version_is_rejected():
    room = make_room('ABC', 'host', WORDS)
    action(room, 'user', 'claim', slotId='red-guesser', controller='human')
    action(room, 'user', 'ready')
    action(room, 'host', 'start')
    accept_clue(room, {'word':'orbit','count':3,'scores':{'w0':.8},'analysis':{},'team':'red'})
    card = next(c for c in room['board'] if c['kind']=='red')
    command = action(room, 'user', 'guess', cardId=card['id'])
    version = room['version']
    assert apply_action(room, 'user', command, WORDS, 'demo') is False
    assert room['guesses'] == 1 and room['version'] == version
    command.actionId = uuid.uuid4().hex
    with pytest.raises(GameError, match='room changed'):
        apply_action(room, 'user', command, WORDS, 'demo')


def test_assassin_loss_and_opponent_last_card_win():
    room = make_room('ABC', 'host', WORDS)
    room.update(phase='guess', clue={'word':'orbit','count':1})
    assassin = next(c for c in room['board'] if c['kind']=='assassin')
    reveal(room, assassin['id'])
    assert room['winner']=='blue' and room['phase']=='finished'
    room = make_room('ABC', 'host', WORDS)
    room.update(phase='guess', clue={'word':'orbit','count':1})
    blue = [c for c in room['board'] if c['kind']=='blue']
    for c in blue[:-1]: c['revealed']=True
    reveal(room, blue[-1]['id'])
    assert room['winner']=='blue'


def test_role_cannot_change_after_viewing_key_and_rematch_clears_it():
    room = make_room('ABC', 'host', WORDS)
    action(room, 'host', 'spectate')
    action(room, 'host', 'start')
    assert project(room,'host','demo')['canSeeKey']
    with pytest.raises(GameError):
        action(room,'host','claim',slotId='red-guesser',controller='bot')
    room['phase']='finished'
    action(room,'host','rematch')
    assert not project(room,'host','demo')['canSeeKey']
    action(room,'host','claim',slotId='red-guesser',controller='human')


def test_communication_configuration_is_host_only_locked_and_preserved():
    room = make_room('ABC', 'host', WORDS)
    config = {'max_words': 5, 'coefficients': True, 'precision': 3}
    with pytest.raises(GameError, match='Only the host'):
        action(room, 'guest', 'configure', communication=config)
    action(room, 'host', 'configure', communication=config)
    assert project(room, 'guest', 'demo')['communication']['max_words'] == 5
    action(room, 'host', 'start')
    with pytest.raises(GameError, match='locked'):
        action(room, 'host', 'configure', communication={'max_words': 1})
    room['phase'] = 'finished'
    action(room, 'host', 'rematch')
    assert room['communication']['precision'] == 3
    assert room['communication']['coefficients'] is True


def test_board_size_changes_reset_readiness_and_survive_rematch():
    room = make_room('ABC', 'host', WORDS)
    action(room, 'host', 'claim', slotId='red-spymaster', controller='human')
    action(room, 'host', 'ready')
    action(room, 'host', 'configure', board_size=9, communication={'common_words_only': True})
    assert len(room['board']) == room['board_size'] == 9
    assert not room['seats'][0]['ready']
    action(room, 'host', 'ready')
    action(room, 'host', 'start')
    with pytest.raises(GameError, match='locked'):
        action(room, 'host', 'configure', board_size=16, communication={})
    room['phase'] = 'finished'
    action(room, 'host', 'rematch')
    assert len(room['board']) == 9
    assert room['communication']['common_words_only']


def test_large_board_accepts_large_clue_counts_and_card_ids():
    room = make_room('ABC', 'host', WORDS, 100)
    action(room, 'host', 'claim', slotId='red-spymaster', controller='human')
    action(room, 'host', 'ready')
    action(room, 'host', 'start')
    action(room, 'host', 'clue', word='zzzzzz', count=34)
    assert room['clue']['count'] == 34
    command = Command(actionId='testlargeguess', version=room['version'],
                      action={'type': 'guess', 'cardId': 'w99'})
    assert command.action.cardId == 'w99'
    room['clue']['scores'] = {'w99': .8}
    # Card lookup and game result work beyond the original 25-card boundary.
    reveal(room, command.action.cardId)
    assert room['board'][99]['revealed']


def test_analysis_spectator_keeps_full_history_while_next_clue_searches():
    from gemma_codenames.game import next_turn
    room = make_room('MOON', 'host', WORDS)
    action(room, 'viewer', 'spectate')
    action(room, 'player', 'claim', slotId='red-guesser', controller='human')
    action(room, 'player', 'ready')
    action(room, 'host', 'start')
    clue = {'word': 'orbit', 'count': 1, 'team': 'red', 'scores': {'w0': .7},
            'plot': {'points': ['PRIVATE_GRAPH']},
            'analysis': {'model': {'details': 'PRIVATE_MODEL'}, 'heatmap': ['PRIVATE_SCORES']},
            'message': {'components': [{'word': 'orbit', 'coefficient': 1}], 'model': {'id': 'PRIVATE_MODEL'}}}
    accept_clue(room, clue)
    next_turn(room)
    room.update(pending=True, liveSearch={'best': 'PRIVATE_SEARCH'})
    viewer = project(room, 'viewer', 'demo')
    assert viewer['canSeeAnalysis'] and viewer['canSeeKey']
    assert viewer['history'][0]['clue']['scores'] == {'w0': .7}
    assert viewer['history'][0]['clue']['analysis'] == clue['analysis']
    assert viewer['history'][0]['clue']['plot'] == clue['plot']
    assert viewer['liveSearch']['best'] == 'PRIVATE_SEARCH'
    assert 'PRIVATE_' not in json.dumps(project(room, 'player', 'demo'))
