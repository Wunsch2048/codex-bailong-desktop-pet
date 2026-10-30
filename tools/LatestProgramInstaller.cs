// First-install bridge: no embedded Python runtime or old program payload.
// Only an explicitly launched installer contacts the fixed public channel.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class ProgramTarget {
    internal string Version,Name,Url,Sha256;
    internal long Bytes;
}

internal sealed class ProgramDownload {
    internal const string Repo="Wunsch2048/codex-bailong-desktop-pet";
    internal const string Channel="https://github.com/"+Repo+"/releases/latest/download/program-channel.json";
    internal const long Maximum=2147483647;
    internal delegate void ReadResponse(string url,Action<Stream> read);
    internal volatile bool Cancelled;
    HttpWebRequest active;
    readonly ReadResponse response;
    readonly JavaScriptSerializer json=new JavaScriptSerializer {MaxJsonLength=65536};
    internal ProgramDownload(ReadResponse response=null) {this.response=response ?? Fetch;}
    internal void Check() {if(Cancelled) throw new OperationCanceledException("已取消下载");}
    internal void Cancel() {Cancelled=true;var request=active;if(request!=null) request.Abort();}
    internal static bool Allowed(Uri u) {
        if(u.Scheme!="https" || u.UserInfo!="" || !u.IsDefaultPort || u.Fragment!="") return false;
        var h=u.DnsSafeHost.ToLowerInvariant();
        return h=="github.com" || h=="release-assets.githubusercontent.com" || h=="objects.githubusercontent.com" || h=="github-releases.githubusercontent.com" || Regex.IsMatch(h,@"^github-production-release-asset-[a-z0-9-]+\.s3\.amazonaws\.com$");
    }
    void Fetch(string url,Action<Stream> read) {
        var uri=new Uri(url);
        for(int hop=0;hop<7;hop++) {
            Check();if(!Allowed(uri)) throw new InvalidDataException("下载被重定向到未识别的地址");
            var request=(HttpWebRequest)WebRequest.Create(uri);active=request;
            request.AllowAutoRedirect=false;request.Timeout=20000;request.ReadWriteTimeout=20000;
            request.UserAgent="Bailong-First-Installer/1";
            request.CachePolicy=new System.Net.Cache.RequestCachePolicy(System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
            try {
                using(var reply=(HttpWebResponse)request.GetResponse()) {
                    int status=(int)reply.StatusCode;
                    if(status==301 || status==302 || status==303 || status==307 || status==308) {
                        var location=reply.Headers[HttpResponseHeader.Location];
                        if(String.IsNullOrWhiteSpace(location)) throw new InvalidDataException("下载跳转地址缺失");
                        uri=new Uri(uri,location);continue;
                    }
                    if(status!=200) throw new IOException("下载响应异常："+status);
                    using(var stream=reply.GetResponseStream()) {Check();read(stream);Check();}
                    return;
                }
            } finally {active=null;}
        }
        throw new IOException("下载跳转次数过多");
    }
    static string Hash(string path) {
        using(var stream=File.OpenRead(path)) using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
    }
    internal static string Safe(string root,string name) {
        if(String.IsNullOrEmpty(name) || name.Contains("\\") || name.Contains(":") || name.StartsWith("/")) throw new InvalidDataException("下载缓存路径无效");
        foreach(var part in name.Split('/')) if(part=="" || part=="." || part==".." || part.EndsWith(".") || part.EndsWith(" ") || Regex.IsMatch(part,@"[\x00-\x1f<>""|?*]")) throw new InvalidDataException("下载缓存路径无效");
        root=Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);var path=Path.GetFullPath(Path.Combine(root,name.Replace('/',Path.DirectorySeparatorChar)));
        if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("下载缓存路径越界");
        // Check every existing ancestor, including the selected cache root.
        for(var p=path;p!=null;p=Path.GetDirectoryName(p)) if((Directory.Exists(p)||File.Exists(p)) && (File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0) throw new InvalidDataException("下载缓存不能使用链接跳转");
        return path;
    }
    internal static ProgramTarget Parse(object value) {
        var d=value as Dictionary<string,object>;
        if(d==null || !d.ContainsKey("schema") || !d.ContainsKey("installerProtocol") || !d.ContainsKey("version") || !d.ContainsKey("program") || !d.ContainsKey("kind") || !(d["schema"] is int) || (int)d["schema"]!=1 || Convert.ToString(d["kind"])!="program-channel" || !(d["installerProtocol"] is int) || (int)d["installerProtocol"]!=1) throw new InvalidDataException("首次安装信息不兼容，请从官网获取新版安装器");
        var v=d["version"] as string;
        if(v==null || !Regex.IsMatch(v,@"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")) throw new InvalidDataException("程序版本无效");
        // The shared staging bridge compares System.Version values.
        new Version(v);
        var p=d["program"] as Dictionary<string,object>;var name="bailong-desktop-pet-"+v+"-program.zip";
        var url="https://github.com/"+Repo+"/releases/download/v"+v+"/"+name;
        if(p==null || !p.ContainsKey("name") || !p.ContainsKey("url") || !p.ContainsKey("sha256") || !p.ContainsKey("bytes") || Convert.ToString(p["name"])!=name || Convert.ToString(p["url"])!=url || !Regex.IsMatch(Convert.ToString(p["sha256"]),"^[0-9a-f]{64}$") || !(p["bytes"] is int || p["bytes"] is long)) throw new InvalidDataException("程序下载信息无效");
        var n=Convert.ToInt64(p["bytes"]);if(n<=0 || n>Maximum) throw new InvalidDataException("程序包大小异常");
        return new ProgramTarget {Version=v,Name=name,Url=url,Bytes=n,Sha256=Convert.ToString(p["sha256"])};
    }
    internal ProgramTarget Resolve() {
        string raw=null;
        response(Channel,delegate(Stream s) {
            using(var output=new MemoryStream()) {
                var buffer=new byte[4096];int n;
                while((n=s.Read(buffer,0,buffer.Length))>0) {Check();if(output.Length+n>65536) throw new InvalidDataException("首次安装信息过大");output.Write(buffer,0,n);}
                raw=new UTF8Encoding(false,true).GetString(output.ToArray()).TrimStart('\ufeff');
            }
        });
        Check();return Parse(json.DeserializeObject(raw));
    }
    internal string Download(ProgramTarget target,string cache,Action<long,long> progress) {
        var relative=target.Version+"/"+target.Sha256+".zip";var ready=Safe(cache,relative);
        Directory.CreateDirectory(Path.GetDirectoryName(ready));
        if(File.Exists(ready)) {
            if(new FileInfo(ready).Length!=target.Bytes || Hash(ready)!=target.Sha256) throw new InvalidDataException("程序下载缓存校验失败，请反馈此错误");
            progress(target.Bytes,target.Bytes);return ready;
        }
        var pending=Safe(cache,relative+".part");long count=0;
        // One bounded partial per version/hash. Retrying overwrites only this
        // file, so repeated network failures do not accumulate whole packages.
        // Never execute a partial or fall back to an older embedded program.
        response(target.Url,delegate(Stream s) {
            using(var output=new FileStream(pending,FileMode.Create,FileAccess.Write,FileShare.None)) {
                var buffer=new byte[262144];int n;var watch=Stopwatch.StartNew();long tick=-250;
                while((n=s.Read(buffer,0,buffer.Length))>0) {
                    Check();count+=n;if(count>target.Bytes) throw new InvalidDataException("下载文件超过公布大小");
                    output.Write(buffer,0,n);
                    if(watch.ElapsedMilliseconds-tick>=200) {tick=watch.ElapsedMilliseconds;progress(count,target.Bytes);}
                }
            }
        });
        Check();if(count!=target.Bytes || Hash(pending)!=target.Sha256) throw new InvalidDataException("程序包未完整下载或SHA-256校验失败");
        File.Move(pending,ready);progress(count,target.Bytes);return ready;
    }
    internal string Prepare(string local,Action<string> status,Action<long,long> progress) {
        status("正在获取最新程序…");var target=Resolve();Check();
        ProgramPatchBootstrap.CheckInstalledVersion(local,target.Version);Check();
        status("正在下载程序 "+target.Version+"…");
        var archive=Download(target,Path.Combine(local,"BailongEnhanced","first-install"),progress);Check();
        status("正在校验安装文件…");
        var source=ProgramPatchBootstrap.StageVerifiedPackage(archive,target.Version,target.Sha256);Check();
        return source;
    }
}

internal sealed class LatestProgramInstaller : Form {
    readonly Label status=new Label {AutoSize=false,Left=24,Top=22,Width=360,Height=42};
    readonly ProgressBar progress=new ProgressBar {Left=24,Top=68,Width=360,Height=12,Style=ProgressBarStyle.Marquee};
    readonly Button action=new Button {Text="取消",Left=304,Top=99,Width=80,Height=28};
    ProgramDownload transfer;Thread worker;bool handingOff,busy;
    internal LatestProgramInstaller() {
        Text="白龙桌宠安装";ClientSize=new System.Drawing.Size(408,148);FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
        Controls.AddRange(new Control[]{status,progress,action});
        action.Click+=delegate {if(busy) Close();else StartDownload();};
        Shown+=delegate {StartDownload();};FormClosing+=delegate {if(!handingOff && transfer!=null) transfer.Cancel();};
    }
    void Post(Action change) {if(!IsDisposed && IsHandleCreated) try {BeginInvoke(change);} catch(InvalidOperationException) {}}
    void StartDownload() {
        busy=true;action.Text="取消";progress.Style=ProgressBarStyle.Marquee;transfer=new ProgramDownload();
        worker=new Thread(delegate() {
            try {
                var local=Environment.GetEnvironmentVariable("LOCALAPPDATA");
                if(String.IsNullOrWhiteSpace(local)) throw new InvalidOperationException("无法确定用户数据目录");
                var source=transfer.Prepare(local,s=>Post(()=>status.Text=s),(n,total)=>Post(()=>{progress.Style=ProgressBarStyle.Continuous;progress.Value=(int)(n*100/total);}));
                Post(delegate {
                    if(transfer.Cancelled) return;
                    try {
                        // Only this verified new program is invoked. Its normal
                        // installer owns directory choice, backup and rollback.
                        Process.Start(new ProcessStartInfo {FileName=Path.Combine(source,"BailongEnhanced.exe"),Arguments="--apply-program-update",WorkingDirectory=source,UseShellExecute=false});
                        handingOff=true;Close();
                    } catch(Exception e) {Failed(e);}
                });
            } catch(Exception e) {Post(()=>Failed(e));}
        });worker.IsBackground=true;worker.Start();
    }
    void Failed(Exception error) {
        if(transfer.Cancelled) return;busy=false;progress.Style=ProgressBarStyle.Continuous;progress.Value=0;action.Text="重试";
        var win=error as System.ComponentModel.Win32Exception;
        status.Text=win!=null && (win.NativeErrorCode==225 || win.NativeErrorCode==226) ? "安全防护拦截了程序，请查看保护历史记录。" : "准备失败："+error.Message;
    }
    [STAThread] static int Main() {
        ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
        bool acquired=false;
        using(var mutex=new Mutex(false,"Local\\BailongFirstInstall")) try {
            try {acquired=mutex.WaitOne(0);} catch(AbandonedMutexException) {acquired=true;}
            if(!acquired) {MessageBox.Show("另一个安装程序正在准备，请稍后重试。","白龙桌宠安装");return 1;}
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new LatestProgramInstaller());return 0;
        } finally {if(acquired) mutex.ReleaseMutex();}
    }
}
