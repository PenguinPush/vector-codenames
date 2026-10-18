"""Refresh the upload bundle after changing either vocabulary CSV."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'gemma_codenames/__init__.py',
    'gemma_codenames/board.py',
    'gemma_codenames/embeddings.py',
    'gemma_codenames/precomputed.py',
    'gemma_codenames/export_embeddings.py',
    'gemma_codenames/data/board_words.csv',
    'gemma_codenames/data/clue_words.csv',
]

if __name__ == '__main__':
    destination = ROOT / 'colab/gemma_colab_bundle.zip'
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
    print(f'Prepared {destination} ({destination.stat().st_size:,} bytes). No credentials included.')
