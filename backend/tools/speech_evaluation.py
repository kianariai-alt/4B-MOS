"""Offline comparison; JSON output contains counts and hashes, never transcripts."""
import argparse
import json
from pathlib import Path
from pydantic import ValidationError
from backend.app.schemas.speech_evaluation import BenchmarkDataset
from backend.app.services.speech_evaluation import compare_text

MAX_INPUT_BYTES = 24 * 1024 * 1024


def evaluate(dataset: BenchmarkDataset) -> dict:
    rows = [dict(case_id=c.case_id, category=c.category,
                 comparison=compare_text(c.reference, c.candidate, c.protected_phrases))
            for c in dataset.cases]
    metrics = [r['comparison'] for r in rows]
    words = sum(m['reference_words'] for m in metrics)
    chars = sum(m['reference_characters'] for m in metrics)
    word_edits = sum(m['word_edit_distance'] for m in metrics)
    char_edits = sum(m['character_edit_distance'] for m in metrics)
    return {
        'dataset_id': dataset.dataset_id, 'dataset_kind': dataset.dataset_kind,
        'comparison_kind': 'reference_text_comparison',
        'sample_count': len(rows),
        'summary': dict(reference_words=words, word_edit_distance=word_edits,
                        word_edit_rate=word_edits / words if words else None,
                        reference_characters=chars, character_edit_distance=char_edits,
                        character_edit_rate=char_edits / chars if chars else None,
                        numeric_change_cases=sum(m['numeric_sequence_changed'] for m in metrics),
                        protected_phrase_change_cases=sum(bool(m['protected_phrase_count_changes']) for m in metrics),
                        audio_review_cases=sum(m['requires_source_audio_review'] for m in metrics)),
        'clinical_accuracy_established': False, 'model_inference_performed': False,
        'release_approved': False, 'training_performed': False, 'cases': rows,
    }


def load_dataset(path):
    # Bound actual reads too, in case the file changes after opening.
    with Path(path).open('rb') as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise ValueError('Benchmark input exceeds its size limit.')
    return BenchmarkDataset.model_validate_json(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare approved benchmark texts; no model inference.')
    parser.add_argument('dataset')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    source, output = Path(args.dataset).resolve(), Path(args.output).resolve()
    if source == output:
        parser.error('Input and output must be different files.')
    try:
        report = evaluate(load_dataset(source))
    except (OSError, ValueError, ValidationError):
        # Validation errors may embed input text. Never print them.
        parser.exit(2, 'Evaluation failed: verify dataset structure, authorization and size limits.\n')
    try:
        # Refuse replacement of existing reports, input hardlinks or symlinks.
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except OSError:
        parser.exit(2, 'Report was not saved: choose a new writable output path.\n')
    print('Text comparison report saved. No model inference or clinical validation performed.')


if __name__ == '__main__':
    main()
