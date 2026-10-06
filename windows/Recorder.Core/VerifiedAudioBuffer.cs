using System.Security.Cryptography;
namespace Mos.Recorder;

// Decrypt only a fully authenticated, completed capture; never create a WAV file.
public sealed class VerifiedAudioBuffer : IDisposable
{
    private byte[]? _pcm;
    private MemoryStream? _stream;
    private VerifiedAudioBuffer(byte[] pcm) => _pcm=pcm;
    public TimeSpan Duration => TimeSpan.FromSeconds((_pcm ?? throw new ObjectDisposedException(nameof(VerifiedAudioBuffer))).Length/32000.0);
    public Stream OpenRead()
    {
        if(_stream is not null)throw new InvalidOperationException("Playback stream already opened.");
        _stream=new MemoryStream(_pcm ?? throw new ObjectDisposedException(nameof(VerifiedAudioBuffer)),writable:false);
        return _stream;
    }
    public static VerifiedAudioBuffer Load(PendingCapture item,string server,string physicianId,IKeyProtector protector)
    {
        if(item.Context.Server!=server || item.Context.PhysicianId!=physicianId || item.FilePath is null || item.Reason!="finished" || item.PcmBytes<=0 || item.PcmBytes>57600000 || item.PcmBytes%2!=0)
            throw new InvalidDataException("Capture not eligible for playback.");
        using var locked=new FileStream(item.FilePath,FileMode.Open,FileAccess.Read,FileShare.Read);
        if(Convert.ToHexString(SHA256.HashData(locked)).ToLowerInvariant()!=item.EncryptedFileSha256)
            throw new InvalidDataException("Capture checksum mismatch.");
        byte[] pcm=new byte[checked((int)item.PcmBytes)];int used=0;
        try{
            var verified=EncryptedCapture.Verify(item.FilePath,protector,frame=>{
                if(frame.Length>pcm.Length-used)throw new InvalidDataException("Capture exceeds declared length.");
                frame.CopyTo(pcm,used);used+=frame.Length;
            });
            if(verified.Context!=item.Context || !verified.Summary.Complete || verified.Summary.Reason!="finished" || verified.Summary.PcmBytes!=item.PcmBytes || used!=pcm.Length)
                throw new InvalidDataException("Capture context or length mismatch.");
            return new VerifiedAudioBuffer(pcm);
        }catch{CryptographicOperations.ZeroMemory(pcm);throw;}
    }
    public void Dispose()
    {
        _stream?.Dispose();_stream=null;
        if(_pcm is { } pcm){CryptographicOperations.ZeroMemory(pcm);_pcm=null;}
    }
}
