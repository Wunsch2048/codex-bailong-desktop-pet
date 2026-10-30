// Small offline installer bridge for clients that still require windows-x64.zip.
// The payload is pinned at build time. No download, shell command, directory
// deletion, login access or deployment occurs before the verified app takes over.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("白龙桌宠程序安装器")]
[assembly: AssemblyProduct("白龙桌宠增强版")]
[assembly: AssemblyCompany("Wunsch2048")]
[assembly: AssemblyDescription("校验程序包后打开安装界面；开机启动由用户选择")]
[assembly: AssemblyVersion("@@VERSION@@.0")]
[assembly: AssemblyFileVersion("@@VERSION@@.0")]

static class ProgramPatchBootstrap {
    const string VersionNumber = "@@VERSION@@";
    const string PayloadSha = "@@PAYLOAD_SHA@@";
    const string MediaPrefix = "outputs/白龙桌宠素材/";
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 8388608 };
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateHardLink(string name, string existing, IntPtr reserved);

    static Dictionary<string,object> Dict(object value) {
        var data = value as Dictionary<string,object>;
        if (data == null) throw new InvalidDataException("补丁说明格式无效");
        return data;
    }
    static string Text(Dictionary<string,object> data,string key) { return Convert.ToString(data[key]); }
    static string Hash(Stream stream) { using (var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant(); }
    static string HashFile(string path) { using(var stream=File.OpenRead(path)) return Hash(stream); }
    static Dictionary<string,object> ReadJson(string path) { return Dict(Json.DeserializeObject(File.ReadAllText(path,Utf8))); }
    static void AtomicJson(string path,object data) {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        var temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        File.WriteAllText(temp,Json.Serialize(data),Utf8);
        if(File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
    }
    static string Safe(string root,string name) {
        if(String.IsNullOrEmpty(name) || name.Contains("\\") || name.Contains(":") || name.StartsWith("/")) throw new InvalidDataException("补丁路径无效");
        foreach(var part in name.Split('/')) {
            if(part=="" || part=="." || part==".." || part.EndsWith(".") || part.EndsWith(" ") ||
                Regex.IsMatch(part,@"[\x00-\x1f<>""|?*]") || Regex.IsMatch(part,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",RegexOptions.IgnoreCase)) throw new InvalidDataException("补丁文件名无效");
        }
        root=Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        var path=Path.GetFullPath(Path.Combine(root,name.Replace('/',Path.DirectorySeparatorChar)));
        if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("补丁路径越界");
        for(var item=path; item!=null && (item==root || item.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase));item=Path.GetDirectoryName(item)) {
            if((File.Exists(item) || Directory.Exists(item)) && (File.GetAttributes(item)&FileAttributes.ReparsePoint)!=0) throw new InvalidDataException("补丁目录不能使用链接跳转");
        }
        return path;
    }
    static Dictionary<string,object> ZipJson(ZipArchive archive,string name) {
        var entry=archive.GetEntry(name);
        if(entry==null || entry.Length>8388608) throw new InvalidDataException("补丁缺少有效说明");
        using(var stream=entry.Open()) using(var reader=new StreamReader(stream,Utf8)) return Dict(Json.DeserializeObject(reader.ReadToEnd()));
    }
    static bool Matches(string path,Dictionary<string,object> record) {
        return File.Exists(path) && new FileInfo(path).Length==Convert.ToInt64(record["bytes"]) && HashFile(path)==Text(record,"sha256");
    }
    static void Verify(string root,Dictionary<string,object> files) {
        var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var name in files.Keys) {
            if(!seen.Add(name) || !Matches(Safe(root,name),Dict(files[name]))) throw new InvalidDataException("暂存文件校验失败："+name);
        }
        foreach(var path in Directory.GetFiles(root,"*",SearchOption.AllDirectories)) {
            var name=path.Substring(root.Length+1).Replace('\\','/');
            if(name!="payload-manifest.json" && !files.ContainsKey(name)) throw new InvalidDataException("暂存目录包含未识别文件");
        }
    }
    static string InstalledSource(string local,string version) {
        var install=Path.Combine(local,"Programs","BailongEnhanced");
        if(Environment.GetEnvironmentVariable("BAILONG_ISOLATED")!="1") {
            using(var key=Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced")) {
                if(key!=null) {
                    var location=key.GetValue("InstallLocation") as string;
                    var data=key.GetValue("DataLocation") as string;
                    bool bound=!String.IsNullOrWhiteSpace(data) && String.Equals(Path.GetFullPath(data).TrimEnd('\\'),Path.Combine(local,"BailongEnhanced").TrimEnd('\\'),StringComparison.OrdinalIgnoreCase);
                    bool legacy=String.IsNullOrWhiteSpace(data) && !String.IsNullOrWhiteSpace(location) && String.Equals(Path.GetFullPath(location).TrimEnd('\\'),Path.GetFullPath(install).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase);
                    if((bound || legacy) && !String.IsNullOrWhiteSpace(location) && Path.IsPathRooted(location) && String.Equals(Path.GetFileName(location.TrimEnd('\\')),"BailongEnhanced",StringComparison.OrdinalIgnoreCase)) install=Path.GetFullPath(location);
                }
            }
        }
        var path=Path.Combine(install,"installations.json");
        if(!File.Exists(path)) return null;
        var current=Text(ReadJson(path),"current");
        if(!Regex.IsMatch(current,@"^\d+\.\d+\.\d+-[A-Za-z0-9-]+$")) throw new InvalidDataException("现有安装记录无效");
        if(new Version(current.Split('-')[0])>new Version(version)) throw new InvalidOperationException("本机程序版本较新，无需安装此程序补丁。");
        return Safe(Path.Combine(install,"versions"),current);
    }
    internal static void CheckInstalledVersion(string local,string version) { InstalledSource(local,version); }
    static string FindMedia(string local,string old,string id,Dictionary<string,object> media) {
        var roots=new List<string>();
        if(old!=null) roots.Add(Path.Combine(old,"outputs","白龙桌宠素材"));
        var pointer=Path.Combine(local,"BailongEnhanced","material-location.json");
        if(File.Exists(pointer)) {
            var value=ReadJson(pointer);var location=Text(value,"path");
            if(Convert.ToInt32(value["schema"])!=1 || !Path.IsPathRooted(location)) throw new InvalidDataException("动画目录配置无效");
            roots.Add(Safe(Path.GetFullPath(location),"light/"+id));
        }
        roots.Add(Safe(Path.Combine(local,"BailongEnhanced","materials"),"light/"+id));
        foreach(var root in roots) {
            bool valid=true;
            try { foreach(var pair in media) if(!Matches(Safe(root,pair.Key.Substring(MediaPrefix.Length)),Dict(pair.Value))) {valid=false;break;} }
            catch(IOException) { valid=false; } catch(UnauthorizedAccessException) { valid=false; }
            if(valid) return root;
        }
        return null;
    }
    internal static string StageVerifiedPackage(string payloadPath,string version,string payloadSha) {
        if(!Regex.IsMatch(version,@"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") || !Regex.IsMatch(payloadSha,"^[0-9a-f]{64}$")) throw new InvalidDataException("程序版本或校验值无效");
        var local=Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if(String.IsNullOrWhiteSpace(local)) throw new InvalidOperationException("无法确定用户数据目录");
        local=Path.GetFullPath(local);var old=InstalledSource(local,version);
        var cache=Safe(Path.Combine(local,"BailongEnhanced","updates"),version+"/program");Directory.CreateDirectory(cache);
        var archivePath=Safe(cache,"package.zip");
        if(!File.Exists(archivePath)) {
            var pending=Safe(cache,"package."+Guid.NewGuid().ToString("N")+".pending");
            using(var input=payloadPath==null ? Assembly.GetExecutingAssembly().GetManifestResourceStream("Bailong.Program") : File.OpenRead(payloadPath)) {
                if(input==null) throw new InvalidDataException("程序补丁载荷缺失");
                using(var output=File.Create(pending)) input.CopyTo(output);
            }
            if(HashFile(pending)!=payloadSha) throw new InvalidDataException("程序补丁 SHA-256 不匹配");
            File.Move(pending,archivePath);
        }
        if(HashFile(archivePath)!=payloadSha) throw new InvalidDataException("下载缓存的程序补丁已改变");
        using(var archive=ZipFile.OpenRead(archivePath)) {
            var descriptor=ZipJson(archive,"program-update.json");var manifest=ZipJson(archive,"payload-manifest.json");
            if(Text(descriptor,"version")!=version || Text(manifest,"version")!=version || Convert.ToInt32(descriptor["schema"])!=1 || Text(descriptor,"kind")!="program" || !descriptor.ContainsKey("optionalMaterials") || !Convert.ToBoolean(descriptor["optionalMaterials"])) throw new InvalidDataException("程序补丁版本不匹配");
            var files=Dict(manifest["files"]);var core=new Dictionary<string,object>(StringComparer.Ordinal);var media=new Dictionary<string,object>(StringComparer.Ordinal);
            long total=0;
            if(files.Count>20128) throw new InvalidDataException("程序文件数量过多");
            foreach(var value in files.Values) {
                var record=Dict(value);var size=Convert.ToInt64(record["bytes"]);
                if(size<0 || size>=2147483648 || !Regex.IsMatch(Text(record,"sha256"),"^[0-9a-f]{64}$")) throw new InvalidDataException("程序文件校验信息无效");
            }
            foreach(var pair in files) { Safe(cache,pair.Key); if(pair.Key.StartsWith(MediaPrefix,StringComparison.Ordinal)) media.Add(pair.Key,pair.Value); else core.Add(pair.Key,pair.Value); }
            foreach(var value in core.Values) {total+=Convert.ToInt64(Dict(value)["bytes"]);if(total>2147483647) throw new InvalidDataException("程序包展开体积过大");}
            if(!core.ContainsKey("BailongEnhanced.exe") || !core.ContainsKey("app/material_catalog.json") || core.Count>20000) throw new InvalidDataException("程序补丁缺少必要文件");
            var catalog=ZipJson(archive,"app/material_catalog.json");var light=Dict(Dict(catalog["tiers"])["light"]);var id=Text(light,"id");
            if(!Regex.IsMatch(id,"^[0-9a-f]{24}$") || id!=Text(descriptor,"materialId")) throw new InvalidDataException("动画素材标识不匹配");
            int count=0;
            foreach(var item in (IEnumerable)light["files"]) {
                var record=Dict(item);var name=MediaPrefix+Text(record,"path");
                if(!media.ContainsKey(name) || Text(Dict(media[name]),"sha256")!=Text(record,"sha256") || Convert.ToInt64(Dict(media[name])["bytes"])!=Convert.ToInt64(record["bytes"])) throw new InvalidDataException("动画复用清单不匹配");
                count++;if(count>128) throw new InvalidDataException("动画复用清单过大");
            }
            if(count!=media.Count) throw new InvalidDataException("动画复用清单不完整");
            var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var entry in archive.Entries) {
                Safe(cache,entry.FullName);
                if(!names.Add(entry.FullName) || (entry.FullName!="program-update.json" && entry.FullName!="payload-manifest.json" && !core.ContainsKey(entry.FullName))) throw new InvalidDataException("程序补丁文件重复或越界");
            }
            if(names.Count!=core.Count+2) throw new InvalidDataException("程序补丁文件不完整");
            var source=Safe(cache,"source");
            if(!Directory.Exists(source)) {
                var pending=Safe(cache,"source.pending-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(pending);
                foreach(var pair in core) {
                    var record=Dict(pair.Value);var entry=archive.GetEntry(pair.Key);var path=Safe(pending,pair.Key);
                    if(entry==null || entry.Length!=Convert.ToInt64(record["bytes"])) throw new InvalidDataException("程序文件大小不匹配");
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    using(var input=entry.Open()) using(var output=File.Create(path)) input.CopyTo(output);
                    if(!Matches(path,record)) throw new InvalidDataException("程序文件 SHA-256 不匹配");
                }
                var oldMedia=FindMedia(local,old,id,media);
                var staged=new Dictionary<string,object>(core,StringComparer.Ordinal);
                if(oldMedia!=null) foreach(var pair in media) {
                    var input=Safe(oldMedia,pair.Key.Substring(MediaPrefix.Length));var path=Safe(pending,pair.Key);Directory.CreateDirectory(Path.GetDirectoryName(path));
                    if(!CreateHardLink(path,input,IntPtr.Zero)) File.Copy(input,path);
                    staged.Add(pair.Key,pair.Value);
                }
                manifest["files"]=staged;AtomicJson(Safe(pending,"payload-manifest.json"),manifest);Verify(pending,staged);Directory.Move(pending,source);
            }
            var ready=ReadJson(Safe(source,"payload-manifest.json"));var readyFiles=Dict(ready["files"]);
            if(Text(ready,"version")!=version) throw new InvalidDataException("已有暂存版本不匹配");
            foreach(var pair in core) if(!readyFiles.ContainsKey(pair.Key) || Text(Dict(readyFiles[pair.Key]),"sha256")!=Text(Dict(pair.Value),"sha256")) throw new InvalidDataException("已有暂存程序不匹配");
            foreach(var pair in readyFiles) if(!files.ContainsKey(pair.Key) || Text(Dict(files[pair.Key]),"sha256")!=Text(Dict(pair.Value),"sha256")) throw new InvalidDataException("已有暂存文件清单不匹配");
            if(readyFiles.Count!=core.Count && readyFiles.Count!=files.Count) throw new InvalidDataException("已有暂存动画不完整");
            Verify(source,readyFiles);
            AtomicJson(Safe(cache,"receipt.json"),new {kind="program",version=version,archiveSha256=payloadSha,exeSha256=Text(Dict(files["BailongEnhanced.exe"]),"sha256"),manifestSha256=HashFile(Safe(source,"payload-manifest.json")),materialId=id});
            return source;
        }
    }
    static string Stage(string payloadPath) { return StageVerifiedPackage(payloadPath,VersionNumber,PayloadSha); }
    [STAThread] static int Main(string[] args) {
        string probe=null,payload=null;
        for(int i=0;i<args.Length;i++) {
            if(args[i]=="--stage-only" && i+1<args.Length) probe=args[++i];
            else if(args[i]=="--payload-path" && i+1<args.Length) payload=args[++i];
        }
        bool acquired=false;
        using(var mutex=new Mutex(false,"Local\\BailongProgramPatch-"+VersionNumber)) try {
            try { acquired=mutex.WaitOne(0); } catch(AbandonedMutexException) { acquired=true; }
            if(!acquired) throw new InvalidOperationException("另一个程序补丁正在准备，请稍后重试。");
            var source=Stage(payload);
            if(probe!=null) { AtomicJson(Path.GetFullPath(probe),new {passed=true,version=VersionNumber,source=source,payloadSha256=PayloadSha});return 0; }
            using(var process=Process.Start(new ProcessStartInfo {FileName=Safe(source,"BailongEnhanced.exe"),Arguments="--apply-program-update",WorkingDirectory=source,UseShellExecute=false,CreateNoWindow=false,WindowStyle=ProcessWindowStyle.Normal})) {
                process.WaitForExit();return process.ExitCode;
            }
        } catch(Exception error) {
            if(probe!=null) AtomicJson(Path.GetFullPath(probe),new {passed=false,error=error.Message});
            else MessageBox.Show("程序补丁准备失败："+error.Message+"\n原有程序和用户数据保持可用。","程序补丁包 "+VersionNumber,MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        } finally { if(acquired) mutex.ReleaseMutex(); }
    }
}
