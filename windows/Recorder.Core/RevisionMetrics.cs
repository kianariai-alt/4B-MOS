using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
namespace Mos.Recorder;

// Only a comparison of the exact saved pair may be shown. No transcript is
// retained here and no score is described as clinical recognition accuracy.
public sealed record RevisionMetrics(int WordEdits,int ReferenceWords,int CharacterEdits,int ReferenceCharacters,
    bool NumericSequenceChanged,int MissingNumbers,int AddedNumbers)
{
    public static RevisionMetrics Parse(JsonElement response,string recordingId,string draftSha,string reviewSha,
        string reviewedText,string draftText)
    {
        try {
            static void Require(bool condition){if(!condition)throw new InvalidDataException("Invalid revision report.");}
            Require(response.GetProperty("recording_id").GetString()==recordingId);
            Require(response.GetProperty("draft_sha256").GetString()==draftSha && response.GetProperty("review_sha256").GetString()==reviewSha);
            Require(response.GetProperty("comparison_kind").GetString()=="physician_revision_distance");
            Require(!response.GetProperty("reference_verified_against_audio").GetBoolean());
            var data=response.GetProperty("comparison");
            Require(data.GetProperty("normalization_version").GetString()=="fa-text-v1");
            foreach(string flag in new[]{"clinical_accuracy_established","authorizes_diagnosis","training_performed"})Require(!data.GetProperty(flag).GetBoolean());
            static string Sha(string value)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
            Require(data.GetProperty("reference_sha256").GetString()==Sha(reviewedText) && data.GetProperty("candidate_sha256").GetString()==Sha(draftText));
            int Read(string name){int number=data.GetProperty(name).GetInt32();Require(number>=0 && number<=100000);return number;}
            int words=Read("reference_words"),wordEdits=Read("word_edit_distance"),characters=Read("reference_characters"),characterEdits=Read("character_edit_distance");
            void Rate(string name,int edits,int count){
                var value=data.GetProperty(name);
                if(count==0){Require(value.ValueKind==JsonValueKind.Null);return;}
                double rate=value.GetDouble();Require(double.IsFinite(rate) && Math.Abs(rate-(double)edits/count)<1e-9);
            }
            Rate("word_edit_rate",wordEdits,words);Rate("character_edit_rate",characterEdits,characters);
            return new(wordEdits,words,characterEdits,characters,data.GetProperty("numeric_sequence_changed").GetBoolean(),Read("numeric_tokens_missing"),Read("numeric_tokens_added"));
        }catch(Exception error) when(error is KeyNotFoundException or InvalidOperationException or FormatException or OverflowException){
            throw new InvalidDataException("Invalid revision report.",error);
        }
    }
    private static string Rate(int edits,int count)=>count==0?"قابل محاسبه نیست":((double)edits/count).ToString("P1",CultureInfo.GetCultureInfo("fa-IR"));
    public string SummaryFa=>$"تفاوت واژه‌ای: {WordEdits} ویرایش از {ReferenceWords} واژه مرجع — {Rate(WordEdits,ReferenceWords)}\nتفاوت نویسه‌ای: {CharacterEdits} ویرایش از {ReferenceCharacters} نویسه مرجع — {Rate(CharacterEdits,ReferenceCharacters)}\nتغییر توالی اعداد: {(NumericSequenceChanged?"دارد؛ با صوت تطبیق دهید":"مشاهده نشد")}\nاعداد مرجع غایب از پیش‌نویس: {MissingNumbers} — اعداد اضافه در پیش‌نویس: {AddedNumbers}";
}
