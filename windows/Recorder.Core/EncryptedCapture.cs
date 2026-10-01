using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
namespace Mos.Recorder;

// No plaintext audio touches disk. Each frame is authenticated and bound to
// the protected header, its position, type and declared length.
public sealed class EncryptedCapture : IDisposable
{
    private const int MaxFrame = 65536;
    private static readonly byte[] Magic = Encoding.ASCII.GetBytes("4BMOSA01");
    private readonly string _path;
    private readonly FileStream _stream;
    private readonly BinaryWriter _writer;
    private readonly byte[] _key = RandomNumberGenerator.GetBytes(32);
    private readonly byte[] _headerHash;
    private readonly IncrementalHash _pcmHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    private long _sequence, _bytes;
    private bool _closed;
    private sealed record Header(CaptureContext Context, string Key);
    public long PcmBytes => _bytes;

    public EncryptedCapture(string path, CaptureContext context, IKeyProtector protector)
    {
        _path = path;
        _stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        _writer = new BinaryWriter(_stream, Encoding.UTF8, leaveOpen:true);
        try {
            byte[] plain = JsonSerializer.SerializeToUtf8Bytes(new Header(context, Convert.ToBase64String(_key)));
            byte[] header;
            try { header = protector.Protect(plain); } finally { CryptographicOperations.ZeroMemory(plain); }
            _headerHash = SHA256.HashData(header);
            _writer.Write(Magic); _writer.Write(header.Length); _writer.Write(header); _stream.Flush(true);
        } catch { _writer.Dispose(); _stream.Dispose(); CryptographicOperations.ZeroMemory(_key); throw; }
    }

    private static byte[] Aad(byte[] header, long sequence, byte type, int length)
    {
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
        writer.Write(header); writer.Write(sequence); writer.Write(type); writer.Write(length);
        return stream.ToArray();
    }

    private void Frame(byte type, byte[] plain)
    {
        byte[] nonce=RandomNumberGenerator.GetBytes(12), tag=new byte[16], cipher=new byte[plain.Length];
        using var aes=new AesGcm(_key,16);
        aes.Encrypt(nonce,plain,cipher,tag,Aad(_headerHash,_sequence,type,plain.Length));
        _writer.Write(type);_writer.Write(_sequence++);_writer.Write(plain.Length);_writer.Write(nonce);_writer.Write(tag);_writer.Write(cipher);
        _stream.Flush(true);
    }

    public void Append(byte[] pcm)
    {
        if (_closed) throw new InvalidOperationException("Capture is closed.");
        if (pcm.Length==0 || pcm.Length>MaxFrame || pcm.Length%2!=0) throw new InvalidDataException("Invalid PCM frame.");
        Frame(0,pcm); _pcmHash.AppendData(pcm); _bytes+=pcm.Length;
    }

    public CaptureResult Complete(string reason)
    {
        if (_closed) throw new InvalidOperationException("Capture is closed.");
        var summary=new CaptureSummary(_bytes,Convert.ToHexString(_pcmHash.GetHashAndReset()).ToLowerInvariant(),reason,true);
        Frame(1,JsonSerializer.SerializeToUtf8Bytes(summary)); Dispose();
        string target=Path.ChangeExtension(_path,"4baudio"); File.Move(_path,target);
        using var input=File.OpenRead(target);
        return new CaptureResult(target,_bytes,Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant(),reason);
    }

    public void Dispose()
    {
        if (_closed) return; _closed=true;
        _writer.Dispose();_stream.Dispose();_pcmHash.Dispose();CryptographicOperations.ZeroMemory(_key);
    }

    // Interrupted files can be inspected without exporting audio. A caller
    // may later stream decoded PCM directly to an authorized transcription job.
    public static (CaptureContext Context, CaptureSummary Summary) Verify(string path,IKeyProtector protector,Action<byte[]>? consume=null,bool allowInterrupted=false)
    {
        using var stream=File.OpenRead(path); using var reader=new BinaryReader(stream);
        byte[] exact(int size) {var bytes=reader.ReadBytes(size);if(bytes.Length!=size)throw new EndOfStreamException();return bytes;}
        if(!exact(8).SequenceEqual(Magic))throw new InvalidDataException("Unknown capture format.");
        int headerLength=reader.ReadInt32();if(headerLength<1 || headerLength>32768)throw new InvalidDataException("Invalid header.");
        byte[] protectedHeader=exact(headerLength),headerHash=SHA256.HashData(protectedHeader),plainHeader=protector.Unprotect(protectedHeader);
        Header header;
        try {header=JsonSerializer.Deserialize<Header>(plainHeader)??throw new InvalidDataException("Invalid context.");}
        finally {CryptographicOperations.ZeroMemory(plainHeader);}
        byte[] key=Convert.FromBase64String(header.Key);long sequence=0,bytes=0;
        using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        try {
            using var aes=new AesGcm(key,16);
            while(stream.Position<stream.Length) {
                byte type;long index;int length;byte[] nonce,tag,cipher;
                try { type=reader.ReadByte();index=reader.ReadInt64();length=reader.ReadInt32();
                    if(index!=sequence || length<1 || length>MaxFrame || type>1)throw new InvalidDataException("Invalid frame order or size.");
                    nonce=exact(12);tag=exact(16);cipher=exact(length);
                } catch(EndOfStreamException) when(allowInterrupted) {break;}
                byte[] plain=new byte[length];aes.Decrypt(nonce,cipher,tag,plain,Aad(headerHash,sequence++,type,length));
                try {
                    if(type==0) {
                        if(length%2!=0)throw new InvalidDataException("Invalid PCM.");
                        hash.AppendData(plain);bytes+=plain.Length;consume?.Invoke(plain);
                    } else {
                        var summary=JsonSerializer.Deserialize<CaptureSummary>(plain)??throw new InvalidDataException("Missing footer.");
                        string digest=Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
                        if(stream.Position!=stream.Length || !summary.Complete || summary.PcmBytes!=bytes || summary.PcmSha256!=digest)throw new InvalidDataException("Capture footer mismatch.");
                        return (header.Context,summary);
                    }
                } finally {CryptographicOperations.ZeroMemory(plain);}
            }
            if(!allowInterrupted)throw new InvalidDataException("Capture was interrupted.");
            return (header.Context,new CaptureSummary(bytes,Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant(),"interrupted",false));
        } finally {CryptographicOperations.ZeroMemory(key);}
    }
}
