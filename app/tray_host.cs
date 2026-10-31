// Small fixed-path Shell owner. No polling, startup entries, or model/user data.
using System;
using System.IO;
using System.IO.Pipes;
using System.Drawing;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Collections.Generic;
[assembly:System.Reflection.AssemblyTitle("白龙桌宠增强版")]
[assembly:System.Reflection.AssemblyProduct("白龙桌宠增强版")]
[assembly:System.Reflection.AssemblyVersion("1.0.0.0")]

class TrayHost : Form {
    const int Callback=0x8000+101;
    static readonly Guid Identity=new Guid("6baea166-d3d9-4ffb-88c4-39a669a20e69");
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct Data {
        public int size; public IntPtr window; public uint id,flags,message; public IntPtr icon;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=128)] public string tip;
        public uint state,stateMask;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=256)] public string info;
        public uint version;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=64)] public string title;
        public uint infoFlags;public Guid guid; public IntPtr balloon;
    }
    [StructLayout(LayoutKind.Sequential)] struct Rect {public int left,top,right,bottom;}
    [StructLayout(LayoutKind.Sequential)] struct Point {public int x,y;}
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct MonitorInfo {public int size;public Rect monitor,work;public uint flags;[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string device;}
    [StructLayout(LayoutKind.Sequential)] struct Identifier {public uint size;public IntPtr window;public uint id;public Guid guid;}
    [DllImport("shell32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool Shell_NotifyIcon(uint command,ref Data data);
    [DllImport("shell32.dll")] static extern int Shell_NotifyIconGetRect(ref Identifier id,out Rect rect);
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr icon);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
    [DllImport("user32.dll")] static extern IntPtr MonitorFromRect(ref Rect rect,uint flags);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool GetMonitorInfo(IntPtr monitor,ref MonitorInfo info);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll",SetLastError=true)] static extern bool AllowSetForegroundWindow(uint process);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int RegisterWindowMessage(string message);
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    readonly JavaScriptSerializer json=new JavaScriptSerializer(); readonly object writeLock=new object();
    StreamWriter writer; NamedPipeClientStream pipe; Data data; bool registered=false; string lastIcon="";IntPtr icon=IntPtr.Zero;
    int taskbarCreated=RegisterWindowMessage("TaskbarCreated");string pipeName,secret;int parent;
    TrayHost(string name,string token,int pid) {
        pipeName=name;secret=token;parent=pid;ShowInTaskbar=false;FormBorderStyle=FormBorderStyle.None;Opacity=0;
        Text="白龙桌宠托盘";
    }
    protected override void SetVisibleCore(bool value){base.SetVisibleCore(false);}
    Data Fresh(uint flags){return new Data{size=Marshal.SizeOf(typeof(Data)),window=Handle,id=1,flags=flags|0x20,guid=Identity,message=Callback,tip="",info="",title=""};}
    void Send(object value) {
        ThreadPool.QueueUserWorkItem(delegate {try{lock(writeLock){if(writer!=null){writer.WriteLine(json.Serialize(value));writer.Flush();}}}catch(IOException){}catch(ObjectDisposedException){}});
    }
    void Add(){
        data=Fresh(1|2);data.icon=icon;
        registered=Shell_NotifyIcon(0,ref data);
        if(registered){Data v=Fresh(0);v.version=4;Shell_NotifyIcon(4,ref v);}
        Send(new {kind="ready",secret=secret,ok=registered,error=registered?0:Marshal.GetLastWin32Error()});
    }
    void Geometry(string kind){
        var id=new Identifier{size=(uint)Marshal.SizeOf(typeof(Identifier)),window=Handle,id=1,guid=Identity};Rect r;Point point;GetCursorPos(out point);
        int code=Shell_NotifyIconGetRect(ref id,out r);
        var monitor=new MonitorInfo{size=Marshal.SizeOf(typeof(MonitorInfo))};GetMonitorInfo(MonitorFromRect(ref r,2),ref monitor);
        Send(new {kind=kind,x=point.x,y=point.y,left=r.left,top=r.top,width=r.right-r.left,height=r.bottom-r.top,geometryValid=code==0,monitor=monitor.device,monitorLeft=monitor.monitor.left,monitorTop=monitor.monitor.top});
    }
    protected override void WndProc(ref Message m){
        if(m.Msg==taskbarCreated && icon!=IntPtr.Zero){registered=false;Add();}
        if(m.Msg==Callback){int code=(int)((long)m.LParam&0xffff);
            if(code==0x200 || code==0x406)Geometry("hover");
            else if(code==0x400 || code==0x401 || code==0x202){Geometry("click");}
            else if(code==0x203){Geometry("doubleClick");}
            else if(code==0x7b || code==0x205){
                SetForegroundWindow(Handle);
                // The actual QMenu belongs to the parent process, not this
                // fixed-path Shell owner. Delegate only for this user action.
                AllowSetForegroundWindow((uint)parent);Geometry("context");
            }
        }
        base.WndProc(ref m);
    }
    void Apply(Dictionary<string,object> command){
        string kind=command.ContainsKey("kind")?Convert.ToString(command["kind"]):"";
        if(kind=="close"){Close();Application.ExitThread();return;}
        if(kind=="focus"){var d=Fresh(0);Shell_NotifyIcon(3,ref d);return;}
        if(kind=="message"){
            var d=Fresh(0x10);d.info=Convert.ToString(command["text"]);d.title=Convert.ToString(command["title"]);d.infoFlags=0x01|0x10|0x80;Shell_NotifyIcon(1,ref d);return;
        }
        if(kind!="icon")return;
        string raw=Convert.ToString(command["png"]);if(raw==lastIcon && registered)return;
        IntPtr next;
        using(var stream=new MemoryStream(Convert.FromBase64String(raw)))using(var bitmap=new Bitmap(stream)){next=bitmap.GetHicon();}
        IntPtr previous=icon;icon=next;
        if(!registered)Add();else{var d=Fresh(2);d.icon=icon;if(!Shell_NotifyIcon(1,ref d)){registered=false;Add();}}
        if(previous!=IntPtr.Zero)DestroyIcon(previous);lastIcon=raw;
    }
    void Connect(){
        try {
            pipe=new NamedPipeClientStream(".",pipeName,PipeDirection.InOut,PipeOptions.Asynchronous);pipe.Connect(8000);
            writer=new StreamWriter(pipe,new System.Text.UTF8Encoding(false));writer.AutoFlush=true;
            Send(new {kind="connected",secret=secret});
            using(var reader=new StreamReader(pipe,new System.Text.UTF8Encoding(false))){string line;
                while((line=reader.ReadLine())!=null){if(line.Length>262144)break;var cmd=json.Deserialize<Dictionary<string,object>>(line);BeginInvoke(new Action(()=>{try{Apply(cmd);}catch(Exception e){Send(new {kind="error",error=e.Message});}}));}
            }
        }catch(Exception e){Send(new {kind="error",error=e.Message});}
        finally{try{BeginInvoke(new Action(()=>{Close();Application.ExitThread();}));}catch(InvalidOperationException){}}
    }
    protected override void OnHandleCreated(EventArgs e){base.OnHandleCreated(e);new Thread(Connect){IsBackground=true}.Start();
        new Thread(()=>{try{Process.GetProcessById(parent).WaitForExit();}catch(ArgumentException){}try{BeginInvoke(new Action(()=>{Close();Application.ExitThread();}));}catch(InvalidOperationException){}}){IsBackground=true}.Start();}
    void Cleanup(){if(registered){var d=Fresh(0);Shell_NotifyIcon(2,ref d);registered=false;}if(icon!=IntPtr.Zero){DestroyIcon(icon);icon=IntPtr.Zero;}if(pipe!=null){pipe.Dispose();pipe=null;}}
    protected override void OnFormClosed(FormClosedEventArgs e){Cleanup();base.OnFormClosed(e);}
    protected override void Dispose(bool disposing){if(disposing)Cleanup();base.Dispose(disposing);}
    [STAThread] static void Main(string[] args){
        if(args.Length==1 && args[0]=="--self-check"){return;}
        if(args.Length!=3)return;int pid;if(!int.TryParse(args[2],out pid))return;
        try{SetProcessDpiAwarenessContext(new IntPtr(-4));}catch(EntryPointNotFoundException){}
        Application.EnableVisualStyles();using(var app=new TrayHost(args[0],args[1],pid)){var handle=app.Handle;Application.Run();}
    }
}
