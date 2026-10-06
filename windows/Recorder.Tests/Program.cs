using Mos.Recorder;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

string root=Path.Combine(Path.GetTempPath(),"4b-recorder-tests-"+Guid.NewGuid());Directory.CreateDirectory(root);
int passed=0;
void Check(bool condition,string message){if(!condition)throw new Exception(message);}
void Test(string name,Action action){action();passed++;Console.WriteLine("PASS: "+name);}
void Throws(Action action){try{action();}catch{return;}throw new Exception("Expected rejection.");}
var context=new CaptureContext("https://clinic.example/",Guid.NewGuid().ToString(),Guid.NewGuid().ToString(),Guid.NewGuid().ToString(),new string('a',64),DateTimeOffset.UtcNow);
FakeHandler.UserId=context.PhysicianId;
IKeyProtector protector=new TestProtector();
if(OperatingSystem.IsWindows())protector=new WindowsProtection();
try{
    byte[] pcm=RandomNumberGenerator.GetBytes(32000);
    CaptureResult result;
    using(var capture=new EncryptedCapture(Path.Combine(root,"sample.part"),context,protector)){capture.Append(pcm);capture.Append(pcm);result=capture.Complete("finished");}
    Test("Authenticated recording round trip",()=>{
        using var recovered=new MemoryStream();
        var verified=EncryptedCapture.Verify(result.FilePath,protector,b=>recovered.Write(b));
        Check(verified.Context==context,"Context mismatch");Check(verified.Summary.Complete && verified.Summary.PcmBytes==64000,"Summary mismatch");
        Check(recovered.ToArray().SequenceEqual(pcm.Concat(pcm)),"PCM mismatch");
    });
    Test("No plaintext PCM or context on disk",()=>{
        byte[] disk=File.ReadAllBytes(result.FilePath);
        Check(!Contains(disk,pcm.AsSpan(0,32).ToArray()),"Plain audio leaked");
        Check(!Contains(disk,Encoding.UTF8.GetBytes(context.VisitId)),"Plain context leaked");
    });
    Test("Cipher checksum matches file",()=>{
        using var input=File.OpenRead(result.FilePath);
        Check(Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant()==result.EncryptedFileSha256,"Checksum mismatch");
    });
    Test("Corrupted ciphertext rejected",()=>{
        byte[] disk=File.ReadAllBytes(result.FilePath);disk[^10]^=0x40;
        string path=Path.Combine(root,"corrupt.4baudio");File.WriteAllBytes(path,disk);
        Throws(()=>EncryptedCapture.Verify(path,protector));
    });
    Test("Removed footer is not a complete recording",()=>{
        byte[] disk=File.ReadAllBytes(result.FilePath);string path=Path.Combine(root,"truncated.4baudio");File.WriteAllBytes(path,disk[..^30]);
        Throws(()=>EncryptedCapture.Verify(path,protector));
    });
    Test("Reordered frame rejected",()=>{
        byte[] disk=File.ReadAllBytes(result.FilePath);int first=12+BitConverter.ToInt32(disk,8);disk[first+1]=1;
        string path=Path.Combine(root,"reordered.4baudio");File.WriteAllBytes(path,disk);Throws(()=>EncryptedCapture.Verify(path,protector));
    });
    Test("Interrupted capture preserves authenticated prefix",()=>{
        string part=Path.Combine(root,"interrupted.part");using(var capture=new EncryptedCapture(part,context,protector))capture.Append(pcm);
        Throws(()=>EncryptedCapture.Verify(part,protector));
        var verified=EncryptedCapture.Verify(part,protector,allowInterrupted:true);
        Check(!verified.Summary.Complete && verified.Summary.PcmBytes==32000,"Recovery failed");
        using(var append=new FileStream(part,FileMode.Append))append.WriteByte(0);
        Check(EncryptedCapture.Verify(part,protector,allowInterrupted:true).Summary.PcmBytes==32000,"Partial-tail recovery failed");
    });
    Test("Invalid PCM frame rejected",()=>{
        using var capture=new EncryptedCapture(Path.Combine(root,"invalid.part"),context,protector);
        Throws(()=>capture.Append(new byte[3]));Throws(()=>capture.Append(new byte[65538]));
    });
    Test("Journal recovery and user/clinic isolation",()=>{
        var journal=new Journal(root,context.Server,context.PhysicianId,protector);
        var pending=new PendingCapture(context,"start-key",null,result.FilePath,result.PcmBytes,result.EncryptedFileSha256,result.Reason);
        journal.Save(pending);Check(journal.Load().Single()==pending,"Journal lost data");
        var otherDoctor=new Journal(root,context.Server,Guid.NewGuid().ToString(),protector);
        var otherClinic=new Journal(root,"https://other.example/",context.PhysicianId,protector);
        Check(otherDoctor.Load().Count==0 && otherClinic.Load().Count==0,"Journal isolation failed");
        journal.Acknowledge(context.RecordingId);Check(journal.Load().Count==0,"Receipt not acknowledged");
        Check(File.Exists(result.FilePath),"Acknowledgement deleted audio");
    });
    Test("Unsafe server addresses rejected",()=>{
        foreach(string address in new[]{"http://192.168.1.2/","https://user:pass@clinic.example/","https://clinic.example/api/","https://clinic.example/?token=x","ftp://clinic.example/"})Throws(()=>MosClient.ValidateServer(address));
        Check(MosClient.ValidateServer("http://127.0.0.1:8000/").IsLoopback,"Loopback rejected");
        Check(MosClient.ValidateServer("https://clinic.example/").Scheme=="https","HTTPS rejected");
    });
    Test("Visit path cannot escape endpoint",()=>{
        Throws(()=>MosClient.VisitPath("../users"));Check(MosClient.VisitPath(context.VisitId).EndsWith("/recordings"),"Wrong visit path");
    });
    Test("Token remains in client memory and authenticated requests",()=>{
        var handler=new FakeHandler("physician");using var client=new MosClient(context.Server,handler);
        client.Login("synthetic","not-real-password").GetAwaiter().GetResult();
        Check(client.UserId==context.PhysicianId,"Wrong identity");Check(handler.Authorization=="Bearer synthetic-token","Missing token");
        Check(handler.Requests.All(uri=>uri.StartsWith(context.Server+"api/v1/")),"Wrong server");
    });
    Test("Non-physician login rejected",()=>{
        using var client=new MosClient(context.Server,new FakeHandler("operator"));Throws(()=>client.Login("synthetic","synthetic").GetAwaiter().GetResult());
        Check(client.UserId is null,"Unauthorized identity retained");
    });
    Test("Completed recordings remain scoped in receipt journal",()=>{
        var journal=new Journal(root,context.Server,context.PhysicianId,protector);
        Check(journal.Completed().Single().Context==context,"Completed receipt unavailable");
    });
    Test("Upload verifies full capture and sends only authenticated PCM",()=>{
        var handler=new UploadHandler();using var client=new MosClient(context.Server,handler);
        client.Login("synthetic","synthetic").GetAwaiter().GetResult();
        var item=new PendingCapture(context,"start-key","finish-key",result.FilePath,result.PcmBytes,result.EncryptedFileSha256,"finished",1);
        var status=AudioUploader.Upload(client,item,protector).GetAwaiter().GetResult();
        Check(status.GetProperty("audio_received").GetBoolean(),"Missing receipt");
        Check(handler.Pcm.SequenceEqual(pcm.Concat(pcm)),"Upload PCM mismatch");
        Check(handler.Init.GetProperty("pcm_sha256").GetString()==EncryptedCapture.Verify(result.FilePath,protector).Summary.PcmSha256,"Whole checksum mismatch");
        Throws(()=>AudioUploader.Upload(client,item with{EncryptedFileSha256=new string('0',64)},protector).GetAwaiter().GetResult());
        Throws(()=>AudioUploader.Upload(client,item with{Reason="interrupted"},protector).GetAwaiter().GetResult());
    });
    Test("Playback buffer verifies context and complete PCM before exposure",()=>{
        var item=new PendingCapture(context,"start","finish",result.FilePath,result.PcmBytes,result.EncryptedFileSha256,"finished",1);
        using var buffer=VerifiedAudioBuffer.Load(item,context.Server,context.PhysicianId,protector);
        Check(buffer.Duration==TimeSpan.FromSeconds(2),"Wrong playback duration");
        using var input=buffer.OpenRead();using var copy=new MemoryStream();input.CopyTo(copy);
        Check(copy.ToArray().SequenceEqual(pcm.Concat(pcm)),"Playback PCM mismatch");
        Throws(()=>VerifiedAudioBuffer.Load(item,"https://other.example/",context.PhysicianId,protector));
        Throws(()=>VerifiedAudioBuffer.Load(item,context.Server,Guid.NewGuid().ToString(),protector));
        Throws(()=>VerifiedAudioBuffer.Load(item with{Context=context with{ConsentSha256=new string('b',64)}},context.Server,context.PhysicianId,protector));
        Throws(()=>VerifiedAudioBuffer.Load(item with{PcmBytes=item.PcmBytes-2},context.Server,context.PhysicianId,protector));
        Throws(()=>VerifiedAudioBuffer.Load(item with{Reason="interrupted"},context.Server,context.PhysicianId,protector));
        Throws(()=>VerifiedAudioBuffer.Load(item with{EncryptedFileSha256=new string('0',64)},context.Server,context.PhysicianId,protector));
    });
    Test("Playback rejects authenticated-file hash of a truncated capture",()=>{
        string file=Path.Combine(root,"playback-truncated.4baudio");File.WriteAllBytes(file,File.ReadAllBytes(result.FilePath)[..^30]);
        string sha=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file))).ToLowerInvariant();
        var item=new PendingCapture(context,"start","finish",file,result.PcmBytes,sha,"finished",1);
        Throws(()=>VerifiedAudioBuffer.Load(item,context.Server,context.PhysicianId,protector));
    });
    Test("Disposed playback closes readers and cannot reopen or export buffer",()=>{
        var item=new PendingCapture(context,"start","finish",result.FilePath,result.PcmBytes,result.EncryptedFileSha256,"finished",1);
        var buffer=VerifiedAudioBuffer.Load(item,context.Server,context.PhysicianId,protector);
        var input=(MemoryStream)buffer.OpenRead();Check(!input.TryGetBuffer(out _),"PCM array publicly exposed");
        Throws(()=>buffer.OpenRead());buffer.Dispose();buffer.Dispose();
        Throws(()=>input.ReadByte());Throws(()=>buffer.OpenRead());
        Check(!Directory.EnumerateFiles(root,"*.wav",SearchOption.AllDirectories).Any(),"Plain WAV created");
    });
    JsonElement MetricsPayload(string recordedId,string draftSha,string reviewSha,object? rate)=>JsonSerializer.SerializeToElement(new{
        recording_id=recordedId,draft_sha256=draftSha,review_sha256=reviewSha,comparison_kind="physician_revision_distance",reference_verified_against_audio=false,
        comparison=new{normalization_version="fa-text-v1",reference_sha256=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("الف"))).ToLowerInvariant(),candidate_sha256=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("الف ب ج"))).ToLowerInvariant(),reference_words=1,word_edit_distance=2,word_edit_rate=rate,reference_characters=3,character_edit_distance=2,character_edit_rate=2.0/3,numeric_sequence_changed=true,numeric_tokens_missing=1,numeric_tokens_added=1,clinical_accuracy_established=false,authorizes_diagnosis=false,training_performed=false}});
    string draftHash=new string('a',64),reviewHash=new string('b',64);
    Test("Revision metrics bind exact saved recording and text hashes",()=>{
        var payload=MetricsPayload(context.RecordingId,draftHash,reviewHash,2.0);
        var metrics=RevisionMetrics.Parse(payload,context.RecordingId,draftHash,reviewHash,"الف","الف ب ج");
        Check(metrics.WordEdits==2 && metrics.NumericSequenceChanged,"Metric values lost");
        Check(metrics.SummaryFa.Contains("تفاوت واژه‌ای") && !metrics.SummaryFa.Contains("الف"),"Unexpected report content");
        // A rate above 100% is valid; never clamp it into an accuracy score.
        Check(metrics.ReferenceWords==1,"Unexpected reference length");
        Throws(()=>RevisionMetrics.Parse(payload,Guid.NewGuid().ToString(),draftHash,reviewHash,"الف","الف ب ج"));
        Throws(()=>RevisionMetrics.Parse(payload,context.RecordingId,new string('c',64),reviewHash,"الف","الف ب ج"));
        Throws(()=>RevisionMetrics.Parse(payload,context.RecordingId,draftHash,new string('c',64),"الف","الف ب ج"));
        Throws(()=>RevisionMetrics.Parse(payload,context.RecordingId,draftHash,reviewHash,"متن دیگر","الف ب ج"));
    });
    Test("Malformed rates and unsupported reports are rejected",()=>{
        foreach(object? rate in new object?[]{-1.0,0.5,null,"not-a-number"}){
            var payload=MetricsPayload(context.RecordingId,draftHash,reviewHash,rate);
            Throws(()=>RevisionMetrics.Parse(payload,context.RecordingId,draftHash,reviewHash,"الف","الف ب ج"));
        }
        string json=MetricsPayload(context.RecordingId,draftHash,reviewHash,2.0).GetRawText();
        foreach(string changed in new[]{json.Replace("fa-text-v1","unknown-v9"),json.Replace("\"clinical_accuracy_established\":false","\"clinical_accuracy_established\":true"),json.Replace("\"word_edit_distance\":2","\"word_edit_distance\":-2")}){
            using var document=JsonDocument.Parse(changed);
            Throws(()=>RevisionMetrics.Parse(document.RootElement,context.RecordingId,draftHash,reviewHash,"الف","الف ب ج"));
        }
        Throws(()=>RevisionMetrics.Parse(JsonSerializer.SerializeToElement(new{}),context.RecordingId,draftHash,reviewHash,"الف","الف ب ج"));
    });
    Test("Undefined revision rates remain undefined",()=>{
        // Construct a valid empty-reference report rather than interpreting it as zero.
        var payload=JsonSerializer.SerializeToElement(new{
            recording_id=context.RecordingId,draft_sha256=draftHash,review_sha256=reviewHash,comparison_kind="physician_revision_distance",reference_verified_against_audio=false,
            comparison=new{normalization_version="fa-text-v1",reference_sha256=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("."))).ToLowerInvariant(),candidate_sha256=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("الف"))).ToLowerInvariant(),reference_words=0,word_edit_distance=1,word_edit_rate=(double?)null,reference_characters=0,character_edit_distance=3,character_edit_rate=(double?)null,numeric_sequence_changed=false,numeric_tokens_missing=0,numeric_tokens_added=0,clinical_accuracy_established=false,authorizes_diagnosis=false,training_performed=false}});
        var metrics=RevisionMetrics.Parse(payload,context.RecordingId,draftHash,reviewHash,".","الف");
        Check(metrics.SummaryFa.Contains("قابل محاسبه نیست"),"Undefined rate shown as zero");
    });
    Console.WriteLine($"{passed} recorder core tests passed. DPAPI: {(OperatingSystem.IsWindows()?"real Windows CurrentUser":"test protector; Windows CI verifies DPAPI")}.");
}finally{Directory.Delete(root,recursive:true);}

static bool Contains(byte[] haystack,byte[] needle)=>haystack.AsSpan().IndexOf(needle)>=0;
sealed class TestProtector:IKeyProtector
{
    private readonly byte[] _key=RandomNumberGenerator.GetBytes(32);
    public byte[] Protect(byte[] input){byte[] nonce=RandomNumberGenerator.GetBytes(12),tag=new byte[16],cipher=new byte[input.Length];using var aes=new AesGcm(_key,16);aes.Encrypt(nonce,input,cipher,tag);return nonce.Concat(tag).Concat(cipher).ToArray();}
    public byte[] Unprotect(byte[] input){byte[] plain=new byte[input.Length-28];using var aes=new AesGcm(_key,16);aes.Decrypt(input.AsSpan(0,12),input.AsSpan(28),input.AsSpan(12,16),plain);return plain;}
}
sealed class FakeHandler(string role):HttpMessageHandler
{
    public string? Authorization{get;private set;}
    public List<string> Requests{get;}=[];
    public static string UserId{get;set;}="";
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken cancellationToken){
        Requests.Add(request.RequestUri!.AbsoluteUri);Authorization=request.Headers.Authorization?.ToString();
        object body=request.RequestUri.AbsolutePath.EndsWith("/login")?new{access_token="synthetic-token"}:(object)new{id=UserId,display_name="Synthetic doctor",role};
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new StringContent(JsonSerializer.Serialize(body),Encoding.UTF8,"application/json")});
    }
}

sealed class UploadHandler:HttpMessageHandler
{
    public byte[] Pcm{get;private set;}=[];
    public JsonElement Init{get;private set;}
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken cancellationToken)
    {
        string path=request.RequestUri!.AbsolutePath;object body;
        if(path.EndsWith("/login"))body=new{access_token="synthetic-token"};
        else if(path.EndsWith("/me"))body=new{id=FakeHandler.UserId,display_name="Synthetic",role="physician"};
        else if(path.EndsWith("/initialize")){
            Init=JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken)).RootElement.Clone();
            body=new{audio_received=false,chunk_bytes=262144,next_chunk_index=0};
        }else if(path.Contains("/chunks/")){
            Pcm=await request.Content!.ReadAsByteArrayAsync(cancellationToken);
            string sha=Convert.ToHexString(SHA256.HashData(Pcm)).ToLowerInvariant();
            if(request.Headers.GetValues("X-PCM-SHA256").Single()!=sha)throw new Exception("Wrong chunk checksum");
            body=new{audio_received=false};
        }else if(path.EndsWith("/complete"))body=new{audio_received=true};
        else throw new Exception("Unexpected upload route");
        return new HttpResponseMessage(HttpStatusCode.OK){Content=new StringContent(JsonSerializer.Serialize(body),Encoding.UTF8,"application/json")};
    }
}
