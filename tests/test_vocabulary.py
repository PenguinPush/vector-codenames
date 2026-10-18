import pytest
from gemma_codenames.board import Card, load_words, random_board
from gemma_codenames.optimizer import CluePolicy


def test_csv_supports_board_phrases_and_ignores_extra_metadata(tmp_path):
    path=tmp_path/'words.csv'
    path.write_text('\ufeffword,category\n"Big Bang",space\nMoon,space\nmoon,duplicate\nSt.Patrick,name\n',encoding='utf-8')
    assert load_words(path)==['big bang','moon','st.patrick']
    assert load_words(path,clues=True)==['moon']


def test_malformed_csv_does_not_silently_become_word_data(tmp_path):
    path=tmp_path/'words.csv'
    path.write_text('term\nmoon\n')
    with pytest.raises(ValueError,match="word.*column"):
        load_words(path)
    path.write_text('word\nmoon,planet\n')
    with pytest.raises(ValueError,match='Malformed'):
        load_words(path)


def test_board_phrase_components_and_inflections_are_illegal_clues():
    policy=CluePolicy([Card('Big Bang','red'),Card('ice cream','blue')])
    for word in ['big','bang','bangs','ice','cream','creams']:
        assert not policy.allows(word)
    assert policy.allows('cosmos')


def test_default_pools_are_independent_and_board_generation_accepts_phrases():
    board=load_words();clues=load_words(clues=True)
    assert board and clues and set(board) != set(clues)
    assert len(random_board(board,42))==25


def test_clue_dictionary_accepts_single_letters_and_warns_about_filtered_entries(tmp_path, caplog):
    path = tmp_path / 'dictionary.csv'
    path.write_text("word\na\ni\nA\na-line\na'man\nriver\ntwo words\n123\n")
    assert load_words(path, clues=True) == ['a', 'i', 'river']
    assert 'Skipped 4 unsupported clue entries' in caplog.text
    assert CluePolicy([Card('moon', 'red')]).allows('a')
    path.write_text('word\ntwo words\n')
    with pytest.raises(ValueError, match='no supported entries'):
        load_words(path, clues=True)


@pytest.mark.parametrize('size,counts', [(9, (4,3,1,1)), (16, (6,5,4,1)), (25, (9,8,7,1))])
def test_configurable_board_sizes(size, counts):
    cards = random_board(load_words(), 42, size=size)
    assert len(cards) == len({c.word for c in cards}) == size
    assert tuple(sum(c.kind == k for c in cards) for k in ('red','blue','neutral','assassin')) == counts
    assert cards == random_board(load_words(), 42, size=size)
    with pytest.raises(ValueError):
        random_board(load_words(), 42, size=10)


def test_every_common_csv_entry_exists_in_full_csv():
    import csv
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'gemma_codenames/data'
    def entries(name):
        with (root / name).open() as stream:
            return {row['word'].strip().lower() for row in csv.DictReader(stream)}
    assert entries('clue_words_common.csv') <= entries('clue_words.csv')


@pytest.mark.parametrize('n', range(2, 11))
def test_any_supported_square_board(n):
    cards = random_board(load_words(), 42, size=n*n)
    assert len(cards) == len({c.word for c in cards}) == n*n
    assert sum(c.kind == 'assassin' for c in cards) == 1
    assert sum(c.kind == 'red' for c in cards) == sum(c.kind == 'blue' for c in cards) + 1
    from gemma_codenames.board import validate_board
    validate_board(cards, 'red')


@pytest.mark.parametrize('size', [0, 1, 8, 26, 121, 25.0, True])
def test_invalid_square_sizes_are_rejected(size):
    with pytest.raises(ValueError):
        random_board(load_words(), 42, size=size)


def test_punctuated_clues_preserve_board_word_and_inflection_exclusion():
    policy = CluePolicy([Card('ice', 'red'), Card('cat', 'blue')])
    for clue in ['ice-cream', "cat's", 'cats-eye']:
        assert not policy.allows(clue)
    assert not policy.allows('about-face')
    assert not policy.allows("a'man")


def test_current_full_clue_csv_skips_punctuated_entries(caplog):
    load_words(clues=True)
    assert 'Skipped 1054 unsupported clue entries' in caplog.text
