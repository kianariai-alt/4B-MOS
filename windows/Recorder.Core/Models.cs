namespace Mos.Recorder;
public sealed record CaptureContext(string Server, string PhysicianId, string VisitId, string RecordingId, string ConsentSha256, DateTimeOffset StartedAt);
public sealed record CaptureSummary(long PcmBytes, string PcmSha256, string Reason, bool Complete);
public sealed record CaptureResult(string FilePath, long PcmBytes, string EncryptedFileSha256, string Reason);
public sealed record PendingCapture(CaptureContext Context, string StartRequestKey, string? FinishRequestKey, string? FilePath, long PcmBytes, string? EncryptedFileSha256, string? Reason, int? FinishVersion = null);
public interface IKeyProtector { byte[] Protect(byte[] data); byte[] Unprotect(byte[] data); }
