using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
namespace Mos.Recorder;
public sealed class MosClient : IDisposable
{
    public static readonly JsonSerializerOptions Json=new(){PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower};
    private readonly HttpClient _http;
    public string Server {get;}
    public string? UserId {get;private set;}
    public string? DisplayName {get;private set;}
    public MosClient(string server,HttpMessageHandler? handler=null)
    {
        Server=ValidateServer(server).AbsoluteUri;
        _http=new HttpClient(handler??new HttpClientHandler{AllowAutoRedirect=false,UseCookies=false}){BaseAddress=new Uri(Server),Timeout=TimeSpan.FromSeconds(10)};
    }
    public static Uri ValidateServer(string value)
    {
        if(!Uri.TryCreate(value,UriKind.Absolute,out var uri) || (uri.Scheme!="https" && !(uri.Scheme=="http" && uri.IsLoopback)) || uri.UserInfo.Length!=0 || uri.Query.Length!=0 || uri.Fragment.Length!=0 || uri.AbsolutePath!="/")
            throw new ArgumentException("از HTTPS سرور یا HTTP روی localhost استفاده کنید؛ آدرس بدون مسیر اضافی باشد.");
        return uri;
    }
    private async Task<JsonElement> Read(HttpResponseMessage response)
    {
        using(response) {
            if(!response.IsSuccessStatusCode)throw new MosApiException(response.StatusCode);
            return await response.Content.ReadFromJsonAsync<JsonElement>();
        }
    }
    public async Task Login(string username,string password)
    {
        var token=await Post("auth/login",new{username,password});
        _http.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",token.GetProperty("access_token").GetString());
        var me=await Get("auth/me");
        if(me.GetProperty("role").GetString()!="physician")throw new InvalidOperationException("ورود فقط برای حساب پزشک فعال است.");
        UserId=me.GetProperty("id").GetString();DisplayName=me.GetProperty("display_name").GetString();
    }
    public Task<JsonElement> Get(string path)=>GetInternal(path);
    private async Task<JsonElement> GetInternal(string path)=>await Read(await _http.GetAsync("api/v1/"+path));
    public async Task<JsonElement> Post(string path,object command)=>await Read(await _http.PostAsJsonAsync("api/v1/"+path,command,Json));
    public static string VisitPath(string visitId)=>"visits/"+Guid.Parse(visitId).ToString("D")+"/recordings";
    public void Dispose(){_http.DefaultRequestHeaders.Authorization=null;_http.Dispose();UserId=null;}
}
public sealed class MosApiException(HttpStatusCode status):Exception(status switch {
    HttpStatusCode.Unauthorized=>"نشست ورود منقضی شده است؛ دوباره وارد شوید.",
    HttpStatusCode.Forbidden=>"این ویزیت به حساب پزشک شما اختصاص ندارد یا دسترسی مجاز نیست.",
    HttpStatusCode.Conflict=>"رضایت یا نسخه تغییر کرده است؛ وضعیت ویزیت را دوباره بررسی کنید.",
    HttpStatusCode.NotFound=>"ویزیت یا نسخه موردنیاز سرور پیدا نشد.",
    _=>"سرور اقدام را نپذیرفت؛ تنظیمات و داده‌ها را بررسی کنید."
}) {public HttpStatusCode Status {get;}=status;}
