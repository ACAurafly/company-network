using System;
using System.Threading;
using System.Threading.Tasks;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
namespace CompanyNetwork {
internal static class LifecycleTests {
 static void Assert(bool value, string name) { if (!value) throw new Exception(name); Console.WriteLine("PASS " + name); }
 static int Main() {
  try {
   string key = "Test." + Guid.NewGuid().ToString("N");
   bool connected = true, fail = false;
   ManualResetEvent entered = new ManualResetEvent(false), release = new ManualResetEvent(false);
   Func<ConnectionSnapshot> read = delegate { return new ConnectionSnapshot { Outer = connected, Inner = connected, Route = connected, SessionsReady = connected }; };
   using (OperationController first = new OperationController(key, delegate(string action, Action<string> p, Action check) {
    if (action == "--connect") { entered.Set(); release.WaitOne(); check(); connected = true; }
    else { if (fail) throw new AppProblem("disconnect_failed", "injected"); connected = false; }
    return "done";
   }, read)) using (OperationController second = new OperationController(key, delegate(string a, Action<string> p, Action c) { if(fail) throw new AppProblem("disconnect_failed", "injected"); connected = false; return "done"; }, read)) {
    Assert(first.Read().Kind == "connected", "restart reads actual session");
    fail = true; try { second.Execute("--disconnect", delegate {}); } catch(AppProblem) {}
    Assert(first.Read().Kind == "connected", "failed disconnect retains connected facts"); fail = false; second.Execute("--disconnect", delegate {});
    connected = false;
    Task connect = Task.Run(delegate { try { first.Execute("--connect", delegate {}); } catch(AppProblem) {} });
    Assert(entered.WaitOne(2000), "connection entered");
    bool busy = false; try { second.Execute("--connect", delegate {}); } catch(AppProblem e) { busy = e.Code == "operation_busy"; }
    Assert(busy, "repeated connection rejected");
    Task stop = Task.Run(delegate { second.Execute("--disconnect", delegate {}); });
    Thread.Sleep(100); release.Set(); Task.WaitAll(connect, stop);
    Assert(!connected && first.Read().Kind == "disconnected", "cross controller stop prevents late reconnect");
   }
   string lateKey = "Test." + Guid.NewGuid().ToString("N");
   connected = false; entered.Reset(); release.Reset();
   using(OperationController late = new OperationController(lateKey, delegate(string a, Action<string> p, Action check) {
    if(a == "--connect") { entered.Set(); release.WaitOne(); connected = true; } else connected = false;
    return "done";
   }, read)) using(OperationController signal = new OperationController(lateKey, delegate(string a, Action<string> p, Action check) { connected = false; return "done"; }, read)) {
    Task pending = Task.Run(delegate { try { late.Execute("--connect", delegate {}); } catch(AppProblem) {} });
    Assert(entered.WaitOne(2000), "noncancellable adapter entered"); signal.RequestStop(); release.Set(); pending.Wait();
    Assert(!connected, "late adapter success is cleaned before returning");
   }
   using(OperationController partial = new OperationController("Test."+Guid.NewGuid().ToString("N"), delegate(string a,Action<string> p, Action c){return "done";}, delegate { return new ConnectionSnapshot { Outer = true, Inner = true, Route = true }; }))
    Assert(partial.Read().Kind == "recovering", "pending sessions cannot claim ready from stale route");
   connected = true;
   using(OperationController cleanup = new OperationController("Test."+Guid.NewGuid().ToString("N"), delegate(string a, Action<string> p, Action c) {
    throw new AppProblem(a == "--connect" ? "connect_failed" : "disconnect_failed", "fixture");
   },read)) {
    bool retained = false; try { cleanup.Execute("--connect", delegate {}); } catch(AppProblem e) { retained = e.Code == "cleanup_failed"; }
    Assert(retained && cleanup.Read().Kind == "connected", "cleanup failure cannot report disconnected");
   }
   using(OperationController partialStop = new OperationController("Test."+Guid.NewGuid().ToString("N"),delegate(string a,Action<string> p,Action c){return "done";},delegate{return new ConnectionSnapshot { Outer=true };})) {
    bool rejected=false; try { partialStop.Execute("--disconnect",delegate {}); } catch(AppProblem e){rejected=e.Code=="disconnect_unconfirmed";}
    Assert(rejected,"successful command cannot conceal remaining outer session");
   }
   using(OperationController unknown = new OperationController("Test."+Guid.NewGuid().ToString("N"),delegate(string a,Action<string> p,Action c){return "done";},delegate{throw new AppProblem("status_unavailable","fixture");})) {
    bool rejected=false; try {unknown.Execute("--disconnect",delegate {});} catch(AppProblem e){rejected=e.Code=="status_unavailable";}
    Assert(rejected,"query failure cannot confirm disconnect");
   }
   TestShortcuts();
   return 0;
  } catch(Exception e) { Console.Error.WriteLine(e); return 1; }
 }
 static void TestShortcuts() {
  string root = Path.Combine(Path.GetTempPath(), "CompanyNetwork.Shortcuts."+Guid.NewGuid().ToString("N"));
  Directory.CreateDirectory(root);
  string launcher = Path.Combine(root,"CompanyNetwork.exe"); File.WriteAllText(launcher,"fixture");
  Type t = Type.GetTypeFromProgID("WScript.Shell"); object shell = Activator.CreateInstance(t);
  try {
   UserInstall.UpdateShortcuts(root,launcher,root,true,false);
   Assert(Directory.GetFiles(root,"*.lnk").Length == 1, "new installation has single entry");
   string[] names = {"公司网络-连接.lnk","公司网络-断开.lnk","公司网络-GPT.lnk"};
   string[] args = {"--connect","--disconnect","--gpt"};
   for(int i=0;i<3;i++) MakeShortcut(t,shell,Path.Combine(root,names[i]),launcher,root,args[i]);
   UserInstall.UpdateShortcuts(root,launcher,root,true,false);
   UserInstall.UpdateShortcuts(root,launcher,root,true,false);
   Assert(Directory.GetFiles(root,"*.lnk").Length == 1, "upgrade and repeated upgrade consolidate owned entries");
   string foreign = Path.Combine(root,names[0]); MakeShortcut(t,shell,foreign,launcher,root,"--remove");
   byte[] before = File.ReadAllBytes(foreign); bool conflict = false;
   try { UserInstall.UpdateShortcuts(root,launcher,root,true,false); } catch(AppProblem e) { conflict = e.Code == "shortcut_conflict"; }
   Assert(conflict && Convert.ToBase64String(before) == Convert.ToBase64String(File.ReadAllBytes(foreign)), "same target with foreign arguments is preserved and reported");
   UserInstall.UpdateShortcuts(root,launcher,root,true,true);
   string unified = Path.Combine(root,"公司网络.lnk"); MakeShortcut(t,shell,unified,Path.Combine(root,"other.exe"),root,"--ui");
   before=File.ReadAllBytes(unified); conflict=false;
   try { UserInstall.UpdateShortcuts(root,launcher,root,true,false); } catch(AppProblem e) { conflict=e.Code=="shortcut_conflict"; }
   Assert(conflict && Convert.ToBase64String(before)==Convert.ToBase64String(File.ReadAllBytes(unified)), "foreign unified entry is never overwritten");
   bool rejected=false; try { UserInstall.UpdateShortcuts(root,launcher,root,false,false); } catch(AppProblem) {rejected=true;}
   Assert(rejected,"upgrade requires installation ownership");
  } finally { Marshal.FinalReleaseComObject(shell); Directory.Delete(root,true); }
 }
 static void MakeShortcut(Type t, object shell, string path, string launcher, string directory, string args) {
  object shortcut=t.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{path});
  try { Type st=shortcut.GetType();
   st.InvokeMember("TargetPath",BindingFlags.SetProperty,null,shortcut,new object[]{launcher});
   st.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,shortcut,new object[]{directory});
   st.InvokeMember("Arguments",BindingFlags.SetProperty,null,shortcut,new object[]{args});
   st.InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,null);
  } finally {Marshal.FinalReleaseComObject(shortcut);}
 }

}
}
