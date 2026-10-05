using System.Security.Cryptography;
using System.Text.Json;
namespace Mos.Recorder;
public static class AudioUploader
{
    public static string MediaPath(CaptureContext context)=>MosClient.VisitPath(context.VisitId)+"/"+Guid.Parse(context.RecordingId).ToString("D")+"/media";
    public static async Task<JsonElement> Upload(MosClient client,PendingCapture item,IKeyProtector protector)
    {
        if(item.Context.Server!=client.Server || item.Context.PhysicianId!=client.UserId || item.FilePath is null || item.Reason!="finished")throw new InvalidDataException("Capture not eligible.");
        // Keep one file handle locked against modification during both passes.
        using var locked=new FileStream(item.FilePath,FileMode.Open,FileAccess.Read,FileShare.Read);
        string fileSha=Convert.ToHexString(SHA256.HashData(locked)).ToLowerInvariant();
        if(fileSha!=item.EncryptedFileSha256)throw new InvalidDataException("Capture checksum mismatch.");
        var verified=await Task.Run(()=>EncryptedCapture.Verify(item.FilePath,protector));
        if(verified.Context!=item.Context || verified.Summary.Reason!="finished" || verified.Summary.PcmBytes!=item.PcmBytes || item.PcmBytes<=0 || item.PcmBytes>57600000)throw new InvalidDataException("Capture context or size mismatch.");
        string path=MediaPath(item.Context);
        var status=await client.Post(path+"/initialize",new{request_key=item.Context.RecordingId+".audio-init",pcm_bytes=item.PcmBytes,pcm_sha256=verified.Summary.PcmSha256,encrypted_file_sha256=fileSha});
        if(status.GetProperty("audio_received").GetBoolean())return status;
        const int size=262144;
        if(status.GetProperty("chunk_bytes").GetInt32()!=size)throw new InvalidDataException("Unsupported chunk size.");
        int next=status.GetProperty("next_chunk_index").GetInt32();
        await Task.Run(()=>{
            byte[] chunk=new byte[size];int used=0,index=0;
            void Send(){
                if(index>=next){byte[] data=chunk.AsSpan(0,used).ToArray();
                    try{client.PutPcm(path+"/chunks/"+index,data,Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant()).GetAwaiter().GetResult();}
                    finally{CryptographicOperations.ZeroMemory(data);}}
                index++;used=0;CryptographicOperations.ZeroMemory(chunk);
            }
            try{
                EncryptedCapture.Verify(item.FilePath,protector,frame=>{
                    int offset=0;
                    while(offset<frame.Length){int count=Math.Min(size-used,frame.Length-offset);frame.AsSpan(offset,count).CopyTo(chunk.AsSpan(used));used+=count;offset+=count;if(used==size)Send();}
                });
                if(used>0)Send();
            }finally{CryptographicOperations.ZeroMemory(chunk);}
        });
        return await client.Post(path+"/complete",new{request_key=item.Context.RecordingId+".audio-complete",expected_pcm_sha256=verified.Summary.PcmSha256});
    }
}
