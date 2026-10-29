using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Unicode;

namespace Mos.Recorder;

public static class RecorderDeviceIdentity
{
    public static string LoadOrCreate(string root)
    {
        Directory.CreateDirectory(root);
        string path=Path.Combine(root,"device-id.txt");
        if(File.Exists(path))return Read(path);
        string id=Guid.NewGuid().ToString("D");
        try{
            using var stream=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None);
            byte[] bytes=Encoding.UTF8.GetBytes(id);stream.Write(bytes);stream.Flush(true);
            return id;
        }catch(IOException) when(File.Exists(path)){return Read(path);}
    }
    private static string Read(string path)
    {
        if(new FileInfo(path).Length!=36)throw new InvalidDataException("Stored device identifier is invalid; it was not replaced.");
        string id=File.ReadAllText(path,Encoding.UTF8);
        if(!CaptureOrigin.CanonicalUuid(id))throw new InvalidDataException("Stored device identifier is invalid; it was not replaced.");
        return id;
    }
}

public sealed record ReviewedTranscriptFile(
    string VisitId,string RecordingId,CaptureOrigin? CaptureOrigin,string SourceReviewSha256,
    string ReviewedText,string TextSha256)
{
    public string SchemaId=>"4b-mos.reviewed-transcript-file";
    public string SchemaVersion=>"1.0.0";
    public string SourceType=>"server_reviewed_transcript";
    public byte[] ToUtf8Json()=>JsonSerializer.SerializeToUtf8Bytes(this,new JsonSerializerOptions{
        PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,WriteIndented=true,
        Encoder=JavaScriptEncoder.Create(UnicodeRanges.All),
    });
}

public static class TranscriptHandoff
{
    private static bool Digest(string? value)=>value is {Length:64} && value.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static (string DraftSha,string ReviewSha,string Text,int Version) Snapshot(JsonElement workspace,string recordingId,string physicianId)
    {
        if(workspace.GetProperty("recording_id").GetString()!=recordingId || workspace.GetProperty("state").GetString()!="reviewed")throw new InvalidDataException("The reviewed source is not ready for this recording.");
        int version=workspace.GetProperty("version").GetInt32();
        var draft=workspace.GetProperty("latest_draft");var review=workspace.GetProperty("latest_review");
        if(version<1 || draft.ValueKind!=JsonValueKind.Object || review.ValueKind!=JsonValueKind.Object)throw new InvalidDataException("A saved draft and physician review are required.");
        string? draftSha=draft.GetProperty("sha256").GetString(),reviewSha=review.GetProperty("sha256").GetString();
        if(!Digest(draftSha) || !Digest(reviewSha) || review.GetProperty("draft_sha256").GetString()!=draftSha
            || !review.GetProperty("reviewed_by_physician").GetBoolean() || review.GetProperty("recorded_by").GetString()!=physicianId)throw new InvalidDataException("The review does not bind the current draft and physician.");
        string text=review.GetProperty("edited_text").GetString() ?? "";
        if(string.IsNullOrWhiteSpace(text) || text.Length>200000)throw new InvalidDataException("Saved reviewed text is missing or oversized.");
        return(draftSha!,reviewSha!,text,version);
    }

    public static ReviewedTranscriptFile Create(PendingCapture capture,string server,string physicianId,
        JsonElement displayedWorkspace,JsonElement freshlyAuthorizedWorkspace,string editorText)
    {
        if(capture.Context.Server!=server || capture.Context.PhysicianId!=physicianId || capture.Reason!="finished"
            || !CaptureOrigin.CanonicalUuid(capture.Context.VisitId) || !CaptureOrigin.CanonicalUuid(capture.Context.RecordingId))throw new InvalidDataException("Wrong source account or capture.");
        var displayed=Snapshot(displayedWorkspace,capture.Context.RecordingId,physicianId);
        var fresh=Snapshot(freshlyAuthorizedWorkspace,capture.Context.RecordingId,physicianId);
        if(displayed!=fresh || editorText!=fresh.Text)throw new InvalidDataException("The saved review or editor changed; reload it before export.");
        capture.CaptureOrigin?.Validate();
        string sha=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(fresh.Text))).ToLowerInvariant();
        return new ReviewedTranscriptFile(capture.Context.VisitId,capture.Context.RecordingId,capture.CaptureOrigin,
            fresh.ReviewSha,fresh.Text,sha);
    }
}
