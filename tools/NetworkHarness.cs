// Isolated, deterministic transport fixture. Never launches a staged EXE.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Diagnostics;

static class NetworkHarness {
    static string root;static byte[] archive;static string channel;
    static readonly JavaScriptSerializer json=new JavaScriptSerializer();
    static readonly Dictionary<string,object> checks=new Dictionary<string,object>();
    static void Assert(bool ok,string message) {if(!ok) throw new Exception(message);}
    static void Reject(Action run) {bool failed=false;try {run();} catch {failed=true;} Assert(failed,"Expected rejection");}
    static string State(string name) {var local=Path.Combine(root,name);Directory.CreateDirectory(local);Environment.SetEnvironmentVariable("LOCALAPPDATA",local);Environment.SetEnvironmentVariable("BAILONG_ISOLATED","1");return local;}
    static Dictionary<string,object> Data() {return (Dictionary<string,object>)json.DeserializeObject(channel);}
    static ProgramDownload Downloader(string info,byte[] bytes,List<string> requests) {
        return new ProgramDownload(delegate(string url,Action<Stream> read) {requests.Add(url);using(var s=new MemoryStream(url==ProgramDownload.Channel ? Encoding.UTF8.GetBytes(info) : bytes)) read(s);});
    }
    static void Run(string name,Action test) {test();checks[name]=true;}
    static int Main(string[] args) {
        root=Path.GetFullPath(args[0]);archive=File.ReadAllBytes(Path.Combine(root,"program.zip"));channel=File.ReadAllText(Path.Combine(root,"program-channel.json"));
        var watch=Stopwatch.StartNew();
        try {
            Run("latestCumulativeProgramStagesWithoutOldRuntime",delegate {
                var local=State("fresh");var requests=new List<string>();var d=Downloader(channel,archive,requests);var source=d.Prepare(local,s=>{},(n,t)=>{});
                Assert(File.ReadAllText(Path.Combine(source,"app","version.py")).Contains("1.2.1"),"Did not stage latest program");
                Assert(requests.Count==2 && requests[0]==ProgramDownload.Channel && requests[1].Contains("v1.2.1/"),"Unexpected downloads");
                Assert(!Directory.Exists(Path.Combine(source,"outputs")),"Fresh setup downloaded animations");
                Assert(File.Exists(Path.Combine(local,"BailongEnhanced","updates","1.2.1","program","receipt.json")),"No handoff receipt");
            });
            Run("animationLatestCanKeepPreviousProgramTarget",delegate {
                var d=Data();var target=ProgramDownload.Parse(d);Assert(target.Version=="1.2.1","Program must follow channel target, not installer assembly or animation release");
            });
            Run("verifiedCacheAvoidsSecondPackageDownload",delegate {
                var local=State("cache");var calls=new List<string>();var d=Downloader(channel,archive,calls);d.Prepare(local,s=>{},(n,t)=>{});d.Prepare(local,s=>{},(n,t)=>{});
                Assert(calls.Count==3,"Already verified archive was downloaded again");
            });
            Run("corruptDownloadedCacheCanRetryAndRecover",delegate {
                var local=State("corrupt-download-cache");var calls=new List<string>();var d=Downloader(channel,archive,calls);var target=ProgramDownload.Parse(Data());
                var cache=Path.Combine(local,"BailongEnhanced","first-install");var ready=d.Download(target,cache,(n,t)=>{});
                File.WriteAllText(ready,"damaged-download");
                var recovered=d.Download(target,cache,(n,t)=>{});
                Assert(Convert.ToBase64String(File.ReadAllBytes(recovered))==Convert.ToBase64String(archive),"Corrupt download was not recovered");
                Assert(calls.Count==2,"Recovery did not download exactly once");
            });
            Run("settingsAndVerifiedMediaSurviveUpgrade",delegate {
                var local=State("existing");var install=Path.Combine(local,"Programs","BailongEnhanced");
                Directory.CreateDirectory(install);File.WriteAllText(Path.Combine(install,"installations.json"),"{\"current\":\"1.0.0-fixture\"}");
                var media=Path.Combine(install,"versions","1.0.0-fixture","outputs","白龙桌宠素材");Directory.CreateDirectory(media);
                File.WriteAllBytes(Path.Combine(media,"idle.webp"),Encoding.UTF8.GetBytes("verified-media-fixture"));File.WriteAllText(Path.Combine(media,"素材清单.json"),"{\"idle\":{\"file\":\"idle.webp\"}}");
                var settings=Path.Combine(local,"BailongEnhanced","settings.json");Directory.CreateDirectory(Path.GetDirectoryName(settings));File.WriteAllText(settings,"{\"theme\":\"saved\"}");
                var source=Downloader(channel,archive,new List<string>()).Prepare(local,s=>{},(n,t)=>{});
                Assert(File.Exists(Path.Combine(source,"outputs","白龙桌宠素材","idle.webp")),"Verified local media not reused");
                Assert(File.ReadAllText(settings)=="{\"theme\":\"saved\"}","Changed settings");
            });
            Run("newerLocalProgramStopsBeforePackageDownload",delegate {
                var local=State("newer");var install=Path.Combine(local,"Programs","BailongEnhanced");Directory.CreateDirectory(install);
                File.WriteAllText(Path.Combine(install,"installations.json"),"{\"current\":\"1.9.2-fixture\"}");
                var calls=new List<string>();Reject(()=>Downloader(channel,archive,calls).Prepare(local,s=>{},(n,t)=>{}));Assert(calls.Count==1,"Downloaded a downgrade");
            });
            Run("foreignUrlsVersionsProtocolsAndBooleansRejected",delegate {
                foreach(var field in new[]{"url","name","sha256","bytes"}) {
                    var d=Data();var p=(Dictionary<string,object>)d["program"];p[field]=field=="bytes" ? (object)true : "https://evil.example/file.zip";Reject(()=>ProgramDownload.Parse(d));
                }
                foreach(var field in new[]{"schema","installerProtocol","version"}) {
                    var d=Data();d[field]=field=="version" ? (object)"01.2.1" : 2;Reject(()=>ProgramDownload.Parse(d));
                }
            });
            Run("redirectAllowlistRejectsCredentialsAndLookalikeHosts",delegate {
                foreach(var url in new[]{"http://github.com/file","https://github.com.evil.example/file","https://user:pass@github.com/file","https://github.com:8443/file","https://localhost/file"}) Assert(!ProgramDownload.Allowed(new Uri(url)),"Unsafe redirect allowed");
                Assert(ProgramDownload.Allowed(new Uri("https://release-assets.githubusercontent.com/file?token=public-signed-url")),"Official asset redirect rejected");
            });
            Run("oversizeMetadataStopsBeforePackageDownload",delegate {
                State("oversized");var calls=new List<string>();Reject(()=>Downloader(new string('x',65537),archive,calls).Resolve());Assert(calls.Count==1,"Oversize data used");
            });
            Run("truncatedAndAlteredDownloadsNeverStage",delegate {
                foreach(var mode in new[]{"short","changed","long"}) {
                    var local=State(mode);byte[] bytes;
                    if(mode=="short") {bytes=new byte[archive.Length-1];Array.Copy(archive,bytes,bytes.Length);}
                    else if(mode=="long") {bytes=new byte[archive.Length+1];Array.Copy(archive,bytes,archive.Length);}
                    else {bytes=(byte[])archive.Clone();bytes[100]^=1;}
                    Reject(()=>Downloader(channel,bytes,new List<string>()).Prepare(local,s=>{},(n,t)=>{}));
                    Assert(!Directory.Exists(Path.Combine(local,"BailongEnhanced","updates")),"Invalid package reached staging");
                }
            });
            Run("networkFailureDoesNotUseEmbeddedOldPayload",delegate {
                var local=State("network-failed");var d=new ProgramDownload((url,read)=>{throw new IOException("offline");});
                Reject(()=>d.Prepare(local,s=>{},(n,t)=>{}));Assert(!Directory.Exists(Path.Combine(local,"BailongEnhanced","updates")),"Used a fallback payload");
            });
            Run("retryReusesOnePartialInsteadOfAccumulatingPackages",delegate {
                var local=State("retry");var shortBytes=new byte[archive.Length/2];Array.Copy(archive,shortBytes,shortBytes.Length);
                var calls=new List<string>();Reject(()=>Downloader(channel,shortBytes,calls).Prepare(local,s=>{},(n,t)=>{}));
                var folder=Path.Combine(local,"BailongEnhanced","first-install","1.2.1");
                Assert(Directory.GetFiles(folder,"*.part").Length==1,"Unexpected partial count");
                Downloader(channel,archive,calls).Prepare(local,s=>{},(n,t)=>{});
                Assert(Directory.GetFiles(folder,"*.part").Length==0,"Successful retry left partials");
            });
            Run("cancelledDownloadDoesNotPrepareProgram",delegate {
                var local=State("cancel");var d=Downloader(channel,archive,new List<string>());
                Reject(()=>d.Prepare(local,s=>{},(n,t)=>d.Cancel()));Assert(!Directory.Exists(Path.Combine(local,"BailongEnhanced","updates")),"Cancelled package staged");
            });
            Run("changedStagedExeIsRejected",delegate {
                var local=State("tampered");var d=Downloader(channel,archive,new List<string>());var source=d.Prepare(local,s=>{},(n,t)=>{});
                File.WriteAllText(Path.Combine(source,"BailongEnhanced.exe"),"changed");Reject(()=>d.Prepare(local,s=>{},(n,t)=>{}));
            });
            Run("noEmbeddedProgramResource",delegate {
                foreach(var name in typeof(NetworkHarness).Assembly.GetManifestResourceNames()) Assert(name!="Bailong.Program","Old program embedded");
            });
            File.WriteAllText(Path.Combine(root,"native-checks.json"),json.Serialize(new {passed=true,checks=checks,elapsedMs=watch.ElapsedMilliseconds,deploymentExecuted=false,publicNetworkUsed=false,temporaryFilesRetained=true}));return 0;
        } catch(Exception e) {
            File.WriteAllText(Path.Combine(root,"native-checks.json"),json.Serialize(new {passed=false,checks=checks,error=e.ToString()}));return 1;
        }
    }
}
