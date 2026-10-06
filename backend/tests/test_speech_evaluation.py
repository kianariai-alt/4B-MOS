"""Independent distance oracle, Persian normalization and report privacy."""
import itertools
import json
import pytest
from pydantic import ValidationError
from backend.app.services.speech_evaluation import compare_text,edit_distance,tokens,MAX_TEXT_CHARACTERS
from backend.app.schemas.speech_evaluation import BenchmarkDataset
from backend.tools.speech_evaluation import evaluate,main


def oracle(left,right):
    row=list(range(len(right)+1))
    for i,a in enumerate(left,1):
        next_row=[i]
        for j,b in enumerate(right,1):
            next_row.append(min(next_row[-1]+1,row[j]+1,row[j-1]+(a!=b)))
        row=next_row
    return row[-1]


def dataset(**changes):
    return dict(dataset_id='synthetic-eval',dataset_kind='synthetic',authorized_for_evaluation=True,
                cases=[dict(case_id='synthetic-001',category='numbers',reference_verified=True,
                            reference='داروی الف ۵ واحد',candidate='داروی الف ۱۰ واحد',protected_phrases=['داروی الف'])],**changes)


def test_exact_edit_distance_against_independent_oracle():
    sequences=[p for size in range(5) for p in itertools.product(('a','b'),repeat=size)]
    for left in sequences:
        for right in sequences:
            assert edit_distance(left,right)==oracle(left,right)
    assert edit_distance(['one']*300,['one']*299+['two'])==1


def test_persian_letters_digits_marks_and_punctuation():
    result=compare_text('كِتاب شماره ١٢، مي\u200cروم','کتاب شماره ۱۲ می روم')
    assert result['word_edit_distance']==0
    assert result['character_edit_distance']==0
    assert result['numeric_sequence_changed'] is False
    assert result['clinical_accuracy_established'] is False
    assert compare_text('۱۲٫۵ واحد','12.5 واحد')['word_edit_distance']==0
    assert compare_text('۱٬۲۰۰ واحد','1200 واحد')['word_edit_distance']==0


def test_numbers_order_duplicates_sign_and_negation_remain_visible():
    result=compare_text('۵ واحد نیست','۱۰ واحد است',('نیست',))
    assert result['word_edit_distance']==2
    assert result['numeric_tokens_missing']==result['numeric_tokens_added']==1
    assert result['protected_phrase_count_changes']==1
    assert result['requires_source_audio_review'] is True
    assert compare_text('۵ و ۱۰','۱۰ و ۵')['numeric_sequence_changed'] is True
    assert compare_text('۵ و ۵','۵')['numeric_tokens_missing']==1
    assert compare_text('-۵','۵')['numeric_sequence_changed'] is True


def test_rates_can_exceed_one_and_empty_reference_is_undefined():
    assert compare_text('یک','یک دو سه چهار')['word_edit_rate']==3
    assert compare_text('یک دو','')['word_edit_rate']==1
    assert compare_text('','سه')['word_edit_rate'] is None
    assert compare_text('','سه')['character_edit_rate'] is None


def test_protected_phrase_must_be_present_and_matches_whole_tokens():
    with pytest.raises(ValueError,match='absent'):compare_text('متن مرجع','متن',('نیست',))
    result=compare_text('نیست', 'نیستم', ('نیست',))
    assert result['protected_phrase_count_changes']==1
    with pytest.raises(ValueError,match='limit'):tokens('ا'*(MAX_TEXT_CHARACTERS+1))


def test_weighted_report_counts_and_no_text_exports():
    raw=dataset();raw['cases'].append(dict(case_id='synthetic-002',category='general',reference_verified=True,reference='یک دو سه چهار',candidate='یک دو سه چهار'))
    report=evaluate(BenchmarkDataset(**raw))
    assert report['summary']['word_edit_rate']==1/8
    output=json.dumps(report,ensure_ascii=False)
    assert 'داروی' not in output and 'الف' not in output
    assert report['model_inference_performed'] is report['release_approved'] is False
    assert report['sample_count']==2

@pytest.mark.parametrize('field,value',[('authorized_for_evaluation',False),('dataset_kind','unapproved_real_visits')])
def test_unapproved_input_rejected(field,value):
    raw=dataset();raw[field]=value
    with pytest.raises(ValidationError):BenchmarkDataset(**raw)


def test_duplicate_cases_and_unverified_reference_rejected():
    raw=dataset();raw['cases']*=2
    with pytest.raises(ValidationError):BenchmarkDataset(**raw)
    raw=dataset();raw['cases'][0]['reference_verified']=False
    with pytest.raises(ValidationError):BenchmarkDataset(**raw)


def test_cli_success_preserves_source_and_refuses_overwrite(tmp_path,capsys):
    source=tmp_path/'input.json';output=tmp_path/'result.json'
    source.write_text(json.dumps(dataset()),encoding='utf-8')
    before=source.read_bytes()
    main([str(source),'--output',str(output)])
    assert json.loads(output.read_text())['summary']['numeric_change_cases']==1
    with pytest.raises(SystemExit):main([str(source),'--output',str(source)])
    with pytest.raises(SystemExit):main([str(source),'--output',str(output)])
    assert source.read_bytes()==before
    assert 'داروی' not in capsys.readouterr().out


def test_cli_validation_never_echoes_sensitive_input(tmp_path,capsys):
    source=tmp_path/'invalid.json';source.write_text('{"patient_secret":"PRIVATE-SYNTHETIC-MARKER"}')
    with pytest.raises(SystemExit):main([str(source),'--output',str(tmp_path/'result.json')])
    captured=capsys.readouterr()
    assert 'PRIVATE-SYNTHETIC-MARKER' not in captured.err+captured.out
    assert not (tmp_path/'result.json').exists()
