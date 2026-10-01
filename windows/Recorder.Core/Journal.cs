using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
namespace Mos.Recorder;
public sealed class Journal
{
    private readonly string _directory;
    private readonly IKeyProtector _protector;
    public Journal(string root,string server,string userId,IKeyProtector protector)
    {
        string clinic=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(server))).ToLowerInvariant();
        _directory=Path.Combine(root,clinic,Guid.Parse(userId).ToString("D"));
        Directory.CreateDirectory(_directory);_protector=protector;
    }
    public string AudioPath(string recordingId)=>Path.Combine(_directory,Guid.Parse(recordingId).ToString("D")+".part");
    private string PathFor(string id)=>Path.Combine(_directory,Guid.Parse(id).ToString("D")+".pending");
    public void Save(PendingCapture capture)
    {
        byte[] plain=JsonSerializer.SerializeToUtf8Bytes(capture);byte[] encrypted;
        try {encrypted=_protector.Protect(plain);}finally{CryptographicOperations.ZeroMemory(plain);}
        string target=PathFor(capture.Context.RecordingId),temp=target+".tmp";
        using(var output=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None)) {output.Write(encrypted);output.Flush(true);}
        File.Move(temp,target,overwrite:true);
    }
    public IReadOnlyList<PendingCapture> Load()
    {
        var items=new List<PendingCapture>();
        foreach(string path in Directory.EnumerateFiles(_directory,"*.pending")) {
            byte[] plain=_protector.Unprotect(File.ReadAllBytes(path));
            try {var item=JsonSerializer.Deserialize<PendingCapture>(plain)??throw new InvalidDataException("Invalid journal.");items.Add(item);}
            finally {CryptographicOperations.ZeroMemory(plain);}
        }
        return items;
    }
    public void Acknowledge(string id)=>File.Move(PathFor(id),Path.ChangeExtension(PathFor(id),"receipt"),overwrite:true);
}
