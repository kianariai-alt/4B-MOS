using System.Net.Http;
using System.ComponentModel;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using NAudio.Wave;

namespace Mos.Recorder.App;
public partial class MainWindow : Window
{
    private MosClient? _client;
    private Journal? _journal;
    private readonly WindowsProtection _protection=new();
    private JsonElement? _access;
    private string? _visitId;
    private PendingCapture? _pending;
    private WaveInEvent? _microphone;
    private EncryptedCapture? _encrypted;
    private readonly object _audioLock=new();
    private readonly DispatcherTimer _timer=new(){Interval=TimeSpan.FromSeconds(5)};
    private TaskCompletionSource? _stopped;
    private Task? _stopTask;
    private bool _busy,_checking,_allowClose;
    private long _captureGeneration;
    private volatile bool _captureStopping;
    private long _lastSoundTicks;

    public MainWindow()
    {
        InitializeComponent();_timer.Tick+=Heartbeat;
        AcknowledgeBox.Checked+=(_,_)=>RefreshButtons();
        AcknowledgeBox.Unchecked+=(_,_)=>RefreshButtons();
        VisitBox.TextChanged+=(_,_)=>{if(_microphone is null){_access=null;_visitId=null;VisitText.Text="";RefreshButtons();}};
        for(int i=0;i<WaveIn.DeviceCount;i++)Microphones.Items.Add(WaveIn.GetCapabilities(i).ProductName);
        if(Microphones.Items.Count>0)Microphones.SelectedIndex=0;
    }

    private void Message(string text)=>StatusText.Text=text;
    private void RefreshButtons()
    {
        bool recording=_microphone is not null;
        LoginButton.IsEnabled=!_busy;
        StartButton.IsEnabled=!_busy && !recording && _access is { } access && access.GetProperty("can_record").GetBoolean() && AcknowledgeBox.IsChecked==true && Microphones.SelectedIndex>=0;
        StopButton.IsEnabled=recording && !_captureStopping;
        foreach(var node in new System.Windows.Controls.Control[]{LoadButton,VisitBox,Microphones,AcknowledgeBox,SyncButton,LogoutButton})node.IsEnabled=!_busy && !recording;
    }
    private async Task Run(Func<Task> action)
    {
        if(_busy)return;_busy=true;RefreshButtons();
        try{await action();}
        catch(Exception error){Message(UserMessage(error));}
        finally{_busy=false;RefreshButtons();}
    }
    private static string UserMessage(Exception error)=>error switch {
        MosApiException=>error.Message,
        ArgumentException=>"آدرس سرور یا شناسه ویزیت معتبر نیست.",
        HttpRequestException or TaskCanceledException=>"ارتباط با MOS برقرار نشد؛ ضبط جدید آغاز نشده و فایل‌های قبلی محفوظ‌اند.",
        CryptographicException or InvalidDataException=>"فایل محلی قابل تأیید نیست؛ آن را حذف نکنید و برای بررسی فنی نگه دارید.",
        _=>"اقدام کامل نشد؛ میکروفن، فضای دیسک و دسترسی‌ها را بررسی کنید. فایل‌های موجود حذف نشده‌اند."
    };
    private async void LoginClick(object sender,RoutedEventArgs e)=>await Run(async()=>{
        var candidate=new MosClient(ServerBox.Text.Trim());
        try{await candidate.Login(UsernameBox.Text.Trim(),PasswordBox.Password);}
        catch{candidate.Dispose();throw;}
        finally{PasswordBox.Clear();}
        _client?.Dispose();_client=candidate;
        _journal=new Journal(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"4B-MOS","Recorder"),candidate.Server,candidate.UserId!,_protection);
        IdentityText.Text=candidate.DisplayName;LoginPanel.Visibility=Visibility.Collapsed;VisitPanel.Visibility=Visibility.Visible;
        Message("ورود انجام شد. ابتدا ویزیت و رضایت ضبط را بررسی کنید؛ ضبط‌های معلق را نیز می‌توانید ثبت کنید.");
    });
    private async void LoadClick(object sender,RoutedEventArgs e)=>await Run(async()=>{
        _access=null;_visitId=null;
        string id=Guid.Parse(VisitBox.Text.Trim()).ToString("D");
        var access=await _client!.Get(MosClient.VisitPath(id)+"/access");
        _access=access;_visitId=id;AcknowledgeBox.IsChecked=false;
        string reason=access.GetProperty("block_reason").ValueKind==JsonValueKind.Null?"آماده ضبط":access.GetProperty("block_reason").GetString() switch {
            "consent_required"=>"رضایت معتبر ضبط ثبت نشده است", "visit_closed"=>"ویزیت بسته است", _=>"ضبط قبلی هنوز پایان نیافته است"
        };
        VisitText.Text=$"کد بیمار: {access.GetProperty("patient_code").GetString()} — {reason}";
        Message("این برنامه رضایت جدیدی ایجاد نمی‌کند؛ رضایت باید در پذیرش MOS ثبت شود.");
    });
    private async void StartClick(object sender,RoutedEventArgs e)=>await Run(async()=>{
        if(_client is null || _journal is null || _visitId is null || AcknowledgeBox.IsChecked!=true)return;
        if(_journal.Load().Count!=0){Message("ابتدا پایان ضبط‌های معلق این حساب را ثبت کنید.");return;}
        string visit=_visitId,path=MosClient.VisitPath(visit);
        var access=await _client.Get(path+"/access");
        if(!access.GetProperty("can_record").GetBoolean()){_access=access;Message("اجازه ضبط تغییر کرده است؛ ویزیت را دوباره بررسی کنید.");return;}
        string recording=Guid.NewGuid().ToString("D"),key=Guid.NewGuid().ToString("D"),consent=access.GetProperty("consent_sha256").GetString()!;
        var context=new CaptureContext(_client.Server,_client.UserId!,visit,recording,consent,DateTimeOffset.UtcNow);
        _pending=new PendingCapture(context,key,null,null,0,null,null);
        // Persist before the first request: an ambiguous network outcome can
        // be resolved by the same recording id after login/restart.
        _journal.Save(_pending);
        var start=await _client.Post(path+"/start",new{recording_id=recording,expected_version=access.GetProperty("version").GetInt32(),request_key=key,expected_consent_sha256=consent});
        _pending=_pending with{Context=context with{StartedAt=DateTimeOffset.Parse(start.GetProperty("created_at").GetString()!)}};_journal.Save(_pending);
        var check=await _client.Get(path+"/"+recording+"/check");
        if(!check.GetProperty("can_continue").GetBoolean()){Message("مجوز ضبط تغییر کرد؛ میکروفن فعال نشد. پایان ضبط معلق را ثبت کنید.");return;}
        try{
            _encrypted=new EncryptedCapture(_journal.AudioPath(recording),_pending.Context,_protection);
            _stopped=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            _captureStopping=false;_stopTask=null;_captureGeneration++;
            _microphone=new WaveInEvent{DeviceNumber=Microphones.SelectedIndex,WaveFormat=new WaveFormat(16000,16,1),BufferMilliseconds=400,NumberOfBuffers=3};
            _microphone.DataAvailable+=AudioAvailable;
            var stopped=_stopped;var microphone=_microphone;
            _microphone.RecordingStopped+=(_,args)=>{
                stopped.TrySetResult();
                Dispatcher.BeginInvoke(new Action(async()=>{
                    if(ReferenceEquals(_microphone,microphone) && !_captureStopping)await StopCapture("microphone_error");
                }));
            };
            Interlocked.Exchange(ref _lastSoundTicks,DateTimeOffset.UtcNow.UtcTicks);_microphone.StartRecording();_timer.Start();
            Message("ضبط فعال است. برای پس‌گرفتن رضایت، همین‌جا توقف را بزنید؛ قطع ارتباط با MOS نیز ضبط را متوقف می‌کند.");
        }catch{
            _captureStopping=true;_microphone?.Dispose();_microphone=null;
            lock(_audioLock){_encrypted?.Dispose();_encrypted=null;}
            Message("میکروفن فعال نشد؛ ثبت شروع محفوظ است. پایان ضبط معلق را ثبت کنید.");
        }
    });

    private void AudioAvailable(object? sender,WaveInEventArgs args)
    {
        if(_captureStopping || !ReferenceEquals(sender,_microphone))return;
        long generation=_captureGeneration;
        byte[] buffer=args.Buffer.AsSpan(0,args.BytesRecorded).ToArray();
        try{
            double peak=0;
            for(int i=0;i+1<buffer.Length;i+=2)peak=Math.Max(peak,Math.Abs((int)BitConverter.ToInt16(buffer,i))/32768.0);
            if(peak>.005)Interlocked.Exchange(ref _lastSoundTicks,DateTimeOffset.UtcNow.UtcTicks);
            long bytes;
            lock(_audioLock){
                if(_captureStopping || _encrypted is null)return;
                if(_encrypted.PcmBytes+buffer.Length>460800000){Dispatcher.BeginInvoke(new Action(async()=>await StopCapture("duration_limit")));return;}
                _encrypted.Append(buffer);bytes=_encrypted.PcmBytes;
            }
            Dispatcher.BeginInvoke(new Action(()=>{if(generation!=_captureGeneration || _captureStopping)return;LevelBar.Value=peak*100;CaptureText.Text=$"مدت صوت ذخیره‌شده: {TimeSpan.FromSeconds(bytes/32000.0):hh\\:mm\\:ss}";}));
        }catch{Dispatcher.BeginInvoke(new Action(async()=>await StopCapture("microphone_error")));}
        finally{CryptographicOperations.ZeroMemory(buffer);}
    }
    private async void Heartbeat(object? sender,EventArgs e)
    {
        if(_checking || _captureStopping || _microphone is null || _pending is null)return;
        _checking=true;long generation=_captureGeneration;var pending=_pending;
        try{
            var check=await _client!.Get(MosClient.VisitPath(pending.Context.VisitId)+"/"+pending.Context.RecordingId+"/check");
            if(generation!=_captureGeneration || _captureStopping || _microphone is null)return;
            if(!check.GetProperty("can_continue").GetBoolean()){
                string reason=check.GetProperty("reason").GetString() switch{"consent_changed"=>"consent_changed","duration_limit"=>"duration_limit",_=>"session_changed"};
                await StopCapture(reason);return;
            }
            if(DateTimeOffset.UtcNow.UtcTicks-Interlocked.Read(ref _lastSoundTicks)>TimeSpan.FromSeconds(20).Ticks)Message("صدای قابل توجهی دریافت نشده است؛ اتصال و محل میکروفن را بررسی کنید.");
        }catch{if(generation==_captureGeneration && !_captureStopping && _microphone is not null)await StopCapture("connection_lost");}
        finally{_checking=false;}
    }
    private Task StopCapture(string reason)
    {
        if(_stopTask is not null)return _stopTask;
        _captureStopping=true;_captureGeneration++;_timer.Stop();RefreshButtons();
        _stopTask=FinishCapture(reason);return _stopTask;
    }
    private async Task FinishCapture(string reason)
    {
        try{
            if(_microphone is null || _pending is null || _journal is null)return;
            _microphone.StopRecording();
            if(_stopped is not null)await _stopped.Task.WaitAsync(TimeSpan.FromSeconds(5));
            _microphone.Dispose();_microphone=null;
            CaptureResult result;
            lock(_audioLock){result=_encrypted!.Complete(reason);_encrypted=null;}
            _pending=_pending with{FilePath=result.FilePath,PcmBytes=result.PcmBytes,EncryptedFileSha256=result.EncryptedFileSha256,Reason=reason};
            _journal.Save(_pending);
            try{await SyncOne(_pending);Message("صوت رمزگذاری‌شده محفوظ است و پایان ضبط در MOS ثبت شد. تبدیل گفتار هنوز فعال نیست.");}
            catch{Message("ضبط متوقف و صوت رمزگذاری‌شده محفوظ شد؛ پایان ضبط هنوز در صف ثبت MOS است.");}
        }catch{Message("ضبط متوقف شد؛ فایل ناتمام محفوظ است. پس از ورود دوباره، ثبت ضبط‌های معلق را انجام دهید.");}
        finally{
            _microphone?.Dispose();_microphone=null;
            lock(_audioLock){_encrypted?.Dispose();_encrypted=null;}
            LevelBar.Value=0;_access=null;_visitId=null;RefreshButtons();
        }
    }
    private async void StopClick(object sender,RoutedEventArgs e)=>await StopCapture("finished");

    private async Task SyncOne(PendingCapture item)
    {
        if(_client is null || _journal is null)throw new InvalidOperationException();
        if(item.Context.Server!=_client.Server || item.Context.PhysicianId!=_client.UserId)throw new InvalidDataException("Context mismatch.");
        string path=MosClient.VisitPath(item.Context.VisitId);
        if(item.FinishRequestKey is null){
            string part=_journal.AudioPath(item.Context.RecordingId),full=Path.ChangeExtension(part,"4baudio");
            string? file=File.Exists(full)?full:File.Exists(part)?part:null;
            long bytes=0;string? digest=null;string reason="interrupted";
            if(file is not null){
                var verified=await Task.Run(()=>EncryptedCapture.Verify(file,_protection,allowInterrupted:file==part));
                if(verified.Context!=item.Context)throw new InvalidDataException("Audio context mismatch.");
                bytes=verified.Summary.PcmBytes;reason=verified.Summary.Reason;
                using var input=File.OpenRead(file);digest=Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
            }
            JsonElement check;
            try{check=await _client.Get(path+"/"+item.Context.RecordingId+"/check");}
            catch(MosApiException error) when(error.Status==System.Net.HttpStatusCode.NotFound && file is null){_journal.Acknowledge(item.Context.RecordingId);return;}
            item=item with{FilePath=file,PcmBytes=bytes,EncryptedFileSha256=digest,Reason=reason,FinishRequestKey=Guid.NewGuid().ToString("D"),FinishVersion=check.GetProperty("version").GetInt32()};
            _journal.Save(item);
        }
        await _client.Post(path+"/finish",new{recording_id=item.Context.RecordingId,expected_version=item.FinishVersion!.Value,request_key=item.FinishRequestKey,reason=item.Reason,pcm_bytes=item.PcmBytes,encrypted_file_sha256=item.EncryptedFileSha256});
        _journal.Acknowledge(item.Context.RecordingId);if(_pending?.Context.RecordingId==item.Context.RecordingId)_pending=null;
    }
    private async void SyncClick(object sender,RoutedEventArgs e)=>await Run(async()=>{
        foreach(var pending in _journal!.Load())await SyncOne(pending);
        _access=null;_visitId=null;Message("ثبت پایان ضبط‌های معلق انجام شد؛ فایل‌های صوتی محلی حفظ شده‌اند.");
    });
    private void LogoutClick(object sender,RoutedEventArgs e)
    {
        if(_microphone is not null)return;
        _client?.Dispose();_client=null;_journal=null;_pending=null;_access=null;_visitId=null;
        IdentityText.Text="";VisitText.Text="";CaptureText.Text="";VisitBox.Clear();UsernameBox.Clear();PasswordBox.Clear();AcknowledgeBox.IsChecked=false;
        LoginPanel.Visibility=Visibility.Visible;VisitPanel.Visibility=Visibility.Collapsed;RefreshButtons();Message("از حساب خارج شدید؛ فایل‌های رمزگذاری‌شده حذف نشده‌اند.");
    }
    private async void WindowClosing(object? sender,CancelEventArgs e)
    {
        if(_allowClose)return;
        if(_busy){e.Cancel=true;Message("منتظر پایان اقدام جاری بمانید؛ سپس برنامه را ببندید.");return;}
        if(_microphone is not null){e.Cancel=true;await StopCapture("app_closing");_allowClose=true;Close();return;}
        _timer.Stop();_client?.Dispose();
    }
}
