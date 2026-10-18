import itertools
import json

import numpy as np
import pytest

from gemma_codenames.board import Card
from gemma_codenames.communication import (CommunicationConfig, decode_vectors, evaluate,
                                          quantize, search)
from gemma_codenames.geometry import normalized
from gemma_codenames.service import EmbeddingService
from gemma_codenames.transmission_plot import transmission_projection


def fixture(weighted=False):
    vocabulary=['alpha','beta']
    vectors=np.array([[1.,0.],[0.,1.]])
    board=[Card('planet','red'),Card('rocket','assassin'),Card('stone','blue')]
    board_vectors=np.array([[.9,.1],[1.,0.],[1.,1.]]) if weighted else np.array([[1.,1.],[1.,0.],[0.,1.]])
    return vocabulary,vectors,board,board_vectors


def config(**kwargs):
    return CommunicationConfig(time_limit=2.0,max_evaluations=100,**kwargs)


def test_two_words_one_shot_when_no_single_word_qualifies():
    result=search(*fixture(), 'red',config(max_words=2))
    assert result['baseline']['coverage']==0
    assert result['best']['coverage']==1
    assert set(result['best']['words'])=={'alpha','beta'}
    assert result['stop_reason']=='one_shot'
    q=decode_vectors(result['message'],fixture()[1])
    np.testing.assert_allclose(q,[1/np.sqrt(2),1/np.sqrt(2)])


def test_coefficients_improve_equal_sum_and_transmitted_rounding_is_respected():
    equal=search(*fixture(True),'red',config(max_words=2))
    assert equal['best']['coverage']==0
    weighted=search(*fixture(True),'red',config(max_words=2,coefficients=True,precision=2))
    assert weighted['best']['coverage']==1
    assert weighted['best']['full_gap']>0
    coefficients=[c['coefficient'] for c in weighted['message']['components']]
    assert sum(coefficients)==pytest.approx(1)
    assert all(abs(a*100-round(a*100))<1e-10 for a in coefficients)
    coarse=search(*fixture(True),'red',config(max_words=2,coefficients=True,precision=0))
    assert coarse['best']['coverage']==0  # Rounding is evaluated, never an idealized weight.


def test_search_matches_exhaustive_subsets_when_small_pool_fits_beam():
    rng=np.random.default_rng(8)
    words=['alpha','beta','gamma','delta']
    vectors=normalized(rng.normal(size=(4,3)))
    board=[Card('moon','red'),Card('planet','red'),Card('rocket','assassin')]
    bv=normalized(rng.normal(size=(3,3)))
    cfg=config(max_words=3,beam_width=32,stop_at_one_shot=False)
    result=search(words,vectors,board,bv,'red',cfg)
    expected=[]
    for n in range(1,4):
        for ids in itertools.combinations(range(4),n):
            q=normalized([vectors[list(ids)].sum(axis=0)])[0]
            stats=evaluate(q,bv,np.array([0,1]),np.array([2]),cfg.target_gap)
            expected.append((stats['coverage'],stats['gap'],-n,stats['mean']))
    best=result['best']
    assert (best['coverage'],best['gap'],-best['word_count'])==pytest.approx(max(expected)[:3])
    gaps=[t['best_one_shot_gap'] for t in result['trace']]
    assert gaps==sorted(gaps)


def test_budget_is_reported_and_baseline_is_retained():
    words=['alpha','beta','gamma','delta']
    rng=np.random.default_rng(7)
    cfg=CommunicationConfig(max_words=4,max_evaluations=1,time_limit=2.0,stop_at_one_shot=False)
    result=search(words,rng.normal(size=(4,3)),fixture()[2],rng.normal(size=(3,3)),'red',cfg)
    assert result['stop_reason']=='evaluation_budget'
    assert result['extension_evaluations']==1
    assert result['best']['coverage']>=result['baseline']['coverage']


def test_rounding_cancellation_and_invalid_coefficients():
    np.testing.assert_allclose(quantize([1,1,1],2),[.34,.33,.33])
    message={'version':1,'weighted':False,'precision':None,
             'components':[{'word':'alpha','coefficient':1},{'word':'beta','coefficient':1}]}
    with pytest.raises(ValueError,match='cancels'):
        decode_vectors(message,[[1,0],[-1,0]])
    message['weighted']=True;message['precision']=2
    message['components'][0]['coefficient']=-.5
    with pytest.raises(ValueError,match='positive'):
        decode_vectors(message,[[1,0],[0,1]])
    message['components'][0]['coefficient']=.333
    message['components'][1]['coefficient']=.667
    with pytest.raises(ValueError,match='precision'):
        decode_vectors(message,[[1,0],[0,1]])


def test_ties_are_not_one_shots_and_ideal_zero_is_not_normalized():
    vectors=np.array([[1.,0],[0.,1]])
    board=[Card('planet','red'),Card('rocket','assassin')]
    result=search(['alpha','beta'],vectors,board,[[1,0],[1,0]],'red',config(max_words=2))
    assert result['best']['coverage']==0
    assert result['_ideal_vector'] is None
    assert abs(result['ideal']['upper_bound'])<1e-6


def test_wire_roundtrip_independent_decoder_and_private_information_boundary():
    class Encoder:
        metadata={'model_id':'controlled','resolved_revision':'one','dimensions':2}
        def encode(self, words):
            mapping={'alpha':[1,0],'beta':[0,1],'planet':[1,1],'rocket':[1,0],'stone':[0,1]}
            return np.array([mapping[w.lower()] for w in words],dtype=float)
    service=EmbeddingService(Encoder(),['alpha','beta'])
    result=service.communicate(fixture()[2],'red',config(max_words=2))
    report=result['communication']
    packet=json.loads(json.dumps(report['message']))
    assert set(packet)=={'version','weighted','precision','components','count','model'}
    decoded=service.decode_message(packet,['planet','rocket','stone'])
    np.testing.assert_allclose(decoded['vector'],report['vectors']['encoded'])
    assert report['reconstruction_error']<1e-12
    assert report['one_shot']
    assert all(row['correct'] for row in report['simulation'])
    assert any(p['type']=='ideal' for p in report['plot']['points'])
    assert not any(p['type']=='ideal' for p in result['plot']['points'])
    packet['model']['resolved_revision']='different'
    with pytest.raises(ValueError,match='identities'):
        service.decode_message(packet,['planet'])
    json.dumps(result,allow_nan=False)


def test_projected_contributions_add_to_sum_exactly():
    _,vectors,board,bv=fixture()
    message={'weighted':True,'components':[{'word':'alpha','coefficient':.7},{'word':'beta','coefficient':.3}]}
    decoded=normalized([[.7,.3]])[0]
    plot=transmission_projection([c.word for c in board],bv,message,vectors,decoded,decoded)
    parts=plot['contributions']
    assert parts[0]['from']==[0.,0.]
    np.testing.assert_allclose(parts[0]['to'],parts[1]['from'])
    endpoint=next(p for p in plot['points'] if p['type']=='sum')
    np.testing.assert_allclose(parts[-1]['to'],[endpoint['x'],endpoint['y']])


def test_live_search_reports_provisional_best_and_depth_progress():
    updates = []
    result = search(*fixture(), 'red', config(max_words=2), progress=updates.append)
    snapshots = [u['search'] for u in updates if isinstance(u, dict)]
    assert snapshots[0]['depth'] == 1
    assert snapshots[0]['best']['coverage'] == 0
    assert snapshots[-1]['depth'] == 2
    assert snapshots[-1]['best'] == result['best']
    assert snapshots[-1]['evaluations'] == result['evaluations']
    assert len(snapshots[0]['trace']) == 1  # Earlier snapshots don't mutate.
    json.dumps(snapshots, allow_nan=False)
