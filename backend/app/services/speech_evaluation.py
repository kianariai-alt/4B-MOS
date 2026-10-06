"""Text comparison only. A revision distance is not clinical speech accuracy."""
from collections import Counter
import hashlib
import re
import unicodedata

NORMALIZATION_VERSION = 'fa-text-v1'
MAX_TEXT_CHARACTERS = 50000
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
_LETTERS = str.maketrans({'ي': 'ی', 'ى': 'ی', 'ك': 'ک', '\u200c': ' ', '\u0640': '', '٫': '.'})
_WORDS = re.compile(r'[-+]?\d+(?:[./]\d+)*|[^\W\d_]+', re.UNICODE)
_NUMBERS = re.compile(r'[-+]?\d+(?:[./]\d+)*\Z')
_DIACRITICS = re.compile('[\u064b-\u065f\u0670]')


def tokens(value: str) -> list[str]:
    if len(value) > MAX_TEXT_CHARACTERS:
        raise ValueError('Text comparison limit exceeded.')
    normalized = unicodedata.normalize('NFKC', value).translate(_DIGITS).translate(_LETTERS)
    if len(normalized) > MAX_TEXT_CHARACTERS:
        raise ValueError('Normalized text comparison limit exceeded.')
    normalized = re.sub(r'(?<=\d)٬(?=\d)', '', normalized)
    return _WORDS.findall(_DIACRITICS.sub('', normalized).casefold())


def edit_distance(reference, candidate) -> int:
    """Exact Levenshtein distance using bounded arbitrary-precision bit vectors."""
    if len(reference) > len(candidate):
        reference, candidate = candidate, reference
    width = len(reference)
    if not width:
        return len(candidate)
    masks = {}
    for index, token in enumerate(reference):
        masks[token] = masks.get(token, 0) | (1 << index)
    mask = (1 << width) - 1
    high_bit = 1 << (width - 1)
    positive, negative, distance = mask, 0, width
    for token in candidate:
        equal = masks.get(token, 0)
        vertical = equal | negative
        horizontal = (((equal & positive) + positive) ^ positive) | equal
        plus = negative | ~(horizontal | positive)
        minus = positive & horizontal
        if plus & high_bit:
            distance += 1
        elif minus & high_bit:
            distance -= 1
        plus, minus = (plus << 1) | 1, minus << 1
        positive = (minus | ~(vertical | plus)) & mask
        negative = plus & vertical & mask
    return distance


def _occurrences(sequence, phrase):
    return sum(sequence[i:i + len(phrase)] == phrase for i in range(len(sequence) - len(phrase) + 1))


def compare_text(reference: str, candidate: str, protected_phrases=()) -> dict:
    """Return counts only: no source text, normalized tokens or sensitive phrases."""
    ref, hyp = tokens(reference), tokens(candidate)
    ref_characters, hyp_characters = ''.join(ref), ''.join(hyp)
    word_edits = edit_distance(ref, hyp)
    character_edits = edit_distance(ref_characters, hyp_characters)
    ref_numbers = [t for t in ref if _NUMBERS.fullmatch(t)]
    hyp_numbers = [t for t in hyp if _NUMBERS.fullmatch(t)]
    changes = 0
    for phrase in protected_phrases:
        term = tokens(phrase)
        if not term or not _occurrences(ref, term):
            raise ValueError('Protected phrase is absent from its reference.')
        changes += _occurrences(ref, term) != _occurrences(hyp, term)
    missing = sum((Counter(ref_numbers) - Counter(hyp_numbers)).values())
    added = sum((Counter(hyp_numbers) - Counter(ref_numbers)).values())
    return {
        'normalization_version': NORMALIZATION_VERSION,
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'candidate_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
        'reference_words': len(ref), 'candidate_words': len(hyp),
        'word_edit_distance': word_edits,
        'word_edit_rate': word_edits / len(ref) if ref else None,
        'reference_characters': len(ref_characters), 'candidate_characters': len(hyp_characters),
        'character_edit_distance': character_edits,
        'character_edit_rate': character_edits / len(ref_characters) if ref_characters else None,
        'numeric_sequence_changed': ref_numbers != hyp_numbers,
        'numeric_tokens_missing': missing, 'numeric_tokens_added': added,
        'protected_phrases_checked': len(protected_phrases),
        'protected_phrase_count_changes': changes,
        'requires_source_audio_review': bool(word_edits or changes),
        'clinical_accuracy_established': False,
        'authorizes_diagnosis': False, 'training_performed': False,
    }
