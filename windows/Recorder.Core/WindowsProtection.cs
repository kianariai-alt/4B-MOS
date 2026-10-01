using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
namespace Mos.Recorder;
[SupportedOSPlatform("windows")]
public sealed class WindowsProtection : IKeyProtector
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("4B-MOS.VisitRecorder.v1");
    public byte[] Protect(byte[] data) => ProtectedData.Protect(data, Entropy, DataProtectionScope.CurrentUser);
    public byte[] Unprotect(byte[] data) => ProtectedData.Unprotect(data, Entropy, DataProtectionScope.CurrentUser);
}
