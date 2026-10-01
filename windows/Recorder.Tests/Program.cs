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
