# Generate embeddings in Google Colab

1. Open https://colab.research.google.com/ and upload `Generate_Gemma_Embeddings.ipynb` using **File → Upload notebook**.
2. Select **Runtime → Change runtime type → GPU**.
3. Run the notebook cells in order. Upload `gemma_colab_bundle.zip` when prompted. If needed, configure `HF_TOKEN` using Colab Secrets; never paste it into notebook code.
4. The generation cell embeds the union of both CSV vocabularies. Watch its batch progress and ETA. If GPU memory runs out, reduce `BATCH_SIZE` from 128 to 64 or 32 and rerun; completed batches remain cached.
5. Download `gemma_embeddings.npz`, then disconnect/delete the Colab runtime to stop consuming GPU compute.
6. Put the file in your project's `.cache/` folder and add this line to `.env`:

   ```sh
   GEMMA_EMBEDDINGS_FILE=.cache/gemma_embeddings.npz
   ```

7. Restart with `./run.sh`. Choose real Gemma in the laboratory. The backend uses the downloaded file directly without loading the model or importing Torch.

The file contains words, normalized float32 vectors, the exact model revision, and STS prompt metadata. Model identity is preserved across the encoder and decoder. Words missing from the export are computed locally on demand with the same pinned model revision and STS prompt, then saved to `.cache/live_embeddings/words.sqlite3`. This includes valid human clues outside the exported pool. Only a genuine cache miss loads Gemma; that first load requires model dependencies and may download weights. Existing file and cached vectors work without loading Gemma. You can also extend the portable file on Colab (see below). You can remove words from the CSV without regenerating it.

The notebook includes optional checkpoint download/restore cells for completed batches. Interrupt a long generation cell before saving a checkpoint. Colab runtime resets delete local files, so download the checkpoint before discarding a runtime. Cache reuse requires the same model revision and software/encoding metadata. This checkpoint is optional; only the final NPZ is required by the game.

## Refresh the upload bundle

The supplied ZIP is a snapshot of the current CSVs and minimal Python exporter. It contains no `.env`, credentials, model weights, or unrelated project files. After editing the CSVs or exporter, run from the project directory:

```sh
python3 colab/prepare_bundle.py
```

Default included paths are `gemma_codenames/data/board_words.csv` and `gemma_codenames/data/clue_words.csv`; environment overrides on your Mac do not change this bundle. Put any intended custom vocabulary into those files before rebuilding, or adjust the bundle and notebook paths together.

## Validation performed locally

Notebook code cells compile, bundle contents match the source files, and tests exercise file validation, model/revision mismatch, missing words, and a full encode/decode game calculation without loading Gemma. Actual Colab GPU execution requires your account/runtime and has not been performed here. Installation and GPU availability can vary; there is no guaranteed completion time or GPU allocation.

## Incremental updates

Reuse an existing NPZ to encode only words it lacks. Run from the project root with model dependencies installed:

```sh
.venv/bin/python -m gemma_codenames.export_embeddings \
  --board gemma_codenames/data/board_words.csv \
  --clues gemma_codenames/data/clue_words.csv \
  --extra-words gemma_codenames/data/clue_words_common.csv \
  --existing .cache/gemma_embeddings.npz \
  --output .cache/gemma_embeddings_updated.npz \
  --device cpu --batch-size 16 --offline
```

`--offline` requires cached weights; omit it to allow model downloading. In Colab, upload the existing NPZ and use `--device cuda` with the appropriate paths. `--extra-words` is optional and includes all entries, even words excluded by the clue legality filter. This local example covers `good-bye` too. The default ZIP contains the full clue CSV; upload the common CSV separately if using that optional argument in Colab.

The updater preserves existing words, pins the original model commit, checks dimensions and encoding settings, and writes the output atomically. Existing legacy exports with a session identifier can be extended only if they also record a pinned requested commit. New exports record that commit as their resolved identity. New vectors use the same normalized STS prompt. Repeating the update with an already-complete file performs no model inference.

Keep the original as a backup, point `GEMMA_EMBEDDINGS_FILE` at the validated output, and restart the server. Incremental vectors may be generated on CPU even when the original file was produced on GPU.
