namespace Mos.Recorder;
public sealed record CaptureContext(string Server, string PhysicianId, string VisitId, string RecordingId, string ConsentSha256, DateTimeOffset StartedAt);
// Reported workstation metadata deliberately lives outside CaptureContext: the
// authenticated .4baudio container and existing files keep their original shape.
public sealed record CaptureOrigin(string RoomCode,string DeviceId,string ClientSessionId)
{
    public static bool ValidRoomCode(string? value)=>value is {Length:>=1 and <=80} && value.All(c=>char.IsAsciiLetterOrDigit(c) || c is '_' or '.' or '-');
    public static bool CanonicalUuid(string? value)=>Guid.TryParseExact(value,"D",out var id) && id.ToString("D")==value;
    public CaptureOrigin Validate()
    {
        if(!ValidRoomCode(RoomCode) || !CanonicalUuid(DeviceId) || !CanonicalUuid(ClientSessionId))throw new InvalidDataException("Invalid reported recording origin.");
        return this;
    }
}
public sealed record CaptureSummary(long PcmBytes, string PcmSha256, string Reason, bool Complete);
public sealed record CaptureResult(string FilePath, long PcmBytes, string EncryptedFileSha256, string Reason);
public sealed record PendingCapture(CaptureContext Context, string StartRequestKey, string? FinishRequestKey, string? FilePath, long PcmBytes, string? EncryptedFileSha256, string? Reason, int? FinishVersion = null,CaptureOrigin? CaptureOrigin = null);
public static class CaptureCommands
{
    public static Dictionary<string,object?> Start(PendingCapture capture,int expectedVersion)
    {
        if(expectedVersion<0)throw new ArgumentOutOfRangeException(nameof(expectedVersion));
        var command=new Dictionary<string,object?>{
            ["recording_id"]=capture.Context.RecordingId,["expected_version"]=expectedVersion,
            ["request_key"]=capture.StartRequestKey,["expected_consent_sha256"]=capture.Context.ConsentSha256,
        };
        // Null must remain absent for exact retries of legacy start commands.
        if(capture.CaptureOrigin is { } origin)command["capture_origin"]=origin.Validate();
        return command;
    }
}
public interface IKeyProtector { byte[] Protect(byte[] data); byte[] Unprotect(byte[] data); }
